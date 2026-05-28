"""Recon: disparar showPlant para POLLO COA, capturar popup + getDevicesByPlantList."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.config import settings
from src.scraper.growatt_client import GrowattClient

OUT = Path("scripts/_recon")

PLANT_ID = "1878757"
SERVER = "1"
ACCOUNT = "2fe88bc7aebf5bbf4d4d0f8a85a0c97f"


def main() -> None:
    client = GrowattClient(headless=True)
    client.start()
    try:
        client.ensure_login(interactive=False)
        ctx = client.ctx
        page = ctx.new_page()
        page.goto(settings.oss_base + "/index", wait_until="networkidle",
                  timeout=settings.nav_timeout_ms)
        time.sleep(2)

        # Capturar tráfico de TODAS las páginas del contexto.
        traffic: list[dict] = []
        ctx.on("response", lambda r: traffic.append(
            {"status": r.status, "method": r.request.method, "url": r.url}))

        popup = None
        try:
            with ctx.expect_page(timeout=15000) as pinfo:
                page.evaluate("([s,a,p]) => showPlant(s,a,p)", [SERVER, ACCOUNT, PLANT_ID])
            popup = pinfo.value
            popup.wait_for_load_state("domcontentloaded", timeout=settings.nav_timeout_ms)
            time.sleep(3)
            print("POPUP url:", popup.url)
        except Exception as e:
            print("No popup:", e)

        target = popup or page
        # Intentar getDevicesByPlantList desde la página server.
        result = None
        if popup:
            try:
                result = popup.evaluate(
                    """async ([plantId]) => {
                        const r = await fetch('/panel/getDevicesByPlantList', {
                            method:'POST',
                            headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                            body: new URLSearchParams({plantId: plantId, currPage: 1}).toString(),
                            credentials:'include'
                        });
                        const t = await r.text();
                        try { return {status:r.status, json: JSON.parse(t)}; }
                        catch(e){ return {status:r.status, text:t.slice(0,500)}; }
                    }""",
                    [PLANT_ID],
                )
            except Exception as e:
                result = {"error": str(e)}

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "showplant_devices.json").write_text(
            json.dumps({"popup_url": popup.url if popup else None, "devices": result},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "traffic_showplant.json").write_text(
            json.dumps(traffic, ensure_ascii=False, indent=2), encoding="utf-8")

        print("DEVICES RESULT:", json.dumps(result, ensure_ascii=False)[:800])
    finally:
        client.close()


if __name__ == "__main__":
    main()
