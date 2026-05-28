# Construcción de la solución — paso a paso

> Bitácora de **cómo se construyó** este scraper (no cómo se opera — eso está en
> [`EXTRACCION_INVERSORES.md`](EXTRACCION_INVERSORES.md)). Documenta las
> decisiones, el reconocimiento y los descubrimientos que permiten **seguir
> escalando** la solución a más plantas, más métricas, otras cuentas o un
> portal con cambios.

---

## 0. Punto de partida

Lo que había:

* Una cuenta operadora en `oss.growatt.com` (`AZPA4001`, Tronex_edemco) con N
  plantas, una de ellas POLLO COA (`plant_id=1878757`, 9 inversores `max`).
* Una UI web con dashboards por inversor que mostraban Hour / Day / Month /
  Year — pero **sin API pública documentada**.

Lo que se necesitaba:

* Extraer la serie de generación **por inversor** (no agregada a planta) en las
  4 granularidades, persistirla y exponerla por API.
* Que la extracción funcionara **headless**, sin intervención humana cada vez,
  para poder programarla a diario.

Decisión raíz: **scraping con Playwright** que reproduce los mismos POST que
hace el navegador, no parsing de HTML. Las series ya vienen como JSON desde
los endpoints `getDevices*Chart`.

---

## 1. Fase de reconocimiento (la que más enseñó)

Toda decisión posterior salió de capturar el tráfico real del navegador. Está
todo bajo `scripts/recon_*.py` + carpeta `scripts/_recon/` con los volcados
HTML/JSON/PNG. **Si el portal cambia, esta fase se repite.**

| Script | Qué captura | Salida en `scripts/_recon/` |
|---|---|---|
| `recon_login.py` | HTML de la página de login, JS de `fn_login`, captcha frames | `login.html`, `login.png`, `captcha_frames.txt` |
| `recon_after_login.py` | DOM y tráfico tras login exitoso | `after_login.html`, `traffic_after_login.json` |
| `recon_plants_dom.py` | Filas de la tabla de plantas + `showPlant(args)` | `plants_dom.json` |
| `recon_showplant.py` | Tráfico del popup `server.growatt.com` al pulsar una planta | `traffic_showplant.json`, `showplant_devices.json` |
| `recon_plantlist.py` | Request/response de `/panel/getDevicesByPlantList` | `plantlist_request.json`, `plantlist_response.json` |
| `recon_charts.py` | Prueba los 4 endpoints `getDevices*Chart` con un SN real | `charts_probe.json` |

**Cómo correrlos sin captcha bloqueando:**

```powershell
# 1. abrir Chrome en modo debug y loguear UNA vez a mano (resuelve el slider)
.\launch_chrome_debug.bat                       # arranca Chrome con --remote-debugging-port=9222
# (loguear en oss.growatt.com en esa ventana)

# 2. correr el recon conectándose por CDP a esa sesión
.\.venv\Scripts\python.exe scripts\recon_charts.py
```

Los scripts admiten `GrowattClient(cdp_url="http://127.0.0.1:9222")` para
reusar esa sesión humana ya autenticada.

---

## 2. Cómo se resolvió el login (sin tocar el captcha)

**Problema:** el portal monta un slider Tencent TCaptcha al pulsar el botón
Login en la UI. Resolverlo programáticamente es frágil y se rompe seguido.

**Descubrimiento:** mirando `scripts/_recon/login.html` (línea ~2227, función
`fn_login`) se ve que el botón **no envía ningún ticket de captcha** al server.
El `POST /login` acepta solamente:

```
userName=AZPA4001              ← en mayúsculas (lo hace .toUpperCase() la propia página)
passwordCrc=<MD5(password)>    ← MD5 hex, calculado client-side
password=                      ← vacío
loginTime=...
isReadPact=1
lang=en
type=1
```

El captcha es **solo UI**, no se valida en el backend. Mismo comportamiento
que las librerías oficiales de Growatt (PyPI `growatt_api`, etc.).

**Implementación:** `src/scraper/growatt_client.py::login_programmatic` hace
`fetch('/login', ...)` desde dentro de la página, usando la función `MD5` que
el propio portal ya cargó. Eso:

* Reusa cookies y `origin` exactamente como el navegador real.
* No reimplementa MD5 en Python (si el portal cambia el algoritmo, lo usamos
  automáticamente).
