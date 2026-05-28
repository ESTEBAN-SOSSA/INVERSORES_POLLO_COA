"""Extrae la lista de plantas del DOM del home (nombre + showPlant args)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.config import settings
from src.scraper.growatt_client import GrowattClient

OUT = Path("scripts/_recon")


def main() -> None:
    client = GrowattClient(headless=True)
    client.start()
    try:
        client.ensure_login(interactive=False)
        page = client.ctx.new_page()
        page.goto(settings.oss_base + "/index", wait_until="networkidle",
                  timeout=settings.nav_timeout_ms)
        time.sleep(3)

        rows = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('[onclick*="showPlant"]').forEach(el => {
                    const oc = el.getAttribute('onclick') || '';
                    const m = oc.match(/showPlant\\(([^)]*)\\)/);
                    const tr = el.closest('tr');
                    out.push({
                        args: m ? m[1] : null,
                        el_text: (el.innerText||'').trim().slice(0,80),
                        row_text: tr ? (tr.innerText||'').replace(/\\s+/g,' ').trim().slice(0,160) : '',
                    });
                });
                return out;
            }"""
        )
        # showObjSave (estructura JS con las plantas), si existe.
        try:
            show_obj = page.evaluate("() => (typeof showObjSave !== 'undefined') ? showObjSave : null")
        except Exception:
            show_obj = None

        (OUT / "plants_dom.json").write_text(
            json.dumps({"rows": rows, "showObjSave": show_obj}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print("filas showPlant:", len(rows))
        for r in rows:
            print(" -", r["args"], "|", r["row_text"][:90])
    finally:
        client.close()


if __name__ == "__main__":
    main()
