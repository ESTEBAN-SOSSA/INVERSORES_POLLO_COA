"""API REST de lectura de inversores y energía (FastAPI).

Autenticación: cabecera `X-API-Key`.
Endpoints:
  GET /api/v1/plants
  GET /api/v1/plants/{plant_id}/inverters
  GET /api/v1/inverters/{sn}/energy?granularity=hour|day|month|year
"""
from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import require_api_key
from src.api.schemas import EnergyPoint, HourAggregate, HourSample, InverterOut, PlantOut
from src.db.base import get_db
from src.db.models import Device, EnergyReading, Plant

app = FastAPI(
    title="Growatt Inversores — POLLO COA",
    version="1.0.0",
    description="Generación por inversor (Hour/Day/Month/Year) extraída de Growatt OSS.",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/plants", response_model=list[PlantOut],
         dependencies=[Depends(require_api_key)])
def list_plants(db: Session = Depends(get_db)) -> list[Plant]:
    return list(db.scalars(select(Plant).order_by(Plant.name)))


@app.get("/api/v1/plants/{plant_id}/inverters", response_model=list[InverterOut],
         dependencies=[Depends(require_api_key)])
def plant_inverters(plant_id: str, db: Session = Depends(get_db)) -> list[Device]:
    inv = list(db.scalars(
        select(Device).where(Device.plant_id == plant_id).order_by(Device.device_sn)))
    if not inv and db.get(Plant, plant_id) is None:
        raise HTTPException(status_code=404, detail="Planta no encontrada")
    return inv


@app.get("/api/v1/inverters/{sn}/energy",
         dependencies=[Depends(require_api_key)])
def inverter_energy(
    sn: str,
    granularity: str = Query("day", pattern="^(hour|day|month|year)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(10000, le=10000, ge=1),
    aggregate: bool = Query(False, description="Sólo para granularity=hour: si "
                            "True devuelve resumen por hora (energy_kwh/peak/avg) "
                            "en vez de las 288 muestras 5-min."),
    db: Session = Depends(get_db),
):
    if db.get(Device, sn) is None:
        raise HTTPException(status_code=404, detail="Inversor no encontrado")

    # YEAR: agregamos las filas 'month' por año (no se persiste granularidad year).
    if granularity == "year":
        stmt = select(
            func.strftime("%Y", EnergyReading.reading_date).label("yr"),
            func.sum(EnergyReading.energy_kwh),
        ).where(
            EnergyReading.device_sn == sn,
            EnergyReading.granularity == "month",
        ).group_by("yr").order_by("yr")
        rows = db.execute(stmt).all()
        return [EnergyPoint(reading_date=date(int(yr), 1, 1), energy_kwh=round(total, 2))
                for yr, total in rows if yr]

    base = select(EnergyReading).where(
        EnergyReading.device_sn == sn,
        EnergyReading.granularity == granularity,
    )
    if date_from:
        base = base.where(EnergyReading.reading_date >= date_from)
    if date_to:
        base = base.where(EnergyReading.reading_date <= date_to)
    base = base.order_by(EnergyReading.reading_date, EnergyReading.reading_hour).limit(limit)
    rows = list(db.scalars(base))

    if granularity == "hour":
        if aggregate:
            return [HourAggregate(
                reading_date=r.reading_date, reading_hour=r.reading_hour,
                energy_kwh=r.energy_kwh, peak_power_w=r.peak_power_w,
                avg_power_w=r.avg_power_w) for r in rows]
        # Por defecto: 288 muestras 5-min planas {reading_date, sample_time, power_w}
        # — formato idéntico al chart "Hour" del portal Growatt.
        samples: list[HourSample] = []
        for r in rows:
            five = (r.raw or {}).get("samples_5min_w") or []
            for i, w in enumerate(five):
                total_min = r.reading_hour * 60 + i * 5
                hh, mm = divmod(total_min, 60)
                samples.append(HourSample(
                    reading_date=r.reading_date,
                    sample_time=f"{hh:02d}:{mm:02d}",
                    power_w=float(w)))
        return samples

    return [EnergyPoint(reading_date=r.reading_date, energy_kwh=r.energy_kwh) for r in rows]
