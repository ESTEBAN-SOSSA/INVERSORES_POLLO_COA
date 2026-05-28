from __future__ import annotations
import json, time
from src.config import settings
from src.scraper.growatt_client import GrowattClient

client = GrowattClient(headless=True)
client.start()
try:
    client.ensure_login(interactive=False)
    page = client.ctx.new_page()
    page.goto(settings.oss_base + "/index", wait_until="networkidle", timeout=settings.nav_timeout_ms)
    time.sleep(3)
    rows = page.evaluate(
        """() => {
            const out=[];
            document.querySelectorAll('[onclick*="showPlant"]').forEach(el=>{
                const tr=el.closest('tr'); if(!tr) return;
                const cells=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').trim());
                const oc=el.getAttribute('onclick')||'';
                const m=oc.match(/showPlant\\(([^)]*)\\)/);
                out.push({args:m?m[1]:null, cells});
            });
            return out;
        }"""
    )
    print(json.dumps(rows[0], ensure_ascii=False, indent=2))
    print("---POLLO COA row---")
    for r in rows:
        if r['args'] and '1878757' in r['args']:
            print(json.dumps(r, ensure_ascii=False, indent=2))
finally:
    client.close()
