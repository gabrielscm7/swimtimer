"""Ensaio automatico de um evento inteiro (nao e coletado pelo pytest).

Uso:
    python scripts/rehearsal.py

Cria um banco temporario e monta 8 provas, 50 baterias, 150 atletas e 8
equipes. Depois percorre as 50 baterias na ordem canonica (`event_seq`),
simula as chegadas e valida:
- a sequencia percorrida (1..50, sem misturar provas);
- o encerramento automatico de cada bateria;
- o resumo e a classificacao final de cada prova (geral e por naipe).

As chegadas simuladas sao registradas de verdade (finish) e os tempos sao
fixados de forma deterministica para permitir asserts exatos.
"""
import asyncio
import os
import sys
import tempfile
import time

N_PROVAS = 8
TOTAL_HEATS = 50
LANES = 8
TEAMS = 8
ATHLETES = 150
CATEGORY = "livre"
STROKES = ("crawl", "borboleta", "peito", "costas", "livre", "medley")


def _heats_for_prova(index: int) -> int:
    base, remainder = divmod(TOTAL_HEATS, N_PROVAS)
    return base + (1 if index < remainder else 0)


def _planned_times(event_seq: int) -> dict[int, int]:
    """Tempo deterministico por raia; raias 1 e 2 empatam (M x F no misto)."""
    base = 60000 + event_seq
    times = {1: base, 2: base}
    for lane in range(3, LANES + 1):
        times[lane] = base + lane * 100
    return times


