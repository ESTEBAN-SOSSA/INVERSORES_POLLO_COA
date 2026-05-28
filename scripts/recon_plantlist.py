"""Recon: capturar el request/response real de plantManage/list."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.config import settings
from src.scraper.growatt_client import GrowattClient

OUT = Path("scripts/_recon")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    client = GrowattClient(headless=True)
    client.start()
    try:
        client.ensure_login(interactive=False)
        page = client.ctx.new_page()

        captured: list[dict] = []

        def on_request(req):
            if "plantManage/list" in req.url or "getDevicesByPlantList" in req.url:
                captured.append({"url": req.url, "method": req.method,
                                 "postData": req.post_data})

        bodies: list[dict] = []

        def on_response(resp):
            if "plantManage/list" in resp.url:
                try:
                    bodies.append({"url": resp.url, "json": resp.json()})
                except Exception:
                    bodies.append({"url": resp.url, "text": resp.text()[:1000]})

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(settings.oss_base + "/deviceManage/plantManage",
                  wait_until="networkidle", timeout=settings.nav_timeout_ms)
        time.sleep(4)

        (OUT / "plantlist_request.json").write_text(
            json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "plantlist_response.json").write_text(
            json.dumps(bodies, ensure_ascii=False, indent=2), encoding="utf-8")
        print("requests captured:", len(captured))
        print("responses captured:", len(bodies))
        if captured:
            print("postData ejemplo:", captured[0].get("postData"))
        if bodies and "json" in bodies[0]:
            j = bodies[0]["json"]
            print("keys:", list(j.keys()) if isinstance(j, dict) else type(j))
    finally:
        client.close()


if __name__ == "__main__":
    main()
