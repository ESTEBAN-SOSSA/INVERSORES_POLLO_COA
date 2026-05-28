"""Login interactivo a Growatt OSS (resuelve el captcha una sola vez).

Uso:
    .\\.venv\\Scripts\\python.exe -m src.scraper.login

Abre el navegador, prellena las credenciales del .env y espera a que resuelvas
el captcha de deslizamiento. Al entrar, guarda la sesión en .auth/state.json
para que el scraper la reutilice sin volver a loguear.
"""
from __future__ import annotations

import sys

from src.scraper.growatt_client import GrowattClient


def main() -> int:
    # Forzar navegador visible: el captcha exige interacción humana.
    client = GrowattClient(headless=False)
    client.start()
    try:
        client.ensure_login(interactive=True)
        ok = client.is_logged_in()
        print("Login OK" if ok else "Login NO confirmado")
        return 0 if ok else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
