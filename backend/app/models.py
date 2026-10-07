import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Event(Base):
    __tablename__ = "event"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[str | None] = mapped_column(String, nullable=True)
    pool_length_m: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    teams: Mapped[list["Team"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )
    heats: Mapped[list["Heat"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="Heat.order_num",
    )


class Team(Base):
    __tablename__ = "team"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)

    event: Mapped["Event"] = relationship(back_populates="teams")
    lanes: Mapped[list["HeatLane"]] = relationship(back_populates="team")


class Heat(Base):
    __tablename__ = "heat"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    order_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    heat_type: Mapped[str] = mapped_column(
        String, default="maratona", nullable=False
    )
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="scheduled", nullable=False
    )
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    event: Mapped["Event"] = relationship(back_populates="heats")
    lanes: Mapped[list["HeatLane"]] = relationship(
        back_populates="heat",
        cascade="all, delete-orphan",
        order_by="HeatLane.lane_number",
    )

    __table_args__ = (
        Index("ix_heat_event_order", "event_id", "order_num"),
    )


class HeatLane(Base):
    __tablename__ = "heat_lane"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    heat_id: Mapped[str] = mapped_column(
        ForeignKey("heat.id"), nullable=False
    )
    lane_number: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("team.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, default="assigned", nullable=False
    )
    finish_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    race_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    heat: Mapped["Heat"] = relationship(back_populates="lanes")
    team: Mapped["Team | None"] = relationship(back_populates="lanes")
    lap_events: Mapped[list["LapEvent"]] = relationship(
        back_populates="lane",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_heat_lane_heat_number", "heat_id", "lane_number", unique=True),
    )


class LapEvent(Base):
    __tablename__ = "lap_event"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lane_id: Mapped[str] = mapped_column(
        ForeignKey("heat_lane.id"), nullable=False
    )
    lap_number: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[float] = mapped_column(Float, nullable=False)
    is_undo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lane: Mapped["HeatLane"] = relationship(back_populates="lap_events")

    __table_args__ = (
        Index("ix_lap_event_lane_recorded", "lane_id", "recorded_at"),
        UniqueConstraint("lane_id", "lap_number", name="uq_lap_event_lane_number"),
    )
