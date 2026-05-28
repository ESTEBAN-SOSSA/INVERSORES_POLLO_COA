"""Modelo de datos: plants, devices, energy_readings.

Esquema alineado con el runbook EXTRACCION_INVERSORES.md:

- `plants`        — una fila por planta (incluye server/account para reabrir popup).
- `devices`       — una fila por inversor (type="inverter"; deviceTypeName real en raw).
- `energy_readings` — serie de tiempo Hour/Day/Month/Year por inversor.
  Índice único (plant_id, device_sn, reading_date, granularity, reading_hour)
  → garantiza idempotencia del DELETE+INSERT del scraper.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class Plant(Base):
    __tablename__ = "plants"

    plant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)

    # Necesarios para reabrir el popup de server.growatt.com (showPlant).
    server: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    # Ubicación (para weather); puede llegar nula y completarse con plant_location.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    devices: Mapped[list["Device"]] = relationship(
        back_populates="plant", cascade="all, delete-orphan"
    )


class Device(Base):
    __tablename__ = "devices"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    plant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("plants.plant_id", ondelete="CASCADE"), index=True
    )

    # type lógico de la app (siempre "inverter"); el deviceTypeName REAL
    # de Growatt (max/mix/storage/inv/noah...) va en device_type_name + raw.
    type: Mapped[str] = mapped_column(String(32), default="inverter")
    device_type_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    plant: Mapped["Plant"] = relationship(back_populates="devices")


class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant_id: Mapped[str] = mapped_column(String(64), index=True)
    device_sn: Mapped[str] = mapped_column(String(64), index=True)

    # "hour" | "day" | "month" | "year"
    granularity: Mapped[str] = mapped_column(String(8), index=True)
    reading_date: Mapped[date] = mapped_column(index=True)
    # 0..23 sólo para granularity="hour"; null en el resto.
    reading_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)

    # raw.samples_5min_w = 12 valores W (sólo hour)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "plant_id",
            "device_sn",
            "reading_date",
            "granularity",
            "reading_hour",
            name="uq_energy_reading",
        ),
        Index("ix_energy_sn_gran_date", "device_sn", "granularity", "reading_date"),
    )
