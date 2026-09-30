import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Competition(Base):
    __tablename__ = "competition"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    meters_lap: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(
        String, default="maratona", nullable=False
    )
    distance_m: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=25
    )
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    teams: Mapped[list["Team"]] = relationship(
        back_populates="competition",
        cascade="all, delete-orphan",
    )
    lanes: Mapped[list["Lane"]] = relationship(
        back_populates="competition",
        cascade="all, delete-orphan",
    )


class Team(Base):
    __tablename__ = "team"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    competition_id: Mapped[str] = mapped_column(
        ForeignKey("competition.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)

    competition: Mapped["Competition"] = relationship(back_populates="teams")
    lanes: Mapped[list["Lane"]] = relationship(back_populates="team")


class Lane(Base):
    __tablename__ = "lane"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    competition_id: Mapped[str] = mapped_column(
        ForeignKey("competition.id"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("team.id"), nullable=True
    )
    laps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String, default="waiting", nullable=False)
    participant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    finish_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    race_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    competition: Mapped["Competition"] = relationship(back_populates="lanes")
    team: Mapped["Team | None"] = relationship(back_populates="lanes")
    lap_events: Mapped[list["LapEvent"]] = relationship(
        back_populates="lane",
        cascade="all, delete-orphan",
    )


class LapEvent(Base):
    __tablename__ = "lap_event"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lane_id: Mapped[str] = mapped_column(ForeignKey("lane.id"), nullable=False)
    lap_number: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[float] = mapped_column(Float, nullable=False)
    is_undo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lane: Mapped["Lane"] = relationship(back_populates="lap_events")

    __table_args__ = (
        Index("idx_lap_event_lane", "lane_id"),
        Index("idx_lap_event_recorded", "recorded_at"),
    )
