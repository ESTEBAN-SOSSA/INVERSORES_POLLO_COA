"""Recon: probar los 4 charts para un inversor de POLLO COA."""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from src.config import settings
from src.scraper.growatt_client import GrowattClient

OUT = Path("scripts/_recon")
PLANT_ID = "1878757"
SERVER = "1"
ACCOUNT = "2fe88bc7aebf5bbf4d4d0f8a85a0c97f"
SN = "ZFEDCA6003"
DEVTYPE = "max"


def main() -> None:
    client = GrowattClient(headless=True)
    client.start()
    try:
        client.ensure_login(interactive=False)
        popup = client.open_server_session(SERVER, ACCOUNT, PLANT_ID)
        print("popup:", popup.url)
        today = date.today()

        def chart(endpoint: str, extra: dict, params: str):
            jsondata = json.dumps([{"type": DEVTYPE, "sn": SN, "params": params}])
            body = {"plantId": PLANT_ID, "jsonData": jsondata, **extra}
            return client.server_post_json(popup, "/energy/compare/" + endpoint, body)

        probes = {
            "DayChart(hour,pac)": chart("getDevicesDayChart",
                                        {"date": today.strftime("%Y-%m-%d")}, "pac"),
            "MonthChart(day)": chart("getDevicesMonthChart",
                                     {"date": today.strftime("%Y-%m")}, "energy,autoEnergy"),
            "YearChart(month)": chart("getDevicesYearChart",
                                      {"year": str(today.year)}, "energy,autoEnergy"),
            "TotalChart(year)": chart("getDevicesTotalChart",
                                      {"year": str(today.year)}, "energy,autoEnergy"),
        }
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "charts_probe.json").write_text(
            json.dumps(probes, ensure_ascii=False, indent=2), encoding="utf-8")
        for name, r in probes.items():
            obj = r.get("obj") if isinstance(r, dict) else None
            datas = obj.get("datas") if isinstance(obj, dict) else None
            shape = (list(datas.keys()) if isinstance(datas, dict) else
                     (f"list[{len(datas)}]" if isinstance(datas, list) else type(datas).__name__))
            print(f"{name}: result={r.get('result')} datas_keys/shape={shape}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
