import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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
    provas: Mapped[list["Prova"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="Prova.order_num",
    )
    heats: Mapped[list["Heat"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="Heat.order_num",
    )
    athletes: Mapped[list["Athlete"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )


class Prova(Base):
    """Agrupa varias baterias sob a mesma prova (ex.: 100m livres masculino)."""

    __tablename__ = "prova"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    order_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stroke: Mapped[str | None] = mapped_column(String, nullable=True)
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    naipe: Mapped[str | None] = mapped_column(String, nullable=True)
    consolidate_results: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    classification_criterion: Mapped[str] = mapped_column(
        String, default="lowest_time", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, default="scheduled", nullable=False
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    event: Mapped["Event"] = relationship(back_populates="provas")
    heats: Mapped[list["Heat"]] = relationship(
        back_populates="prova",
        cascade="all, delete-orphan",
        order_by="Heat.order_num",
    )

    __table_args__ = (
        Index("ix_prova_event_order", "event_id", "order_num"),
        UniqueConstraint(
            "event_id", "order_num", name="uq_prova_event_order"
        ),
    )


class Team(Base):
    __tablename__ = "team"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)

    event: Mapped["Event"] = relationship(back_populates="teams")
    lanes: Mapped[list["HeatLane"]] = relationship(back_populates="team")
    athletes: Mapped[list["Athlete"]] = relationship(back_populates="team")


class Athlete(Base):
    """Atleta inscrito em um evento, independente das baterias.

    A alocacao em raia referencia o atleta por `heat_lane.athlete_id`; nome e
    equipe exibidos na raia sao derivados deste registro (fonte unica de
    verdade), evitando divergencia de dados entre cadastro e prova.
    """

    __tablename__ = "athlete"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event.id"), nullable=False
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("team.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    naipe: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    event: Mapped["Event"] = relationship(back_populates="athletes")
    team: Mapped["Team | None"] = relationship(back_populates="athletes")
    lanes: Mapped[list["HeatLane"]] = relationship(back_populates="athlete")

    __table_args__ = (
        Index("ix_athlete_event", "event_id"),
        Index("ix_athlete_event_team", "event_id", "team_id"),
        Index("ix_athlete_event_name", "event_id", "name"),
        Index(
            "uq_athlete_event_name_team",
            text("event_id"),
            text("name COLLATE NOCASE"),
            text("COALESCE(team_id, '')"),
            unique=True,
        ),
    )


class Heat(Base):
    __tablename__ = "heat"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event.id"), nullable=False
    )
    prova_id: Mapped[str] = mapped_column(
        ForeignKey("prova.id"), nullable=False
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
    prova: Mapped["Prova"] = relationship(back_populates="heats")
    lanes: Mapped[list["HeatLane"]] = relationship(
        back_populates="heat",
        cascade="all, delete-orphan",
        order_by="HeatLane.lane_number",
    )

    __table_args__ = (
        Index("ix_heat_event_order", "event_id", "order_num"),
        Index("ix_heat_prova_order", "prova_id", "order_num"),
        UniqueConstraint("prova_id", "order_num", name="uq_heat_prova_order"),
    )


class HeatLane(Base):
    __tablename__ = "heat_lane"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    heat_id: Mapped[str] = mapped_column(
        ForeignKey("heat.id"), nullable=False
    )
    lane_number: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    athlete_id: Mapped[str | None] = mapped_column(
        ForeignKey("athlete.id"), nullable=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("team.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, default="assigned", nullable=False
    )
    finish_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    race_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    late: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )

    heat: Mapped["Heat"] = relationship(back_populates="lanes")
    athlete: Mapped["Athlete | None"] = relationship(back_populates="lanes")
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
    received_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    late: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )

    lane: Mapped["HeatLane"] = relationship(back_populates="lap_events")

    __table_args__ = (
        Index("ix_lap_event_lane_recorded", "lane_id", "recorded_at"),
        UniqueConstraint("lane_id", "lap_number", name="uq_lap_event_lane_number"),
    )


class ActionLog(Base):
    """Auditoria de toda acao que muda estado do sistema."""

    __tablename__ = "action_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    received_at: Mapped[float] = mapped_column(Float, nullable=False)
    effective_ts: Mapped[float] = mapped_column(Float, nullable=False)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    heat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lane_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    op_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_action_log_heat_received", "heat_id", "received_at"),
    )


class ProcessedOp(Base):
    """Resultado original de um op_id, para reenvios idempotentes."""

    __tablename__ = "processed_op"

    op_id: Mapped[str] = mapped_column(String, primary_key=True)
    lane_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
