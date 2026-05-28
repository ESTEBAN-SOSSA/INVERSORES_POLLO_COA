# Extracción de datos por INVERSOR — Runbook

> Documento operativo (paso a paso) para extraer la generación **por inversor**
> de una planta específica de Growatt OSS, mapeada en **Hour / Day / Month** (+ Year).
>
> Pensado para usarse a demanda: *"extrae los inversores de la planta X"* → seguir
> este runbook. Toda la información está verificada contra el código real del
> proyecto (`src/scraper/*`).

---

## 0. TL;DR — el comando que casi siempre vas a usar

```powershell
# Extraer TODOS los inversores de UNA planta, con histórico completo + hourly de hoy
.\.venv\Scripts\python.exe -m src.scraper.inverter_main --plant_id <PLANT_ID> --hourly_days 1
```

Luego leer los datos:

```powershell
# Inversores de esa planta
curl http://127.0.0.1:8001/api/v1/plants/<PLANT_ID>/inverters -H "X-API-Key: PRUEBAS_GROWATT_INVERSORES"

# Energía de un inversor (Hour/Day/Month/Year)
curl "http://127.0.0.1:8001/api/v1/inverters/<SN>/energy?granularity=day&date_from=2026-01-01" -H "X-API-Key: PRUEBAS_GROWATT_INVERSORES"
```

> El API corre en **:8001** en este entorno (el :8000 está ocupado). Ajusta el puerto si cambia.

---

## 1. Cómo funciona la extracción (modelo mental)

El portal Growatt OSS **no tiene API pública**: se hace *reverse engineering* del
flujo del navegador con Playwright. La cadena real es:

```
oss.growatt.com  ──login──►  Plant List
        │  (showPlant abre popup con auto-login por ACCOUNT)
        ▼
server.growatt.com (popup autenticado)
        │  POST /panel/getDevicesByPlantList   → lista de inversores (SN, deviceTypeName…)
        │  POST /energy/compare/getDevices*Chart → series de generación por inversor
        ▼
   energy_readings (BD)  ──►  API REST  ──►  cliente
```

Puntos clave aprendidos en este proyecto:

1. **Una sesión `server.growatt.com` por ACCOUNT**, no por planta. El orquestador
   agrupa las plantas por `account` y reusa el popup (`open_server_session`).
2. **`/panel/getDevicesByPlantList` acepta `plantId` directo** — no hace falta
   navegar a cada planta; con el popup abierto, se piden los inversores de
   cualquier planta del mismo account.
3. **El campo `type` de los charts es el `deviceTypeName` REAL** del inversor
   (`max`, `mix`, `storage`, `inv`, `noah`…), **NO la string `"inverter"`**.
   Si mandas `type:"inverter"` el servidor responde `result:1` pero con `datas`
   vacío (silencioso). El código toma `deviceTypeName` del panel y, si falta,
   usa `"max"` como fallback (el más común).
4. **Idempotente por inversor**: antes de insertar hace `DELETE` de las lecturas
   previas del inversor (`day`+`month`, o las `hour` del día) y luego `INSERT`.
   ⚠️ Implicación importante → ver §6 (no mezclar `--no_history` con histórico ya cargado).

---

## 2. Pre-requisitos (una sola vez)

```powershell
# Entorno
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

# Credenciales OSS en .env  (GROWATT_USER / GROWATT_PASSWORD)
copy .env.example .env   # y editar

# Base de datos
alembic upgrade head
```

Verificación rápida de que todo está listo:

```powershell
.\.venv\Scripts\python.exe -c "from src.api.main import app; print('OK', len(app.routes))"
```

---

## 3. Paso a paso para extraer una planta específica

### 3.1 Encontrar el `plant_id`

Si ya hiciste al menos un sync, las plantas están en BD:

```powershell
# Listado plant_id + nombre (SQLite)
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('growatt_test.db'); [print(r) for r in c.execute('SELECT plant_id,name FROM plants ORDER BY name').fetchall()]"
```

O vía API: `GET /api/v1/plants`.

Si es una planta nunca sincronizada, corre el sync sin `--plant_id` una vez para
poblar la lista, o míra el `onclick="showPlant(server, account, PLANT_ID)"` en el
HTML de Plant List del portal.

### 3.2 Ejecutar la extracción de esa planta

```powershell
# Histórico COMPLETO (todos los años) + hourly de los últimos 7 días
.\.venv\Scripts\python.exe -m src.scraper.inverter_main --plant_id <PLANT_ID>

# Solo año actual (más rápido) + hourly de hoy
.\.venv\Scripts\python.exe -m src.scraper.inverter_main --plant_id <PLANT_ID> --no_history --hourly_days 1

# Histórico completo + 14 días de hourly
.\.venv\Scripts\python.exe -m src.scraper.inverter_main --plant_id <PLANT_ID> --hourly_days 14
```

