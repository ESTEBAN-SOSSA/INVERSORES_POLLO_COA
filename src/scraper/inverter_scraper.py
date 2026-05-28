"""Extracción de inversores y sus series de generación desde server.growatt.com.

Contratos verificados contra el portal real (POLLO COA, plant 1878757):

  Lista de inversores:
    POST /panel/getDevicesByPlantList  {plantId, currPage}
      → obj.pages (paginación), obj.datas = [ {sn, deviceTypeName, deviceModel,
        alias, status, nominalPower, datalogSn, eToday, eMonth, eTotal, pac...} ]

  Charts (POST /energy/compare/getDevices{X}Chart):
    body: plantId, jsonData=[{type:<deviceTypeName>, sn, params}], (date|year)
    respuesta: obj = [ {datas:{<key>:[...]}, sn, type, params} ]   ← obj es LISTA

    | Chart            | param extra      | params            | key     | longitud |
    | getDevicesDayChart   | date=YYYY-MM-DD | pac              | pac     | 288 (12/h) |
    | getDevicesMonthChart | date=YYYY-MM    | energy,autoEnergy | energy  | días-mes  |
    | getDevicesYearChart  | year=YYYY       | energy,autoEnergy | energy  | 12        |
    | getDevicesTotalChart | year=YYYY       | energy,autoEnergy | energy  | N años    |
"""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from playwright.sync_api import Page

from src.scraper.growatt_client import GrowattClient

# Pausa entre llamadas para no saturar el portal.
THROTTLE_S = 0.25
SAMPLES_PER_HOUR = 12  # pac cada 5 min → 12 muestras por hora


# --------------------------------------------------------------------------- #
#  Helpers de parseo
# --------------------------------------------------------------------------- #
def _series(resp: Any, *keys: str) -> list:
    """Devuelve la primera serie no vacía de obj[0].datas[key]."""
    obj = resp.get("obj") if isinstance(resp, dict) else None
    if not isinstance(obj, list) or not obj:
        return []
    first = obj[0]
    datas = first.get("datas") if isinstance(first, dict) else None
    if not isinstance(datas, dict):
        return []
    for k in keys:
        v = datas.get(k)
        if v:
            return v
    return []


def _chart(client: GrowattClient, popup: Page, endpoint: str, plant_id: str,
           sn: str, devtype: str, params: str, extra: dict) -> Any:
    jsondata = json.dumps([{"type": devtype, "sn": sn, "params": params}])
    body = {"plantId": plant_id, "jsonData": jsondata, **extra}
    resp = client.server_post_json(popup, "/energy/compare/" + endpoint, body)
    time.sleep(THROTTLE_S)
    return resp