* Vuela el captcha por completo, sin evasión de seguridad — es el mismo POST
  que haría el botón si no hubiera UI.

Códigos de `result` que devuelve `/login` están mapeados en
`growatt_client._LOGIN_MSG` (0 = credenciales malas, 6 = cuenta en otro
servidor, 7 = bloqueada, 8 = MD5 no aceptado).

La sesión queda guardada en `.auth/state.json` (storage_state de Playwright)
y se reusa por horas/días. Cuando expira, `ensure_login` la rehace sola.

---

## 3. Cómo se descubrió la lista de plantas

`oss.growatt.com/index` renderiza la tabla de plantas con un `onclick` por
fila:

```html
<a onclick="showPlant('1','2fe88bc7aebf5bbf4d4d0f8a85a0c97f','1878757')">…</a>
```

Esos tres argumentos son `(server, account, plant_id)` — el **trío necesario
para abrir el popup autenticado de server.growatt.com**.

`src/scraper/oss_portal.py::list_plants` extrae todas las filas vía
`page.evaluate(...)` (índices de columna en las constantes `_COL_*`) y arma
el mapeo `plant_id → (server, account, name, city, capacity, …)`.

**Para escalar a otra cuenta operadora:** solo cambia el `GROWATT_USER` /
`GROWATT_PASSWORD` del `.env`. La tabla y los onclick son los mismos.

---

## 4. Una sesión `server.growatt.com` por ACCOUNT (no por planta)

`showPlant` abre una pestaña a `server.growatt.com` con auto-login firmado por
el `account` hash. Esa pestaña queda autenticada para **cualquier planta del
mismo operador colombiano** (`account=2fe88bc7…` en POLLO COA).

`GrowattClient` cachea esos popups:

```python
self._server_pages: dict[str, Page] = {}   # key = account hash
```

Por eso `open_server_session(server, account, plant_id)` solo abre el popup la
primera vez por account. Las 9 plantas de POLLO COA reusan la misma sesión.

**Implicación para escalar:** procesar varias cuentas operadoras requiere
N popups (uno por hash), pero N plantas de la misma cuenta = 1 popup.

---

## 5. Inversores de una planta

```
POST server.growatt.com/panel/getDevicesByPlantList
body: plantId=<ID>&currPage=<N>
```

Respuesta: `obj.pages` (total), `obj.datas[]` (filas). Cada fila trae:

```
sn, deviceTypeName, deviceModel, alias, status, nominalPower,
datalogSn, eToday, eMonth, eTotal, pac, …
```

**Footgun ya pisado:** el campo crítico para los charts NO es `"inverter"` ni
`deviceModel`, es `deviceTypeName` (`max`, `mix`, `storage`, `inv`, `noah`,
…). Si mandás `type:"inverter"` al chart, el server responde `result:1` pero
con `datas` vacío (silencioso). Ver `inverter_scraper.list_inverters_for_plant`:
guarda `deviceTypeName` y usa `"max"` como fallback.

Paginación: respetar `obj.pages`, **no** usar `len(datas) < 10`.

---

## 6. Los 4 charts — el descubrimiento central

Endpoints simétricos en `server.growatt.com/energy/compare/`:

| Chart | Param extra | `params` body | Devuelve |
|---|---|---|---|
| `getDevicesDayChart`   | `date=YYYY-MM-DD` | `pac`              | 288 muestras PAC (W) cada 5 min |
| `getDevicesMonthChart` | `date=YYYY-MM`    | `energy,autoEnergy` | kWh por día del mes |
| `getDevicesYearChart`  | `year=YYYY`       | `energy,autoEnergy` | 12 totales mensuales |
| `getDevicesTotalChart` | `year=YYYY`       | `energy,autoEnergy` | N totales anuales (toda la historia) |

Body común:

```
plantId=<ID>
jsonData=[{"type":"<deviceTypeName>","sn":"<SN>","params":"<pac|energy,…>"}]
```

**Estructura real de la respuesta** (descubierta por reconocimiento — no es la
del runbook viejo):

```jsonc
{
  "result": 1,
  "obj": [                           // ← obj es LISTA, no dict
    {
      "sn": "ZFEDCA6003",
      "type": "max",
      "params": "pac",
      "datas": {                     // ← y dentro hay un dict
        "pac": [0, 0, 12, 45, ...]   // ← clave varía: 'pac' para Day, 'energy' para los otros
      }
    }
  ]
}
```

