"""Cliente Growatt OSS basado en Playwright.

Maneja:
  * Login al portal oss.growatt.com con **persistencia de sesión** (storage_state).
    El portal exige un captcha de deslizamiento (Tencent TCaptcha) al loguear,
    por lo que el primer login es *interactivo*: el humano resuelve el captcha una
    vez y la sesión queda guardada en `.auth/state.json` para reusarse luego.
  * Apertura del popup autenticado de server.growatt.com (mecanismo `showPlant`),
    reutilizado **por account** (no por planta).
  * POSTs autenticados a los endpoints de server.growatt.com vía fetch in-page,
    de modo que se respetan cookies/origin igual que el navegador real.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from src.config import settings

STATE_PATH = Path(".auth/state.json")


class NotLoggedInError(RuntimeError):
    """La sesión guardada no existe o expiró y no se pidió login interactivo."""


class GrowattClient:
    def __init__(self, headless: bool | None = None, cdp_url: str | None = None) -> None:
        self.headless = settings.headless if headless is None else headless
        # Si se da cdp_url, se conecta a un Chrome ya abierto por el usuario
        # (donde resolvió el captcha) en vez de lanzar su propio navegador.
        self.cdp_url = cdp_url
        self._pw = None
        self.browser: Browser | None = None
        self.ctx: BrowserContext | None = None
        # popup server.growatt.com cacheado por account
        self._server_pages: dict[str, Page] = {}

    # ---------- ciclo de vida ----------
    def __enter__(self) -> "GrowattClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        self._pw = sync_playwright().start()
        if self.cdp_url:
            # Reusar el Chrome del usuario (sesión ya autenticada, captcha resuelto).
            self.browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
            self.ctx = (
                self.browser.contexts[0]
                if self.browser.contexts
                else self.browser.new_context()
            )
            self.ctx.set_default_timeout(settings.nav_timeout_ms)
            return

        self.browser = self._pw.chromium.launch(headless=self.headless)
        kwargs: dict[str, Any] = {
            "locale": "en-US",
            "viewport": {"width": 1440, "height": 900},
        }
        if STATE_PATH.exists():
            kwargs["storage_state"] = str(STATE_PATH)
        self.ctx = self.browser.new_context(**kwargs)
        self.ctx.set_default_timeout(settings.nav_timeout_ms)

    def close(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
            if self.browser:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        assert self.ctx is not None
        self.ctx.storage_state(path=str(STATE_PATH))

    # ---------- login ----------
    @staticmethod
    def _dismiss_modals(page: Page) -> None:
        for sel in ["#agree", "#yc_notice_cancel", "#yc_notice_cancel2"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    time.sleep(0.3)
            except Exception:
                pass
        try:
            page.evaluate(
                "() => document.querySelectorAll('.markBox,#fenquLayer')"
                ".forEach(e => e.style.display='none')"
            )
        except Exception:
            pass

    def is_logged_in(self, page: Page | None = None) -> bool:
        """True si una navegación al portal NO termina en /login."""
        own = page is None
        page = page or self.ctx.new_page()  # type: ignore[union-attr]
        try:
            page.goto(settings.oss_base + "/index",
                      wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
            time.sleep(1.5)
            return "/login" not in page.url
        except Exception:
            return False
        finally:
            if own:
                page.close()

    # Códigos de result del endpoint /login (ver fn_login en login.jsp).
    _LOGIN_MSG = {
        "0": "Usuario o contraseña incorrectos.",
        "3": "La cuenta existe en varios servidores; elegir región.",
        "4": "Falta aceptar acuerdo de protección de datos.",
        "5": "Notificación de cambio pendiente.",
        "6": "La cuenta no existe en este servidor (probar otra región).",
        "7": "Cuenta bloqueada temporalmente (demasiados intentos).",
        "8": "MD5 no coincide; reintentar con contraseña en claro.",
    }

    def login_programmatic(self) -> dict:
        """Login por POST directo a /login (sin UI, sin captcha).

        Reproduce el `fn_login` del portal: userName en mayúsculas +
        passwordCrc = MD5(password), usando la función MD5 de la propia página.
        Devuelve el JSON de respuesta del portal.
        """
        assert self.ctx is not None
        page = self.ctx.new_page()
        try:
            page.goto(settings.oss_base, wait_until="domcontentloaded",
                      timeout=settings.nav_timeout_ms)
            time.sleep(1.5)
            self._dismiss_modals(page)

            script = """
            async ([user, pwd]) => {
                const md5 = (typeof MD5 === 'function') ? MD5(pwd)
                          : (typeof hex_md5 === 'function') ? hex_md5(pwd) : null;
                let loginTime = '';
                try { loginTime = (typeof getDateText === 'function') ? getDateText(null, 4) : ''; } catch(e) {}
                const data = {
                    userName: user.toUpperCase(),
                    password: '',
                    passwordCrc: md5,
                    loginTime: loginTime,
                    isReadPact: 1,
                    changeNotice: '',
                    lang: 'en',
                    type: (localStorage.getItem('login_type') || 1),
                };
                const r = await fetch('/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                              'X-Requested-With': 'XMLHttpRequest'},
                    body: new URLSearchParams(data).toString(),
                    credentials: 'include',
                });
                const text = await r.text();
                try { return JSON.parse(text); } catch(e) { return {_raw: text.slice(0,300)}; }
            }
            """
            resp = page.evaluate(script, [settings.growatt_user, settings.growatt_password])
            return resp if isinstance(resp, dict) else {"_resp": resp}
        finally:
            page.close()

    def ensure_login(self, interactive: bool = False, wait_seconds: int = 240) -> None:
        """Garantiza una sesión válida.

        1. Si hay sesión guardada y sigue viva → no hace nada.
        2. Intenta login programático (POST /login con MD5). Sin captcha.
        3. Si falla y interactive=True → cae al login manual con captcha.
        """
        assert self.ctx is not None
        if STATE_PATH.exists() and self.is_logged_in():
            return

        resp = self.login_programmatic()
        result = str(resp.get("result", ""))
        if result == "1":
            time.sleep(1)
            self.save_state()
            return

        detail = self._LOGIN_MSG.get(result, resp.get("msg") or str(resp))
        if not interactive:
            raise NotLoggedInError(
                f"Login programático falló (result={result or '?'}): {detail}"
            )
        self.ensure_login_interactive(wait_seconds=wait_seconds)

    def ensure_login_interactive(self, wait_seconds: int = 240) -> None:
        """Fallback: login manual resolviendo el captcha en navegador visible."""
        assert self.ctx is not None
        page = self.ctx.new_page()
        page.goto(settings.oss_base, wait_until="domcontentloaded",
                  timeout=settings.nav_timeout_ms)
        time.sleep(2)
        self._dismiss_modals(page)
        try:
            page.fill("#userName-id", settings.growatt_user)
            page.fill("#passWd-id", settings.growatt_password)
            time.sleep(0.3)
            page.click(".loginInput-btn.btn-yes", force=True)
        except Exception:
            pass

        print("\n" + "=" * 64)
        print(" >>> Resuelve el CAPTCHA en la ventana del navegador y entra <<<")
        print(f"     Esperando hasta {wait_seconds}s a que el login se complete...")
        print("=" * 64 + "\n", flush=True)

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if "/login" not in page.url:
                break
            time.sleep(2)
        else:
            raise NotLoggedInError("Tiempo agotado esperando el login (captcha).")

        time.sleep(2)
        self.save_state()
        print(f"Sesión guardada en {STATE_PATH}. URL actual: {page.url}")
        page.close()

    # ---------- sesión server.growatt.com (popup showPlant) ----------
    def open_server_session(self, server: str, account: str, plant_id: str) -> Page:
        """Abre (o reutiliza) el popup autenticado de server.growatt.com.

        Una sesión por `account`; se reutiliza para cualquier planta del account.
        """
        assert self.ctx is not None
        if account in self._server_pages and not self._server_pages[account].is_closed():
            return self._server_pages[account]

        page = self.ctx.new_page()
        page.goto(settings.oss_base + "/index", wait_until="domcontentloaded",
                  timeout=settings.nav_timeout_ms)
        time.sleep(1)
        # Disparar showPlant(server, account, plantId) → abre popup auto-logueado.
        try:
            with self.ctx.expect_page(timeout=settings.nav_timeout_ms) as popup_info:
                page.evaluate(
                    "([s,a,p]) => showPlant(s,a,p)",
                    [server, account, plant_id],
                )
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded", timeout=settings.nav_timeout_ms)
            time.sleep(2)
        except Exception:
            # Fallback: navegar directo al server si showPlant no abre popup.
            popup = self.ctx.new_page()
            popup.goto(settings.server_base, wait_until="domcontentloaded",
                       timeout=settings.nav_timeout_ms)
            time.sleep(1)

        self._server_pages[account] = popup
        return popup

    # ---------- POST autenticado a server.growatt.com ----------
    def server_post_json(self, page: Page, path: str, data: dict[str, Any]) -> Any:
        """POST x-www-form-urlencoded a server.growatt.com vía fetch in-page.

        Devuelve el JSON parseado (o {} si la respuesta no es JSON).
        """
        url = settings.server_base + path
        body = urlencode(data)
        script = """
        async ([url, body]) => {
            const r = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                          'X-Requested-With': 'XMLHttpRequest'},
                body: body,
                credentials: 'include',
            });
            const text = await r.text();
            return {status: r.status, text: text};
        }
        """
        res = page.evaluate(script, [url, body])
        text = res.get("text", "") if isinstance(res, dict) else ""
        try:
            return json.loads(text)
        except Exception:
            return {"_status": res.get("status"), "_raw": text[:500]}