async def main() -> None:
    tmp = tempfile.mkdtemp(prefix="swimtimer_rehearsal_")
    os.environ["DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{os.path.join(tmp, 'rehearsal.db')}"
    )
    os.environ["LOGO_DIR"] = os.path.join(tmp, "logos")
    os.environ["THEME_DIR"] = os.path.join(tmp, "theme")
    os.environ.pop("OPERATOR_PIN", None)

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from app import database as database_module
    from app.main import app
    from app.models import HeatLane

    def log(text: str = "") -> None:
        print(text)

    async def set_times(heat_id: str, times: dict[int, int]) -> None:
        async with database_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(HeatLane).where(HeatLane.heat_id == heat_id)
            )
            for lane in result.scalars().all():
                lane.race_time_ms = times[lane.lane_number]
            await session.commit()

    started = time.perf_counter()
    log("# Ensaio — SwimTimer")
    log()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://rehearsal"
        ) as client:
            event = (
                await client.post(
                    "/api/events",
                    json={
                        "name": "Ensaio Completo",
                        "date": "2026-10-23",
                        "pool_length_m": 25,
                        "default_lane_count": LANES,
                    },
                )
            ).json()

            # Equipes
            for index in range(TEAMS):
                await client.post(
                    f"/api/events/{event['id']}/teams",
                    json={"name": f"Equipe {index + 1}"},
                )

            # Atletas (com codigo de registro para homonimos)
            rows = ["NOME,EQUIPE,NAIPE,CATEGORIA,REGISTRO"]
            for index in range(ATHLETES):
                rows.append(
                    f"Atleta {index:03d},Equipe {index % TEAMS + 1},"
                    f"{'M' if index % 2 == 0 else 'F'},"
                    f"{CATEGORY},R{index:03d}"
                )
            imported = await client.post(
                f"/api/events/{event['id']}/athletes/import",
                files={
                    "file": (
                        "atletas.csv",
                        ("\n".join(rows) + "\n").encode("utf-8"),
                        "text/csv",
                    )
                },
            )
            assert imported.status_code == 200, imported.text
            athletes = (
                await client.get(
                    f"/api/events/{event['id']}/athletes",
                    params={"limit": 200},
                )
            ).json()["items"]
            assert len(athletes) == ATHLETES
            males = [athlete for athlete in athletes if athlete["naipe"] == "M"]
            females = [
                athlete for athlete in athletes if athlete["naipe"] == "F"
            ]
            mixed = []
            for index in range(max(len(males), len(females))):
                if index < len(males):
                    mixed.append(males[index])
                if index < len(females):
                    mixed.append(females[index])
            log(
                f"- {len(athletes)} atletas ({len(males)} M / "
                f"{len(females)} F), {TEAMS} equipes"
            )

            # Grupos (provas) + baterias: a prova e criada automaticamente
            # a partir dos atributos da primeira bateria de cada grupo.
            provas = []
            heat_specs = []  # (prova_index, prova, naipe, heat)
            for p in range(N_PROVAS):
                naipe = ["M", "F", "MISTO"][p % 3]
                stroke = STROKES[p % len(STROKES)]
                distance = 50 if p < len(STROKES) else 100
                prova = None
                for h in range(_heats_for_prova(p)):
                    heat = (
                        await client.post(
                            f"/api/events/{event['id']}/heats",
                            json={
                                "name": f"Bateria {h + 1}",
                                "heat_type": "bateria",
                                "stroke": stroke,
                                "distance_m": distance,
                                "naipe": naipe,
                                "category": CATEGORY,
                                "lane_count": LANES,
                            },
                        )
                    ).json()
                    if prova is None:
                        prova = {
                            "id": heat["prova_id"],
                            "naipe": naipe,
                            "stroke": stroke,
                            "distance_m": distance,
                        }
                        provas.append(prova)
                    heat_specs.append((p, prova, naipe, heat))

            # Inscricoes: atletas distintos por prova, respeitando o naipe.
            pools = {"M": males, "F": females, "MISTO": mixed}
            per_prova: dict[str, list] = {}
            for p, prova, naipe, _heat in heat_specs:
                per_prova.setdefault(prova["id"], [])
            for p in range(N_PROVAS):
                prova = provas[p]
                naipe = ["M", "F", "MISTO"][p % 3]
                needed = _heats_for_prova(p) * LANES
                pool = pools[naipe]
                start = (p * 11) % (len(pool) - needed)
                per_prova[prova["id"]] = pool[start : start + needed]

            heat_positions: dict[str, int] = {}
            for p, prova, naipe, heat in heat_specs:
                position = heat_positions.get(prova["id"], 0)
                heat_positions[prova["id"]] = position + 1
                h_index = position * LANES
                chosen = per_prova[prova["id"]][h_index : h_index + LANES]
                response = await client.post(
                    f"/api/heats/{heat['id']}/lanes",
                    json={
                        "lanes": [
                            {"lane_number": lane, "athlete_id": athlete["id"]}
                            for lane, athlete in enumerate(chosen, start=1)
                        ]
                    },
                )
                assert response.status_code == 200, response.text

            heats = (
                await client.get(f"/api/events/{event['id']}/heats")
            ).json()
            heats.sort(key=lambda item: item["event_seq"])
            assert [heat["event_seq"] for heat in heats] == list(
                range(1, TOTAL_HEATS + 1)
            )
            log(
                f"- {len(provas)} grupos (provas), {len(heats)} baterias, "
                f"{len(heats) * LANES} inscricoes"
            )
            log()

            # Percorre na ordem canonica, simulando as chegadas.
            traversed = []
            for heat in heats:
                opened = await client.post(
                    f"/api/heats/{heat['id']}/open-ready-check"
                )
                assert opened.status_code == 200, opened.text
                current = next(
                    item
                    for item in (
                        await client.get(
                            f"/api/provas/{heat['prova_id']}/heats"
                        )
                    ).json()
                    if item["id"] == heat["id"]
                )
                for lane in current["heat_lanes"]:
                    ready = await client.post(
                        f"/api/lanes/{lane['id']}/ready"
                    )
                    assert ready.status_code == 200, ready.text
                start = await client.post(f"/api/heats/{heat['id']}/start")
                assert start.status_code == 200, start.text
                await asyncio.sleep(0.01)
                for lane in reversed(current["heat_lanes"]):
                    finish = await client.post(
                        f"/api/lanes/{lane['id']}/finish"
                    )
                    assert finish.status_code == 200, finish.text
                await set_times(heat["id"], _planned_times(heat["event_seq"]))
                finished = next(
                    item
                    for item in (
                        await client.get(
                            f"/api/provas/{heat['prova_id']}/heats"
                        )
                    ).json()
                    if item["id"] == heat["id"]
                )
                assert finished["status"] == "finished", finished["status"]
                traversed.append(heat["event_seq"])

            assert traversed == list(range(1, TOTAL_HEATS + 1))
            log(
                f"- 50 baterias percorridas na ordem 1..{TOTAL_HEATS} "
                "(A1, A2, ... sem misturar provas)"
            )

            # Valida resumo e classificacao final de cada prova.
            total_valid = 0
            by_naipe_checked = 0
            for p, prova in enumerate(provas):
                summary = (
                    await client.get(
                        f"/api/provas/{prova['id']}/summary"
                    )
                ).json()
                expected_heats = _heats_for_prova(p)
                assert summary["heat_count"] == expected_heats
                assert summary["heats_finished"] == expected_heats
                assert summary["classification"]["is_provisional"] is False
                standings = summary["classification"]["standings"]
                expected_entries = expected_heats * LANES
                assert len(standings) == expected_entries, (
                    len(standings),
                    expected_entries,
                )
                times = [entry["race_time_ms"] for entry in standings]
                assert times == sorted(times)
                assert [entry["position"] for entry in standings][0] == 1
                total_valid += len(standings)
                if prova["naipe"] == "MISTO":
                    groups = summary["classification"]["standings_by_naipe"]
                    assert groups is not None
                    assert set(groups) == {"M", "F"}
                    for naipe in ("M", "F"):
                        entries = groups[naipe]
                        assert entries
                        assert entries[0]["position"] == 1
                        assert all(
                            entry["naipe"] == naipe for entry in entries
                        )
                        group_times = [
                            entry["race_time_ms"] for entry in entries
                        ]
                        assert group_times == sorted(group_times)
                    by_naipe_checked += 1
                log(
                    f"- Prova {p + 1} ({prova['naipe']}): "
                    f"{summary['heats_finished']}/{summary['heat_count']} "
                    f"baterias, {len(standings)} classificados"
                )

            assert total_valid == TOTAL_HEATS * LANES
            assert by_naipe_checked >= 1

    elapsed = time.perf_counter() - started
    log()
    log(
        f"OK — sequencia e classificacao validadas em {elapsed:.1f} s."
    )


if __name__ == "__main__":
    asyncio.run(main())
