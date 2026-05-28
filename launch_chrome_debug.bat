@echo off
REM ============================================================
REM  Abre Chrome con depuracion remota (puerto 9222) para que
REM  el scraper se conecte. Inicia sesion en Growatt OSS aqui
REM  (resuelve el captcha) y deja esta ventana de Chrome abierta.
REM ============================================================
echo Abriendo Chrome con depuracion remota en el puerto 9222...
echo Inicia sesion en Growatt OSS (resuelve el captcha) y NO cierres esta ventana.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%~dp0.chrome-debug" "https://oss.growatt.com"
