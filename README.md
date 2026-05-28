# INVERSORES POLLO COA — Extracción Growatt OSS

Extrae la generación **por inversor** (Hour / Day / Month / Year) de plantas
operadas en Growatt OSS, la persiste en una base de datos y la expone vía
una API REST con autenticación por `X-API-Key`.

> Foco de esta instancia: planta **POLLO COA** (`plant_id=1878757`, cuenta
> Tronex_edemco, 9 inversores `max`).

El paso a paso operativo (qué endpoints, qué cargas, qué columnas) está
documentado en [`EXTRACCION_INVERSORES.md`](EXTRACCION_INVERSORES.md).

---

## Arquitectura

```
oss.growatt.com  ──login (POST /login, MD5)──►  Plant List (showPlant onclick)
        │
        ▼  popup auto-logueado por ACCOUNT
server.growatt.com
        │  POST /panel/getDevicesByPlantList     → lista de inversores
        │  POST /energy/compare/getDevices*Chart → series 5-min / día / mes / año
        ▼
   SQLite/Postgres (energy_readings)  ──►  FastAPI  ──►  cliente
```

Módulos:

| Ruta | Qué hace |
|---|---|
| `src/scraper/growatt_client.py` | Cliente Playwright. Login programático MD5 (sin captcha), apertura del popup `server.growatt.com`, POST autenticado vía `fetch` in-page. Persiste sesión en `.auth/state.json`. |
| `src/scraper/oss_portal.py` | Lista de plantas leídas del DOM del home (`showPlant` + celdas). |
| `src/scraper/inverter_scraper.py` | `list_inverters_for_plant`, `fetch_inverter_history` (day+month), `fetch_inverter_hourly_for_date` (288 → 24 horas). |
| `src/scraper/persist.py` | DELETE acotado al rango + INSERT, idempotente. |
| `src/scraper/inverter_main.py` | CLI orquestador. |
| `src/api/main.py` | FastAPI: plantas, inversores, energía. |
| `src/db/models.py` | `plants`, `devices`, `energy_readings`. |

---

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

copy .env.example .env   # editar credenciales
.\.venv\Scripts\python.exe -m alembic upgrade head
```

`.env`:

```
GROWATT_USER=AZPA4001
GROWATT_PASSWORD=********
DATABASE_URL=sqlite:///growatt_test.db
API_KEY=PRUEBAS_GROWATT_INVERSORES
```

---

## Uso

### Extraer datos de POLLO COA

```powershell
# Histórico COMPLETO (todos los años) + hourly de los últimos 7 días
.\.venv\Scripts\python.exe -m src.scraper.inverter_main --plant_id 1878757

# Refresco incremental: sólo año actual + hourly de hoy
.\.venv\Scripts\python.exe -m src.scraper.inverter_main --plant_id 1878757 --no_history --hourly_days 1
```

> El `DELETE` está **acotado por rango de fechas**, así que `--no_history`
> sólo reescribe el año actual y **no borra años previos** (a diferencia del
> footgun descrito en §6 del runbook).

### Servir la API

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8001
```

```powershell
$H = @{ "X-API-Key" = "PRUEBAS_GROWATT_INVERSORES" }

# Plantas
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/plants" -Headers $H

# Inversores de POLLO COA
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/plants/1878757/inverters" -Headers $H

# Generación por día (todo 2026)
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/ZFEDCA6003/energy?granularity=day&date_from=2026-01-01" -Headers $H

# Detalle 5-min de hoy → 288 puntos planos (reading_date, sample_time HH:MM, power_w)
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/ZFEDCA6003/energy?granularity=hour&date_from=2026-05-28" -Headers $H

# Resumen horario (energy_kwh/peak/avg por hora) en vez de las 288 muestras
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/inverters/ZFEDCA6003/energy?granularity=hour&date_from=2026-05-28&aggregate=true" -Headers $H
```

---

## Estrategia de ramas

| Rama | Propósito |
|---|---|
| `main` | Estable. Sólo merges desde `staging` ya validados. |
| `staging` | Pre-producción. Recibe PRs desde `DEV` para validación. |
| `DEV` | Desarrollo del día a día. |

---

## Notas

* La sesión OSS dura horas/días; mientras `.auth/state.json` esté vigente
  no se vuelve a loguear. Si caduca, `ensure_login` re-hace el POST.
* La contraseña se hashea con MD5 antes del POST (igual que la propia
  página del portal), por lo que **el captcha del UI no se dispara**.
* SQLite es cómodo para dev; para producción cambiar `DATABASE_URL` a
  Postgres (recomendado TimescaleDB si el detalle 5-min crece — ver §7
  del runbook).
