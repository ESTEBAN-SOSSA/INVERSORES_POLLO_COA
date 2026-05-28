"""Reconocimiento del portal Growatt OSS (temporal, para construir el cliente real).

Navega al login, vuelca los inputs/forms, captura tráfico de red y guarda
HTML + screenshot para inspección.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import settings

OUT = Path("scripts/_recon")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    traffic: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        def on_response(resp):
            try:
                traffic.append({"status": resp.status, "url": resp.url, "method": resp.request.method})
            except Exception:
                pass

        page.on("response", on_response)

        print(f">> goto {settings.oss_base}")
        page.goto(settings.oss_base, timeout=settings.nav_timeout_ms, wait_until="networkidle")
        print(">> landed url:", page.url)
        print(">> title:", page.title())

        # Volcar inputs
        inputs = page.eval_on_selector_all(
            "input",
            "els => els.map(e => ({name:e.name, id:e.id, type:e.type, placeholder:e.placeholder, cls:e.className}))",
        )
        buttons = page.eval_on_selector_all(
            "button, .loginB, a.login, [type=submit]",
            "els => els.map(e => ({tag:e.tagName, id:e.id, cls:e.className, text:(e.innerText||'').trim().slice(0,40)}))",
        )
        forms = page.eval_on_selector_all(
            "form",
            "els => els.map(e => ({id:e.id, action:e.action, method:e.method}))",
        )

        summary = {"url": page.url, "title": page.title(),
                   "inputs": inputs, "buttons": buttons, "forms": forms}
        (OUT / "login_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / "login.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(OUT / "login.png"), full_page=True)
        (OUT / "traffic_login.json").write_text(
            json.dumps(traffic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("DONE - wrote summary/html/png/traffic to", OUT)
        browser.close()


if __name__ == "__main__":
    main()
