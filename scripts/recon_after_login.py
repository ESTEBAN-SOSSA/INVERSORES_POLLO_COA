"""Recon paso 2: login real + volcado de la Plant List y tráfico de red."""
from __future__ import annotations

import json
import re
import time
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
        page.on("response", lambda r: traffic.append(
            {"status": r.status, "method": r.request.method, "url": r.url}
        ))

        page.goto(settings.oss_base, timeout=settings.nav_timeout_ms, wait_until="domcontentloaded")
        time.sleep(2)

        # Cerrar/aceptar modales de privacidad si aparecen.
        for sel in ["#agree", "#yc_notice_cancel", "#yc_notice_cancel2"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    time.sleep(0.5)
            except Exception:
                pass

        # Ocultar capas que interceptan clicks (selección de región / máscaras).
        page.evaluate(
            """() => {
                ['#fenquLayer'].forEach(id => {
                    const el = document.querySelector(id);
                    if (el) el.style.display = 'none';
                });
                document.querySelectorAll('.markBox').forEach(e => e.style.display='none');
            }"""
        )
        time.sleep(0.3)

        # Login
        page.fill("#userName-id", settings.growatt_user)
        page.fill("#passWd-id", settings.growatt_password)
        time.sleep(0.3)
        page.click(".loginInput-btn.btn-yes", force=True)

        # Esperar a que cambie de /login
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=settings.nav_timeout_ms)
        except Exception:
            pass
        time.sleep(3)

        result = {"after_login_url": page.url, "title": page.title()}

        # Intentar navegar a la lista de plantas conocida del OSS.
        for path in ["/distributorAccount/getPlantList", "/plant", "/index"]:
            pass  # (sólo doc; dejamos que la home cargue)

        # Buscar onclick showPlant(...) en el HTML
        html = page.content()
        (OUT / "after_login.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(OUT / "after_login.png"), full_page=True)

        show_plant = re.findall(r"showPlant\(([^)]*)\)", html)
        result["showPlant_calls"] = show_plant[:20]

        # Links del menú / iframes
        result["frames"] = [f.url for f in page.frames]

        (OUT / "after_login_summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / "traffic_after_login.json").write_text(
            json.dumps(traffic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("DONE login. url=", page.url, "showPlant matches=", len(show_plant))
        browser.close()


if __name__ == "__main__":
    main()
