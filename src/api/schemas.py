"""Esquemas de respuesta de la API."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PlantOut(BaseModel):
    plant_id: str
    name: str
    account: str | None = None
    server: str | None = None


class InverterOut(BaseModel):
    device_sn: str
    plant_id: str
    device_type_name: str | None = None
    model: str | None = None
    alias: str | None = None
    status: str | None = None


class EnergyPoint(BaseModel):
    """Punto de energía por período (day/month/year)."""
    reading_date: date
    energy_kwh: float | None = None


class HourSample(BaseModel):
    """Muestra 5-min — formato idéntico al chart 'Hour' del portal Growatt."""
    reading_date: date
    sample_time: str          # HH:MM (00:00, 00:05, …, 23:55) — 288 puntos por día
    power_w: float


class HourAggregate(BaseModel):
    """Resumen por hora (peak / avg / kWh) — disponible vía aggregate=true."""
    reading_date: date
    reading_hour: int
    energy_kwh: float | None = None
    peak_power_w: float | None = None
    avg_power_w: float | None = None
