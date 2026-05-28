"""Conecta al Chrome del usuario (CDP :9222), guarda la sesión y recon del portal.

Pre-requisito: el usuario abrió Chrome con launch_chrome_debug.bat e inició
sesión en Growatt OSS (captcha resuelto).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import settings

OUT = Path("scripts/_recon")
OUT.mkdir(parents=True, exist_ok=True)
STATE = Path(".auth/state.json")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        print("contexts:", len(browser.contexts))
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        pages = ctx.pages
        print("pages:", [pg.url for pg in pages])

        # Buscar una página de growatt
        page = None
        for pg in pages:
            if "growatt.com" in pg.url:
                page = pg
                break
        if page is None:
            page = ctx.new_page()
            page.goto(settings.oss_base + "/index", wait_until="domcontentloaded")
            time.sleep(2)

        # ¿logueado?
        if "/login" in page.url:
            print("ERROR: la página sigue en /login. Inicia sesión primero.")
            return

        # Guardar sesión para reusar luego en modo headless.
        STATE.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(STATE))
        print("Sesión guardada en", STATE)

        # Recon del portal autenticado.
        page.goto(settings.oss_base + "/index", wait_until="domcontentloaded")
        time.sleep(2)
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
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("url:", page.url, "| showPlant matches:", len(show_plant))
        if show_plant:
            print("ejemplo showPlant:", show_plant[0])


if __name__ == "__main__":
    main()