El parser `inverter_scraper._series(resp, *keys)` busca `obj[0].datas[key]`
probando varias claves en orden (`energy` → `pac` → `autoEnergy`) y devuelve
la primera no vacía. Eso lo hace robusto a que Growatt mueva el nombre.

**Verificación:** `scripts/recon_charts.py` prueba los 4 y vuelca
`_recon/charts_probe.json`. Útil para validar después de cualquier sospecha de
cambio en el portal.

---

## 7. Transformación a la BD

Una sola tabla `energy_readings` con discriminador `granularity`:

```
(plant_id, device_sn, reading_date, granularity, reading_hour)   ← índice único
```

| Granularidad | `reading_date` | `reading_hour` | `energy_kwh` | `raw` |
|---|---|---|---|---|
| `hour` | día | 0..23 (24 filas/día) | kWh de esa hora | `samples_5min_w: [12 valores]` |
| `day` | día | `null` | kWh del día | — |
| `month` | YYYY-MM-01 | `null` | kWh del mes | — |

Year **no se persiste**: lo agrega la API sumando los `month` de cada año
(`func.strftime("%Y", reading_date)`). Razón: la suma de meses ya es exacta y
evita un row más por inversor por año.

El cálculo `hour` (de 288 muestras 5-min a 24 filas) está en
`fetch_inverter_hourly_for_date`:

```python
for h in range(24):
    chunk = pac[h*12 : (h+1)*12]                      # 12 muestras
    kwh   = sum(chunk) * 5 / 60 / 1000                # W·min → kWh
    peak  = max(chunk)
    avg   = sum(chunk) / 12
    raw   = {"samples_5min_w": chunk}                 # se guarda crudo para el chart
```

Las 12 muestras crudas quedan en `raw.samples_5min_w` → permite reconstruir
los 288 puntos por día en la API sin volver a scrapear.

---

## 8. Persistencia idempotente

`src/scraper/persist.py` hace **DELETE acotado por rango + INSERT** en una
transacción. Crítico:

* `persist_inverter_history` borra `day`+`month` **del rango de años que va a
  insertar**, no todo (footgun original: borraba todo → con `--no_history`
  perdíamos años previos).
* `persist_inverter_hour` borra las `hour` del día y reinserta las 24.

Resultado: corridas incrementales seguras. `--no_history --hourly_days 1` se
puede correr cada N minutos sin pérdida.

---

## 9. La API REST

`src/api/main.py` (FastAPI):

| Endpoint | Notas |
|---|---|
| `GET /api/v1/plants` | Listado plano de la tabla `plants` |
| `GET /api/v1/plants/{id}/inverters` | Filas de `devices` con `plant_id=<id>` |
| `GET /api/v1/inverters/{sn}/energy?granularity=…` | Series; ver formato abajo |

Formato de respuesta de `energy` según `granularity`:

```
day / month        → [{reading_date, energy_kwh}, …]
year               → [{reading_date: YYYY-01-01, energy_kwh}, …]   (agregado on-the-fly)
hour               → [{reading_date, sample_time:"HH:MM", power_w}, …]   288/día (lista plana)
hour&aggregate=1   → [{reading_date, reading_hour, energy_kwh, peak_power_w, avg_power_w}, …]
```

Auth: header `X-API-Key` (valor en `.env`, hoy `PRUEBAS_GROWATT_INVERSORES`).

---

## 10. Cómo extender (cheatsheet de escalado)

