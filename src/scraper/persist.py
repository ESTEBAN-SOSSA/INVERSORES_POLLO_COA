"""Persistencia idempotente de plantas, inversores y lecturas de energía.

Estrategia DELETE+INSERT acotada por rango de fechas (no borra todo el
histórico): así un refresco incremental del año actual no elimina años
previos. Mapea el índice único
(plant_id, device_sn, reading_date, granularity, reading_hour).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, delete
from sqlalchemy.orm import Session

from src.db.models import Device, EnergyReading, Plant


# --------------------------------------------------------------------------- #
#  Metadatos
# --------------------------------------------------------------------------- #
def upsert_plant(session: Session, plant_id: str, name: str,
                 server: str | None = None, account: str | None = None,
                 raw: dict | None = None) -> None:
    plant = session.get(Plant, plant_id)
    if plant is None:
        plant = Plant(plant_id=plant_id)
        session.add(plant)
    plant.name = name
    if server is not None:
        plant.server = server
    if account is not None:
        plant.account = account
    if raw is not None:
        plant.raw = raw


def upsert_inverter_meta(session: Session, plant_id: str, device: dict) -> str:
    """Inserta/actualiza la fila del inversor en `devices`. Devuelve el SN."""
    sn = device.get("sn")
    dev = session.get(Device, sn)
    if dev is None:
        dev = Device(device_sn=sn, plant_id=plant_id)
        session.add(dev)
    dev.plant_id = plant_id
    dev.type = "inverter"
    dev.device_type_name = device.get("deviceTypeName")
    dev.model = device.get("deviceModel")
    dev.alias = device.get("alias")
    # status del portal: "1" = online; resto = offline (ver STATUS_MAP).
    dev.status = "online" if str(device.get("status")) == "1" else "offline"
    dev.raw = {
        "nominalPower": device.get("nominalPower"),
        "datalogSn": device.get("datalogSn"),
        "datalogTypeTest": device.get("datalogTypeTest"),
        "eToday": device.get("eToday"),
        "eMonth": device.get("eMonth"),
        "eTotal": device.get("eTotal"),
        "pac": device.get("pac"),
        "lastUpdateTime": device.get("lastUpdateTime"),
        "location": device.get("location"),
    }
    return sn


# --------------------------------------------------------------------------- #
#  Lecturas de energía
# --------------------------------------------------------------------------- #
def _delete_range(session: Session, plant_id: str, sn: str, granularity: str,
                  rows: list[dict]) -> None:
    """Borra lecturas existentes del rango [min,max] de las filas a insertar."""
    if not rows:
        return
    dates = [r["reading_date"] for r in rows]
    session.execute(
        delete(EnergyReading).where(and_(
            EnergyReading.device_sn == sn,
            EnergyReading.plant_id == plant_id,
            EnergyReading.granularity == granularity,
            EnergyReading.reading_date >= min(dates),
            EnergyReading.reading_date <= max(dates),
        ))
    )


def persist_inverter_history(session: Session, plant_id: str, sn: str,
                             day_rows: list[dict], month_rows: list[dict]) -> tuple[int, int]:
    """DELETE acotado + INSERT de day y month. Devuelve (n_days, n_months)."""
    _delete_range(session, plant_id, sn, "day", day_rows)
    _delete_range(session, plant_id, sn, "month", month_rows)
    for r in day_rows + month_rows:
        session.add(EnergyReading(
            plant_id=plant_id, device_sn=sn,
            granularity=r["granularity"], reading_date=r["reading_date"],
            reading_hour=None, energy_kwh=r["energy_kwh"],
        ))
    return len(day_rows), len(month_rows)


def persist_inverter_hourly(session: Session, plant_id: str, sn: str,
                            day: date, hour_rows: list[dict]) -> int:
    """DELETE de las horas de ese día + INSERT de las 24 filas."""
    session.execute(
        delete(EnergyReading).where(and_(
            EnergyReading.device_sn == sn,
            EnergyReading.plant_id == plant_id,
            EnergyReading.granularity == "hour",
            EnergyReading.reading_date == day,
        ))
    )
    for r in hour_rows:
        session.add(EnergyReading(
            plant_id=plant_id, device_sn=sn,
            granularity="hour", reading_date=r["reading_date"],
            reading_hour=r["reading_hour"], energy_kwh=r["energy_kwh"],
            peak_power_w=r.get("peak_power_w"), avg_power_w=r.get("avg_power_w"),
            raw=r.get("raw"),
        ))
    return len(hour_rows)
