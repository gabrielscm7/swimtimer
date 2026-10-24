"""Semeadura de demonstracao do telao (nao e coletado pelo pytest).

Uso:
    python scripts/seed_demo.py [--db CAMINHO] [--name NOME] [--date AAAA-MM-DD]

Cria, via API, um evento com 8 equipes, uma prova masculina (5 baterias de
7 raias: 3 finalizadas, 1 ativa e 1 agendada) e uma prova MISTO (2 baterias de
7 raias, finalizadas). Os tempos sao deterministicos e os nomes sao longos
para exercitar o truncamento em uma linha no telao.

O modulo tambem expoe `build_demo`/`build_waiting_event` para o tv_check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TEAMS = [
    "Golfinhos Azuis",
    "Leões do Norte",
    "Tubarões do Sul",
    "Águias Douradas",
    "Focas Prateadas",
    "Orcas Gigantes",
    "Pinguins Polares",
    "Estrelas do Mar",
]

FIRST_NAMES = [
    "Ana Beatriz",
    "João Pedro",
    "Maria Eduarda",
    "Lucas Gabriel",
    "Isabela Cristina",
    "Matheus Henrique",
    "Larissa",
    "Rafael",
    "Giovanna",
    "Gustavo",
    "Camila",
    "Vinícius",
    "Letícia",
    "Bruno",
    "Fernanda",
    "Thiago",
]

LAST_NAMES = [
    "de Albuquerque Nascimento",
    "dos Santos Oliveira",
    "da Silva Costa",
    "Pereira Martins",
    "Ferreira de Souza",
    "Nogueira Almeida",
    "Ribeiro Carvalho",
    "Barbosa Lima",
]

LANES = 7
EVENT_DATE = "2026-10-24"
MALE_HEATS = 5
MIXED_HEATS = 2
ATHLETES_PER_TEAM = 10


def configure_env(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    data_dir = db_path.parent
    os.environ.setdefault("LOGO_DIR", str(data_dir / "logos"))
    os.environ.setdefault("THEME_DIR", str(data_dir / "theme"))
    os.environ.setdefault("JOURNAL_DIR", str(data_dir / "journal"))
    os.environ.setdefault("BACKUP_DIR", str(data_dir / "backups"))
    os.environ.pop("OPERATOR_PIN", None)


def _sqlite_path() -> str | None:
    url = os.environ.get("DATABASE_URL", "")
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return None
    return url[len(prefix):]


def _set_times(heat_id: str, times: dict[int, int]) -> None:
    path = _sqlite_path()
    if not path:
        raise RuntimeError("DATABASE_URL precisa ser um arquivo sqlite")
    with sqlite3.connect(path, timeout=30) as conn:
        for lane_number, time_ms in times.items():
            conn.execute(
                "UPDATE heat_lane SET race_time_ms = ? "
                "WHERE heat_id = ? AND lane_number = ?",
                (time_ms, heat_id, lane_number),
            )
        conn.commit()


def _athlete_rows() -> list[dict]:
    rows = []
    for team_index in range(len(TEAMS)):
        for index in range(ATHLETES_PER_TEAM):
            name_index = team_index * ATHLETES_PER_TEAM + index
            first = FIRST_NAMES[name_index % len(FIRST_NAMES)]
            last = LAST_NAMES[(team_index * 3 + index) % len(LAST_NAMES)]
            rows.append(
                {
                    "team_index": team_index,
                    "name": f"{first} {last}",
                    "naipe": "M" if index < 6 else "F",
                }
            )
    return rows


async def _request(client, method: str, path: str, body=None):
    response = await client.request(method, path, json=body)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text}")
    return response.json()


async def _post(client, path: str, body=None):
    return await _request(client, "POST", path, body)


async def _get(client, path: str):
    return await _request(client, "GET", path)


async def _put(client, path: str, body=None):
    return await _request(client, "PUT", path, body)


async def _create_heat(
    client,
    event_id: str,
    *,
    name: str,
    stroke: str,
    distance_m: int,
    naipe: str,
    order_num: int,
) -> dict:
    return await _post(
        client,
        f"/api/events/{event_id}/heats",
        {
            "name": name,
            "heat_type": "bateria",
            "stroke": stroke,
            "distance_m": distance_m,
            "naipe": naipe,
            "category": "livre",
            "lane_count": LANES,
            "order_num": order_num,
        },
    )


async def _assign(client, heat_id: str, athletes: list[dict]) -> dict:
    response = await _post(
        client,
        f"/api/heats/{heat_id}/lanes",
        {
            "lanes": [
                {"lane_number": number, "athlete_id": athlete["id"]}
                for number, athlete in enumerate(athletes, start=1)
            ]
        },
    )
    return response


async def _ready_all(client, heat_id: str) -> None:
    heat = await _get(client, f"/api/heats/{heat_id}")
    for lane in heat["heat_lanes"]:
        await _post(client, f"/api/lanes/{lane['id']}/ready")


async def _start(client, heat_id: str) -> None:
    await _post(client, f"/api/heats/{heat_id}/open-ready-check")
    await _ready_all(client, heat_id)
    await _post(client, f"/api/heats/{heat_id}/start")


async def _finish(client, heat_id: str, times: dict[int, int]) -> None:
    await _start(client, heat_id)
    await asyncio.sleep(0.02)
    heat = await _get(client, f"/api/heats/{heat_id}")
    for lane in heat["heat_lanes"]:
        await _post(client, f"/api/lanes/{lane['id']}/finish")
    _set_times(heat_id, times)


def _heat_times(heat_index: int, base: int, step: int) -> dict[int, int]:
    return {
        lane: base + heat_index * step + lane * 130
        for lane in range(1, LANES + 1)
    }


async def build_demo(
    client,
    *,
    event_name: str,
    date: str = EVENT_DATE,
    pool_length_m: int = 25,
) -> dict:
    event = await _post(
        client,
        "/api/events",
        {
            "name": event_name,
            "date": date,
            "pool_length_m": pool_length_m,
            "default_lane_count": LANES,
        },
    )
    teams = []
    for name in TEAMS:
        teams.append(
            await _post(
                client, f"/api/events/{event['id']}/teams", {"name": name}
            )
        )

    athletes = []
    for row in _athlete_rows():
        athletes.append(
            await _post(
                client,
                f"/api/events/{event['id']}/athletes",
                {
                    "name": row["name"],
                    "naipe": row["naipe"],
                    "team_id": teams[row["team_index"]]["id"],
                    "category": "livre",
                    "registration_code": f"D{len(athletes):03d}",
                },
            )
        )
    males = [athlete for athlete in athletes if athlete["naipe"] == "M"]
    females = [athlete for athlete in athletes if athlete["naipe"] == "F"]

    male_heats = []
    for index in range(MALE_HEATS):
        male_heats.append(
            await _create_heat(
                client,
                event["id"],
                name=f"Eliminatória {index + 1}",
                stroke="livre",
                distance_m=50,
                naipe="M",
                order_num=index + 1,
            )
        )

    mixed_heats = []
    for index in range(MIXED_HEATS):
        mixed_heats.append(
            await _create_heat(
                client,
                event["id"],
                name=f"Final Mista {index + 1}",
                stroke="costas",
                distance_m=100,
                naipe="MISTO",
                order_num=MALE_HEATS + index + 1,
            )
        )

    male_pool = males[: MALE_HEATS * LANES]
    for index, heat in enumerate(male_heats):
        start = index * LANES
        await _assign(client, heat["id"], male_pool[start : start + LANES])

    mixed_pool = []
    for index in range(MIXED_HEATS * LANES):
        source = males[MALE_HEATS * LANES:] if index % 2 == 0 else females
        mixed_pool.append(source[index // 2])
    for index, heat in enumerate(mixed_heats):
        start = index * LANES
        await _assign(client, heat["id"], mixed_pool[start : start + LANES])

    for index in range(3):
        await _finish(
            client,
            male_heats[index]["id"],
            _heat_times(index, base=28000, step=450),
        )
    await _start(client, male_heats[3]["id"])

    for index in range(MIXED_HEATS):
        await _finish(
            client,
            mixed_heats[index]["id"],
            _heat_times(index, base=32000, step=520),
        )

    await _put(
        client,
        f"/api/events/{event['id']}/presentation",
        {
            "enabled": False,
            "rotation": True,
            "slide_duration_s": 15,
            "show_next_prova": True,
            "pinned_ref": None,
            "slides": [],
        },
    )

    return {
        "event_id": event["id"],
        "event_name": event["name"],
        "male_prova_id": male_heats[0]["prova_id"],
        "mixed_prova_id": mixed_heats[0]["prova_id"],
        "active_heat_id": male_heats[3]["id"],
        "scheduled_heat_id": male_heats[4]["id"],
        "teams": len(teams),
        "athletes": len(athletes),
    }


async def build_waiting_event(
    client, *, event_name: str, date: str = EVENT_DATE
) -> dict:
    event = await _post(
        client,
        "/api/events",
        {
            "name": event_name,
            "date": date,
            "pool_length_m": 25,
            "default_lane_count": LANES,
        },
    )
    heats = [
        await _create_heat(
            client,
            event["id"],
            name="Bateria 1",
            stroke="livre",
            distance_m=50,
            naipe="M",
            order_num=1,
        ),
        await _create_heat(
            client,
            event["id"],
            name="Bateria 2",
            stroke="livre",
            distance_m=100,
            naipe="F",
            order_num=2,
        ),
    ]
    return {"event_id": event["id"], "heats": [heat["id"] for heat in heats]}


async def seed(db_path: Path, *, event_name: str, date: str) -> dict:
    configure_env(db_path)
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://seed"
        ) as client:
            return await build_demo(client, event_name=event_name, date=date)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(BACKEND / "data" / "demo.db"),
        help="arquivo SQLite de destino (padrao: backend/data/demo.db)",
    )
    parser.add_argument(
        "--name", default="Copa SwimTimer · Etapa Demonstração"
    )
    parser.add_argument("--date", default=EVENT_DATE)
    args = parser.parse_args()

    info = asyncio.run(
        seed(Path(args.db), event_name=args.name, date=args.date)
    )
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print()
    print("Telão:")
    print(f"  publico.html?event={info['event_id']}")
    print("Servidor:")
    print(
        f"  DATABASE_URL=sqlite+aiosqlite:///{Path(args.db).resolve()} "
        "uvicorn app.main:app"
    )


if __name__ == "__main__":
    main()