Flags (de `inverter_main.py`):

| Flag | Default | Qué hace |
|---|---|---|
| `--plant_id <ID>` | (todas) | Procesa solo esa planta |
| `--no_history` | off | Solo año actual (recorta day+month al `current_year`) |
| `--hourly_days <N>` | `7` | Días recientes con detalle 5-min. `0` desactiva hourly |

### 3.3 Qué hace internamente por cada inversor

1. `list_inverters_for_plant(plant_id)` → SN, `deviceTypeName`, modelo, status…
   (paginado, respeta `obj.pages`; dedup por SN).
2. `upsert_inverter_meta` → fila en `devices` (`type="inverter"`, `raw` con nombre/potencia).
3. `fetch_inverter_history` → Year/Total/Month charts → `day` + `month`.
4. `fetch_inverter_hourly_for_date` (× N días) → Day chart 5-min → `hour`.
5. `persist_*` → `DELETE` previo + `INSERT` (idempotente).

Salida esperada al final (ejemplo de una corrida completa):

```json
{"plants": 1, "inverters": 4, "days": 4200, "months": 150, "hours": 96}
```

---

## 4. Mapeo Hour / Day / Month / Year (lo central)

Todos los charts son `POST` a `server.growatt.com/energy/compare/getDevices{X}Chart`
con cuerpo `application/x-www-form-urlencoded`:

```
plantId=<PLANT_ID>
jsonData=[{"type":"<deviceTypeName>","sn":"<SN_INVERSOR>","params":"<params>"}]
<+ date= o year= según el chart>
```

| Granularidad | Endpoint | Param extra | `params` | Devuelve | Cómo se transforma |
|---|---|---|---|---|---|
| **HOUR** | `getDevicesDayChart` | `date=YYYY-MM-DD` | `pac` | ~288 muestras de **PAC (W)** cada 5 min | Se agrupan en 24 horas (12 slots/hora). Por hora: `kwh = Σpac · 5/60/1000`, `peak_w = max`, `avg_w`, y se guarda la lista de 12 `samples_5min_w` en `raw`. Siempre 24 filas (noche = 0). |
| **DAY** | `getDevicesMonthChart` | `date=YYYY-MM` | `energy,autoEnergy` | kWh por **día** del mes | 1 fila por día con `energy_kwh` (se omiten días ≤ 0). |
| **MONTH** | `getDevicesYearChart` | `year=YYYY` | `energy,autoEnergy` | **12** totales mensuales (kWh) | 1 fila por mes (`reading_date = YYYY-MM-01`), se omiten meses ≤ 0. |
| **YEAR** | `getDevicesTotalChart` | `year=YYYY` | `energy,autoEnergy` | kWh por **año** | Su **longitud** indica cuántos años de histórico hay → arma `years = [current-N+1 … current]`. Si viene vacío → fallback a solo el año actual. |

> El parser de respuesta busca, en orden, `datas.energy` → `datas.pac` →
> `datas.autoEnergy` y devuelve el primero con datos. `result != 1` o `obj` vacío → `[]`.

### Almacenamiento en `energy_readings`

| Columna | hour | day | month |
|---|---|---|---|
| `granularity` | `"hour"` | `"day"` | `"month"` |
| `reading_date` | día | día | primer día del mes |
| `reading_hour` | 0..23 | `null` | `null` |
| `energy_kwh` | kWh de esa hora | kWh del día | kWh del mes |
| `peak_power_w` | pico W de la hora | `null` | `null` |
| `raw.samples_5min_w` | 12 valores W | — | — |
| `device_sn` | **SN del inversor** | SN | SN |

Índice único: `(plant_id, device_sn, reading_date, granularity, reading_hour)`.

---

## 5. Leer los datos extraídos

### Vía API (recomendado)

```powershell
$H = @{ "X-API-Key" = "PRUEBAS_GROWATT_INVERSORES" }

# Inversores de la planta
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/plants/<PLANT_ID>/inverters" -Headers $H

# HOUR → 288 puntos planos (reading_date, sample_time HH:MM, power_w) — igual al chart del portal
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/<SN>/energy?granularity=hour&date_from=2026-05-26" -Headers $H

# HOUR con aggregate=true → resumen por hora (energy_kwh, peak_power_w, avg_power_w)
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/<SN>/energy?granularity=hour&date_from=2026-05-26&aggregate=true" -Headers $H

# DAY / MONTH / YEAR → energy_kwh por período
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/<SN>/energy?granularity=day&date_from=2026-01-01" -Headers $H
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/<SN>/energy?granularity=month&date_from=2026-01-01" -Headers $H
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/<SN>/energy?granularity=year" -Headers $H
```