| Quiero… | Qué tocar |
|---|---|
| **Nueva planta del mismo operador** | Nada de código. `python -m src.scraper.inverter_main --plant_id <NUEVO_ID>`. Si no aparece, corre el sync sin `--plant_id` para refrescar la tabla `plants`. |
| **Otra cuenta operadora** (otro `GROWATT_USER`) | Cambiar `.env` y correr. Si querés múltiples cuentas a la vez, refactor: pasar credenciales por parámetro y no por settings global. |
| **Nuevo tipo de dispositivo** (`mix`, `storage`, etc.) | Verificar que `deviceTypeName` del panel coincida con lo que aceptan los charts. Probar con `scripts/recon_charts.py` cambiando `DEVTYPE`. El código ya lee `deviceTypeName` dinámico (no está hardcoded a `max`). |
| **Nueva métrica del mismo chart** (ej. voltaje, temperatura) | Crear params nuevo (`vac`, `temperature`, …), probarlo con `recon_charts.py`, agregar columna en `energy_readings` o nueva tabla, extender `fetch_inverter_*` y `persist_*`. |
| **Otro chart distinto** (ej. eventos, alarmas) | Hay endpoints como `/device/inverter/getInverterControlData`, `/device/getDeviceAllAlarm`. Capturarlos con un nuevo `recon_*.py`, replicar el patrón de `inverter_scraper.fetch_*`. |
| **Refrescos cada N minutos** | Cron de Windows / `schtasks` corriendo `inverter_main --no_history --hourly_days 1`. El DELETE acotado lo hace seguro. |
| **Postgres / TimescaleDB** | Solo `DATABASE_URL`. Alembic genera el schema. Para retención automática del `hour` 5-min, crear *hypertable* sobre `energy_readings` particionada por `reading_date` y agregar *retention policy* (ver §7 del runbook). |
| **Más concurrencia** | Hoy es secuencial (1 inversor a la vez). El cuello no es CPU sino el portal — paralelizar más de 2-3 requests puede ratearte. Si hace falta, abrir N popups por account y un pool. |
| **Migrar a `requests` puro** (sin browser) | Posible: el login MD5 ya está descripto, las cookies se pueden mantener con `requests.Session`. Lo abandonamos porque el popup de `server.growatt.com` hace auto-login con un token efímero firmado client-side; replicarlo es más trabajo que mantener Playwright. Solo conviene si headless + Chromium es un problema operativo. |

---

## 11. Cuando el portal cambia (procedimiento de re-recon)

Síntomas: `result != 1`, `obj` vacío, redirects raros, parseo del DOM roto.

1. **Reproducir manualmente** en `launch_chrome_debug.bat` y mirar DevTools →
   Network. Ver qué endpoint cambió o qué campo nuevo aparece.
2. **Re-correr el `recon_*.py` afectado** conectado por CDP a esa sesión:
   `GrowattClient(cdp_url="http://127.0.0.1:9222")`. El volcado nuevo en
   `scripts/_recon/` muestra el delta.
3. **Comparar** con el JSON previo (git diff sobre `scripts/_recon/`).
4. **Ajustar el parser** (`_series` y similares). Tip: agregar la clave nueva
   a `_series(resp, "nueva_key", "energy", "pac")` en lugar de reemplazar —
   así si el portal vuelve atrás, sigue funcionando.
5. **Actualizar** este documento + `EXTRACCION_INVERSORES.md`.

> Memoria útil: el proceso de Claude en esta máquina NO puede mostrar ventanas
> en el desktop del usuario. Si hace falta un Chrome con UI (para resolver
> captcha o re-recon manual), el usuario tiene que ejecutar
> `launch_chrome_debug.bat` con doble-click y luego Claude se conecta vía
> `cdp_url=http://127.0.0.1:9222`.

---

## 12. Mapa de archivos para futuros mantenedores

```
src/scraper/
  growatt_client.py   ← login MD5 + popup server.growatt.com + POST in-page (núcleo)
  oss_portal.py       ← lista de plantas desde el DOM del home
  inverter_scraper.py ← list_inverters + 4 charts + parseo a (day/month/hour)
  persist.py          ← DELETE acotado + INSERT idempotente
  inverter_main.py    ← CLI orquestador (--plant_id, --no_history, --hourly_days)

src/api/
  main.py             ← 3 endpoints FastAPI
  schemas.py          ← Pydantic models
  deps.py             ← X-API-Key

src/db/
  models.py           ← plants, devices, energy_readings
  base.py             ← engine + Session

scripts/
  recon_*.py          ← reconocimiento por etapa (login, plantlist, charts, …)
  _recon/             ← volcados HTML/JSON/PNG capturados (commiteable, son docs)

alembic/              ← migraciones (sqlite y postgres)
.auth/state.json      ← sesión Playwright (gitignored)
launch_chrome_debug.bat ← Chrome con --remote-debugging-port=9222 para CDP
```

Los archivos en `scripts/_recon/` son **documentación viva** — no los borres
aunque parezcan basura. Son la verdad sobre cómo se comportaba el portal en
el momento en que el scraper se hizo.
