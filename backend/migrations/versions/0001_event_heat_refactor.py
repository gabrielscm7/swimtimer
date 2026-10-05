"""Refatoracao arquitetural: Competition -> Event + Heat

Cria as tabelas event, team, heat e heat_lane e migra os dados do modelo
antigo (competition, team, lane) quando ele estiver presente. O lap_event e
preservado: os IDs das raias antigas sao reutilizados como IDs das heat_lane
para manter a integridade das referencias.

Em um banco novo (sem a tabela competition) apenas cria o schema novo.

Revision ID: 0001_event_heat_refactor
Revises:
Create Date: 2026-09-30

"""
from typing import Sequence, Union

import uuid as _uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "0001_event_heat_refactor"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _new_id() -> str:
    return str(_uuid.uuid4())


def _create_new_schema() -> None:
    op.create_table(
        "event",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("pool_length_m", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "team",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("event.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
    )
    op.create_table(
        "heat",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("event.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("order_num", sa.Integer(), nullable=False),
        sa.Column("heat_type", sa.String(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("finished_at", sa.Float(), nullable=True),
    )
    op.create_index("ix_heat_event_order", "heat", ["event_id", "order_num"])
    op.create_table(
        "heat_lane",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "heat_id",
            sa.String(),
            sa.ForeignKey("heat.id"),
            nullable=False,
        ),
        sa.Column("lane_number", sa.Integer(), nullable=False),
        sa.Column("participant_name", sa.String(), nullable=True),
        sa.Column(
            "team_id",
            sa.String(),
            sa.ForeignKey("team.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("finish_at", sa.Float(), nullable=True),
        sa.Column("race_time_ms", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_heat_lane_heat_number",
        "heat_lane",
        ["heat_id", "lane_number"],
        unique=True,
    )


def _create_lap_event() -> None:
    op.create_table(
        "lap_event",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "lane_id",
            sa.String(),
            sa.ForeignKey("heat_lane.id"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.Float(), nullable=False),
        sa.Column("is_undo", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_lap_event_lane_recorded",
        "lap_event",
        ["lane_id", "recorded_at"],
    )


def _migrate_legacy(bind) -> None:
    comps = bind.execute(
        text(
            "SELECT id, name, status, duration_s, meters_lap, event_type, "
            "distance_m, started_at, finished_at, created_at "
            "FROM competition"
        )
    ).mappings().all()

    event_status_map = {"active": "active", "finished": "finished"}
    heat_status_map = {
        "draft": "scheduled",
        "active": "active",
        "finished": "finished",
    }
    heat_map: dict[str, str] = {}

    for comp in comps:
        event_id = comp["id"]
        heat_id = _new_id()
        heat_map[event_id] = heat_id
        event_status = event_status_map.get(comp["status"], "draft")
        heat_status = heat_status_map.get(comp["status"], "scheduled")
        heat_type = comp["event_type"] or "maratona"
        distance_m = comp["distance_m"] if heat_type == "bateria" else None

        bind.execute(
            text(
                "INSERT INTO event "
                "(id, name, location, date, pool_length_m, status, created_at) "
                "VALUES (:id, :name, NULL, NULL, :pool, :status, :created)"
            ),
            {
                "id": event_id,
                "name": comp["name"],
                "pool": comp["meters_lap"],
                "status": event_status,
                "created": comp["created_at"],
            },
        )
        bind.execute(
            text(
                "INSERT INTO heat "
                "(id, event_id, name, order_num, heat_type, distance_m, "
                "duration_s, status, started_at, finished_at) "
                "VALUES (:id, :event, :name, 1, :htype, :dist, :dur, "
                ":status, :started, :finished)"
            ),
            {
                "id": heat_id,
                "event": event_id,
                "name": comp["name"],
                "htype": heat_type,
                "dist": distance_m,
                "dur": comp["duration_s"],
                "status": heat_status,
                "started": comp["started_at"],
                "finished": comp["finished_at"],
            },
        )

    if "team_old" in inspect(bind).get_table_names():
        teams = bind.execute(
            text("SELECT id, competition_id, name FROM team_old")
        ).mappings().all()
        for team in teams:
            bind.execute(
                text(
                    "INSERT INTO team (id, event_id, name) "
                    "VALUES (:id, :event, :name)"
                ),
                {
                    "id": team["id"],
                    "event": team["competition_id"],
                    "name": team["name"],
                },
            )

    lanes = bind.execute(
        text(
            "SELECT id, competition_id, number, team_id, status, "
            "participant_name, finish_at, race_time_ms FROM lane"
        )
    ).mappings().all()
    lane_status_map = {"waiting": "assigned"}
    for lane in lanes:
        heat_id = heat_map.get(lane["competition_id"])
        if heat_id is None:
            continue
        bind.execute(
            text(
                "INSERT INTO heat_lane "
                "(id, heat_id, lane_number, participant_name, team_id, "
                "status, finish_at, race_time_ms) "
                "VALUES (:id, :heat, :number, :participant, :team, "
                ":status, :finish, :race)"
            ),
            {
                "id": lane["id"],
                "heat": heat_id,
                "number": lane["number"],
                "participant": lane["participant_name"],
                "team": lane["team_id"],
                "status": lane_status_map.get(lane["status"], lane["status"]),
                "finish": lane["finish_at"],
                "race": lane["race_time_ms"],
            },
        )

    if "lap_event" in inspect(bind).get_table_names():
        existing_indexes = {
            idx["name"] for idx in inspect(bind).get_indexes("lap_event")
        }
        for index_name in ("idx_lap_event_lane", "idx_lap_event_recorded"):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="lap_event")
        op.create_index(
            "ix_lap_event_lane_recorded",
            "lap_event",
            ["lane_id", "recorded_at"],
        )


def _assert_migration_counts(bind) -> None:
    competitions = bind.execute(
        text("SELECT COUNT(*) FROM competition")
    ).scalar_one()
    events = bind.execute(text("SELECT COUNT(*) FROM event")).scalar_one()
    if events < competitions:
        raise RuntimeError(
            "migracao abortada: nem todas as competitions viraram event"
        )
    lanes = bind.execute(text("SELECT COUNT(*) FROM lane")).scalar_one()
    heat_lanes = bind.execute(
        text("SELECT COUNT(*) FROM heat_lane")
    ).scalar_one()
    if heat_lanes < lanes:
        raise RuntimeError(
            "migracao abortada: nem todas as lanes viraram heat_lane"
        )


def _drop_legacy() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    op.drop_table("lane")
    if "team_old" in inspect(bind).get_table_names():
        op.drop_table("team_old")
    op.drop_table("competition")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    legacy = "competition" in existing

    if legacy and "team" in existing:
        op.rename_table("team", "team_old")

    _create_new_schema()

    if "lap_event" not in existing:
        _create_lap_event()

    if legacy:
        _migrate_legacy(bind)
        _assert_migration_counts(bind)
        _drop_legacy()


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    op.create_table(
        "competition",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("meters_lap", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("finished_at", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "team_old",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("competition.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
    )
    op.create_table(
        "lane",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("competition.id"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "team_id",
            sa.String(),
            sa.ForeignKey("team_old.id"),
            nullable=True,
        ),
        sa.Column("laps", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("participant_name", sa.String(), nullable=True),
        sa.Column("finish_at", sa.Float(), nullable=True),
        sa.Column("race_time_ms", sa.Integer(), nullable=True),
    )
    op.drop_table("heat_lane")
    op.drop_table("heat")
    op.drop_table("team")
    op.drop_table("event")
    op.rename_table("team_old", "team")
