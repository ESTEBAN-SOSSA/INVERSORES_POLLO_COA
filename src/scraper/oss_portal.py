"""Lectura de la lista de plantas desde el portal OSS (oss.growatt.com).

La tabla del home embebe, por planta, un onclick `showPlant(server, account, plantId)`
y celdas con nombre/cuenta/ciudad/capacidad. De ahí sacamos el mapeo
plant_id → (server, account, name) que necesita el orquestador.
"""
from __future__ import annotations

import time

from src.config import settings
from src.scraper.growatt_client import GrowattClient

# Índices de columna verificados en la tabla del home.
_COL_STATUS = 3
_COL_NAME = 4
_COL_ACCOUNT = 6
_COL_CITY = 7
_COL_CREATED = 10
_COL_DEVICES = 11
_COL_CAPACITY = 12


def _parse_args(args: str) -> tuple[str, str, str]:
    """'1','2fe8...',1878757 → (server, account, plant_id)."""
    parts = [p.strip().strip("'\"") for p in args.split(",")]
    server, account, plant_id = parts[0], parts[1], parts[2]
    return server, account, plant_id


def list_plants(client: GrowattClient) -> list[dict]:
    """Todas las plantas del operador logueado."""
    assert client.ctx is not None
    page = client.ctx.new_page()
    try:
        page.goto(settings.oss_base + "/index", wait_until="networkidle",
                  timeout=settings.nav_timeout_ms)
        time.sleep(2)
        rows = page.evaluate(
            """() => {
                const out=[];
                document.querySelectorAll('[onclick*="showPlant"]').forEach(el=>{
                    const tr=el.closest('tr'); if(!tr) return;
                    const cells=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').trim());
                    const oc=el.getAttribute('onclick')||'';
                    const m=oc.match(/showPlant\\(([^)]*)\\)/);
                    if(m) out.push({args:m[1], cells});
                });
                return out;
            }"""
        )
    finally:
        page.close()

    plants: dict[str, dict] = {}
    for r in rows:
        try:
            server, account, plant_id = _parse_args(r["args"])
        except (IndexError, ValueError):
            continue
        cells = r["cells"]

        def cell(i: int) -> str:
            return cells[i] if i < len(cells) else ""

        if plant_id in plants:
            continue
        plants[plant_id] = {
            "plant_id": plant_id,
            "server": server,
            "account": account,
            "name": cell(_COL_NAME),
            "account_name": cell(_COL_ACCOUNT),
            "city": cell(_COL_CITY),
            "status": cell(_COL_STATUS),
            "created": cell(_COL_CREATED),
            "device_count": cell(_COL_DEVICES),
            "capacity": cell(_COL_CAPACITY),
        }
    return list(plants.values())


def find_plant(client: GrowattClient, plant_id: str) -> dict | None:
    pid = str(plant_id)
    for p in list_plants(client):
        if p["plant_id"] == pid:
            return p
    return None
