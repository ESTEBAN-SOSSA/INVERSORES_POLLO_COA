"""Recon: capturar el captcha tras pulsar Login para entender su tipo."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import settings

OUT = Path("scripts/_recon")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(settings.oss_base, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
        time.sleep(2)
        page.evaluate("() => { document.querySelectorAll('.markBox,#fenquLayer').forEach(e=>e.style.display='none'); }")
        page.fill("#userName-id", settings.growatt_user)
        page.fill("#passWd-id", settings.growatt_password)
        page.click(".loginInput-btn.btn-yes", force=True)
        time.sleep(4)
        page.screenshot(path=str(OUT / "captcha.png"), full_page=True)
        frames = [f.url for f in page.frames]
        Path(OUT / "captcha_frames.txt").write_text("\n".join(frames), encoding="utf-8")
        print("frames:", len(frames))
        for f in frames:
            print(" -", f[:80])
        browser.close()


if __name__ == "__main__":
    main()