def _num(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
#  Lista de inversores
# --------------------------------------------------------------------------- #
def list_inverters_for_plant(client: GrowattClient, popup: Page, plant_id: str) -> list[dict]:
    """Inversores de la planta (paginado, dedup por SN)."""
    inverters: dict[str, dict] = {}
    page_num = 1
    pages = 1
    while page_num <= pages:
        resp = client.server_post_json(
            popup, "/panel/getDevicesByPlantList",
            {"plantId": plant_id, "currPage": page_num},
        )
        obj = resp.get("obj") if isinstance(resp, dict) else None
        if not isinstance(obj, dict):
            break
        pages = int(obj.get("pages", 1) or 1)
        for d in obj.get("datas", []) or []:
            sn = d.get("sn")
            if sn and sn not in inverters:
                inverters[sn] = d
        page_num += 1
        time.sleep(THROTTLE_S)
    return list(inverters.values())


# --------------------------------------------------------------------------- #
#  Histórico: span de años, meses y días
# --------------------------------------------------------------------------- #
def fetch_year_span(client: GrowattClient, popup: Page, plant_id: str, sn: str,
                    devtype: str, current_year: int) -> tuple[list[int], dict[int, float]]:
    """TotalChart → cuántos años de histórico hay. Devuelve (years, energía/año)."""
    resp = _chart(client, popup, "getDevicesTotalChart", plant_id, sn, devtype,
                  "energy,autoEnergy", {"year": str(current_year)})
    series = _series(resp, "energy", "autoEnergy")
    n = len(series)
    if n <= 0:
        return [current_year], {current_year: 0.0}
    years = list(range(current_year - n + 1, current_year + 1))
    return years, {y: (_num(series[i]) or 0.0) for i, y in enumerate(years)}


def fetch_inverter_history(
    client: GrowattClient, popup: Page, plant_id: str, sn: str, devtype: str,
    current_year: int, no_history: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Devuelve (day_rows, month_rows) del inversor.

    month_rows: 1 fila por mes con energía > 0 (reading_date = YYYY-MM-01).
    day_rows:   1 fila por día con energía > 0 (reading_date = YYYY-MM-DD).
    Si no_history → sólo el año actual.
    """
    if no_history:
        years = [current_year]
    else:
        years, _ = fetch_year_span(client, popup, plant_id, sn, devtype, current_year)

    month_rows: list[dict] = []
    day_rows: list[dict] = []

    for year in years:
        resp = _chart(client, popup, "getDevicesYearChart", plant_id, sn, devtype,
                      "energy,autoEnergy", {"year": str(year)})
        months = _series(resp, "energy", "autoEnergy")  # 12 valores
        for mi, mval in enumerate(months):
            kwh = _num(mval)
            if not kwh or kwh <= 0:
                continue
            month = mi + 1
            month_rows.append({
                "granularity": "month",
                "reading_date": date(year, month, 1),
                "reading_hour": None,
                "energy_kwh": kwh,
            })
            # Bajar detalle diario sólo de los meses con generación.
            resp_m = _chart(client, popup, "getDevicesMonthChart", plant_id, sn, devtype,
                            "energy,autoEnergy", {"date": f"{year}-{month:02d}"})
            days = _series(resp_m, "energy", "autoEnergy")
            for di, dval in enumerate(days):
                dkwh = _num(dval)
                if not dkwh or dkwh <= 0:
                    continue
                try:
                    rd = date(year, month, di + 1)
                except ValueError:
                    continue
                day_rows.append({
                    "granularity": "day",
                    "reading_date": rd,
                    "reading_hour": None,
                    "energy_kwh": dkwh,
                })
    return day_rows, month_rows


# --------------------------------------------------------------------------- #
#  Horario (5 min → 24 horas)
# --------------------------------------------------------------------------- #
def fetch_inverter_hourly_for_date(
    client: GrowattClient, popup: Page, plant_id: str, sn: str, devtype: str, day: date,
) -> list[dict]:
    """DayChart (pac 5-min) → 24 filas horarias (noche = 0)."""
    resp = _chart(client, popup, "getDevicesDayChart", plant_id, sn, devtype,
                  "pac", {"date": day.strftime("%Y-%m-%d")})
    pac = _series(resp, "pac")
    rows: list[dict] = []
    for hour in range(24):
        chunk = pac[hour * SAMPLES_PER_HOUR:(hour + 1) * SAMPLES_PER_HOUR]
        watts = [(_num(x) or 0.0) for x in chunk]
        # Energía de la hora: cada muestra son 5 min → Wh = W * 5/60; kWh = /1000
        kwh = sum(w * (5.0 / 60.0) for w in watts) / 1000.0
        peak = max(watts) if watts else 0.0
        avg = (sum(watts) / len(watts)) if watts else 0.0
        rows.append({
            "granularity": "hour",
            "reading_date": day,
            "reading_hour": hour,
            "energy_kwh": round(kwh, 4),
            "peak_power_w": round(peak, 2),
            "avg_power_w": round(avg, 2),
            "raw": {"samples_5min_w": watts},
        })
    return rows
