"""Orquestador de extracción por inversor.

Uso (ver EXTRACCION_INVERSORES.md):
    python -m src.scraper.inverter_main --plant_id 1878757 --hourly_days 1

Flags:
    --plant_id <ID>   procesa sólo esa planta (default: todas)
    --no_history      sólo año actual (recorta day+month)
    --hourly_days <N> días recientes con detalle 5-min (default 7; 0 desactiva)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta

from src.db.base import session_scope
from src.scraper.growatt_client import GrowattClient
from src.scraper.inverter_scraper import (
    fetch_inverter_history,
    fetch_inverter_hourly_for_date,
    list_inverters_for_plant,
)
from src.scraper.oss_portal import list_plants
from src.scraper.persist import (
    persist_inverter_history,
    persist_inverter_hourly,
    upsert_inverter_meta,
    upsert_plant,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Extracción Growatt por inversor")
    ap.add_argument("--plant_id", default=None, help="Procesar sólo esta planta")
    ap.add_argument("--no_history", action="store_true",
                    help="Sólo año actual (no baja años previos)")
    ap.add_argument("--hourly_days", type=int, default=7,
                    help="Días recientes con detalle 5-min (0 desactiva)")
    return ap.parse_args(argv)


def run(plant_id: str | None, no_history: bool, hourly_days: int) -> dict:
    current_year = date.today().year
    totals = {"plants": 0, "inverters": 0, "days": 0, "months": 0, "hours": 0}

    client = GrowattClient(headless=True)
    client.start()
    try:
        client.ensure_login(interactive=False)

        plants = list_plants(client)
        if plant_id:
            plants = [p for p in plants if p["plant_id"] == str(plant_id)]
        if not plants:
            raise SystemExit(f"No se encontró la planta {plant_id}")

        # Agrupar por account → una sesión server.growatt.com por account.
        by_account: dict[str, list[dict]] = defaultdict(list)
        for p in plants:
            by_account[p["account"]].append(p)

        for account, account_plants in by_account.items():
            server = account_plants[0]["server"]
            popup = client.open_server_session(server, account, account_plants[0]["plant_id"])

            for p in account_plants:
                pid = p["plant_id"]
                print(f"[planta] {p['name']} ({pid}) — account {p['account_name']}",
                      flush=True)
                with session_scope() as s:
                    upsert_plant(s, pid, p["name"], server=server, account=account,
                                 raw={k: p[k] for k in ("city", "capacity", "created",
                                                        "device_count", "status")})

                inverters = list_inverters_for_plant(client, popup, pid)
                print(f"  inversores: {len(inverters)}", flush=True)
                totals["plants"] += 1

                hourly_dates = [date.today() - timedelta(days=i)
                                for i in range(hourly_days)] if hourly_days > 0 else []

                for inv in inverters:
                    sn = inv.get("sn")
                    devtype = inv.get("deviceTypeName") or "max"
                    print(f"  - {sn} ({devtype}) {inv.get('deviceModel','')}", flush=True)
                    totals["inverters"] += 1

                    with session_scope() as s:
                        upsert_inverter_meta(s, pid, inv)

                    day_rows, month_rows = fetch_inverter_history(
                        client, popup, pid, sn, devtype, current_year,
                        no_history=no_history)
                    with session_scope() as s:
                        nd, nm = persist_inverter_history(s, pid, sn, day_rows, month_rows)
                    totals["days"] += nd
                    totals["months"] += nm
                    print(f"      day={nd} month={nm}", flush=True)

                    for d in hourly_dates:
                        hour_rows = fetch_inverter_hourly_for_date(
                            client, popup, pid, sn, devtype, d)
                        with session_scope() as s:
                            nh = persist_inverter_hourly(s, pid, sn, d, hour_rows)
                        totals["hours"] += nh
                    if hourly_dates:
                        print(f"      hours={24 * len(hourly_dates)} "
                              f"({len(hourly_dates)} días)", flush=True)
    finally:
        client.close()

    return totals


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    totals = run(args.plant_id, args.no_history, args.hourly_days)
    print(json.dumps(totals, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