Parámetros del endpoint `/inverters/{sn}/energy`: `granularity` (`hour|day|month|year`),
`date_from`, `date_to`, `limit` (≤ 10000), `aggregate` (solo `hour`: `true` devuelve
resumen horario en vez de las 288 muestras 5-min).

### Vía SQL directo

```sql
-- kWh por día de un inversor en 2026
SELECT reading_date, energy_kwh
FROM energy_readings
WHERE device_sn = '<SN>' AND granularity = 'day'
  AND reading_date >= '2026-01-01'
ORDER BY reading_date;
```

---

## 6. ⚠️ Gotchas (errores que ya nos costaron)

- **No mezclar `--no_history` sobre datos históricos ya cargados.** `persist_inverter_history`
  hace `DELETE` de TODOS los `day`+`month` del inversor antes de insertar. Con
  `--no_history` solo reinserta el año actual ⇒ **borra los años anteriores**.
  Regla: el histórico se baja **completo una vez**; los refrescos incrementales
  usan el año actual *solo si te basta con eso*, o se ajusta la lógica de persist
  para no borrar años previos (ver §7).
- **`type` ≠ `"inverter"`** → `datas` vacío silencioso. Siempre usar `deviceTypeName`.
- **Paginación**: confiar en `obj.pages`, no en `len(datas) < 10`.
- **Status**: code `1` del portal = `online` (no offline). Mapeo en `STATUS_MAP`.
- **HOUR debe dar 288 muestras** (no 24). Si da 24, versión vieja del scraper.
- **Sin lat/lng** → el endpoint `weather` da `null`; correr `python -m src.scraper.plant_location`.

---

## 7. Recomendación: ¿límite de 1 año o serie de tiempo completa en Postgres?

**TL;DR: guarda la serie de tiempo completa (no la recortes a 1 año), pero
extrae el histórico UNA sola vez y luego corre syncs incrementales.** El cuello de
botella real es el *scraping*, no el almacenamiento.

### Por qué la serie completa gana

- **El almacenamiento no es el problema.** Una corrida típica fueron ~50 k filas
  (`day`+`month`+`hour`) para 37 inversores. Aún sumando hourly a diario
  (24 filas/inversor/día ≈ 320 k filas/año para 37 inversores), Postgres maneja
  millones de filas sin despeinarse. Recortar a 1 año ahorra MB, no GB.
- **El histórico tiene valor analítico** que no se recupera si lo tiras:
  comparativas año-a-año, degradación del panel, estacionalidad, detección de
  caídas de rendimiento. Una vez borrado, **re-scrapearlo es caro** (muchos
  `MonthChart`, 1 request por mes por año por inversor).
- **El costo real es tiempo de portal, no disco.** `--no_history` es útil para
  *velocidad de sync*, no para *ahorrar espacio*. La optimización correcta es:
  **backfill completo 1 vez → incrementales chicos** (año actual + últimos N días).

### El matiz importante: por granularidad

| Dato | Volumen | Recomendación |
|---|---|---|
| `month` | minúsculo (12/año/inversor) | Guardar **siempre, todo el histórico** |
| `day` | pequeño (~365/año/inversor) | Guardar **siempre, todo el histórico** |
| `hour` (5-min) | **pesado** (288 muestras/día/inversor) | Aquí **sí** aplicar retención (p.ej. 90 días de detalle 5-min; agregados horarios 1–2 años) |

O sea: el "límite de 1 año" tiene sentido **solo para el dato horario de alta
resolución**, no para day/month.

### Sobre el motor: SQLite vs Postgres (vs TimescaleDB)

- Hoy el dev usa **SQLite** (`growatt_test.db`) — perfecto para pruebas.
- Para producción con histórico real y consultas por rango de fechas, **Postgres**
  (ya soportado vía `DATABASE_URL` / docker-compose). Indexa bien por
  `reading_date` y `device_sn`.
- Si el dato **horario 5-min** crece mucho, **TimescaleDB** (extensión de Postgres)
  es el ideal: *hypertables*, compresión nativa y *retention policies* automáticas
  (ej. "comprime > 30 días, borra > 1 año") sin tocar el código de la app.

### Cambio sugerido para habilitar incrementales sin perder histórico

`persist_inverter_history` hoy borra todo `day`+`month` del inversor. Para
incrementales seguros, acotar el `DELETE` al rango que se va a reinsertar
(p.ej. solo el año en curso) en vez de borrar todo. Así `--no_history` deja de
ser destructivo y se puede correr a diario.

**Veredicto:** serie de tiempo completa en **Postgres**, histórico `day`/`month`
sin límite, y retención SOLO sobre el `hour` de 5 minutos (con TimescaleDB si el
volumen lo justifica).
