"""Prueba el login programático (sin captcha) y recon del portal autenticado."""
from __future__ import annotations

import json
import re
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
        resp = client.login_programmatic()
        print("LOGIN RESP:", json.dumps(resp, ensure_ascii=False)[:400])
        ok = client.is_logged_in()
        print("is_logged_in:", ok)
        if not ok:
            return
        client.save_state()
        print("estado guardado")

        ctx = client.ctx
        page = ctx.new_page()
        traffic: list[dict] = []
        page.on("response", lambda r: traffic.append(
            {"status": r.status, "method": r.request.method, "url": r.url}))

        page.goto(settings.oss_base + "/index", wait_until="networkidle",
                  timeout=settings.nav_timeout_ms)
        time.sleep(3)
        html = page.content()
        (OUT / "home.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(OUT / "home.png"), full_page=True)

        show_plant = re.findall(r"showPlant\(([^)]*)\)", html)
        summary = {
            "url": page.url,
            "title": page.title(),
            "showPlant_calls": show_plant[:50],
            "frames": [f.url for f in page.frames],
        }
        (OUT / "home_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "traffic_home.json").write_text(
            json.dumps(traffic, ensure_ascii=False, indent=2), encoding="utf-8")
        print("home url:", page.url, "| showPlant matches:", len(show_plant))
        if show_plant:
            print("ejemplo showPlant:", show_plant[0])
    finally:
        client.close()


if __name__ == "__main__":
    main()
