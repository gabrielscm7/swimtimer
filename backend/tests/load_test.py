"""Teste de carga manual (nao e coletado pelo pytest).

Uso:
    python tests/load_test.py

Cria um banco temporario, popula eventos/provas/baterias/equipes e mede o
tempo de resposta dos endpoints principais e a concorrencia de finalizacao.
Os numeros sao reais da execucao (sem estimativas) e podem variar por maquina.
"""
import asyncio
import json
import os
import platform
import statistics
import sys
import tempfile
import time

N_PROVAS = int(os.environ.get("LOAD_PROVAS", "8"))
TOTAL_HEATS = int(os.environ.get("LOAD_TOTAL_HEATS", "50"))
LANES = int(os.environ.get("LOAD_LANES", "8"))
TEAMS = int(os.environ.get("LOAD_TEAMS", "8"))
ATHLETES = int(os.environ.get("LOAD_ATHLETES", "150"))


def _heats_for_prova(index: int) -> int:
    """Distribui o total de baterias entre as provas (ex.: 50 em 8)."""
    base, remainder = divmod(TOTAL_HEATS, N_PROVAS)
    return base + (1 if index < remainder else 0)


async def _time(coro):
    start = time.perf_counter()
    result = await coro
    return (time.perf_counter() - start) * 1000.0, result


async def main() -> None:
    tmp = tempfile.mkdtemp(prefix="swimtimer_load_")
    db = os.path.join(tmp, "load.db")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    os.environ["LOGO_DIR"] = os.path.join(tmp, "logos")
    os.environ["THEME_DIR"] = os.path.join(tmp, "theme")

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    lines = []
    def log(text=""):
        print(text)
        lines.append(text)

    log("# Resultado do teste de carga — SwimTimer")
    log()
    log(f"- Data: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"- Python: {sys.version.split()[0]}")
    log(f"- Plataforma: {platform.platform()}")
    log(f"- SQLite: {__import__('sqlite3').sqlite_version}")
    log(
        f"- Massa: {N_PROVAS} provas x {TOTAL_HEATS} baterias x "
        f"{LANES} raias = {TOTAL_HEATS * LANES} raias; "
        f"{TEAMS} equipes; {ATHLETES} atletas importados"
    )
    log()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://load") as client:
            event = (
                await client.post(
                    "/api/events",
                    json={"name": "Carga", "pool_length_m": 25},
                )
            ).json()
            teams = []
            for index in range(TEAMS):
                response = await client.post(
                    f"/api/events/{event['id']}/teams",
                    json={"name": f"Equipe {index + 1}"},
                )
                teams.append(response.json())

            rows = ["NOME,EQUIPE,NAIPE,CATEGORIA"]
            for index in range(ATHLETES):
                rows.append(
                    f"Atleta {index:03d},Equipe {index % TEAMS + 1},"
                    f"{'M' if index % 2 == 0 else 'F'},SUB-12"
                )
            csv_content = ("\n".join(rows) + "\n").encode("utf-8")

            import_start = time.perf_counter()
            import_response = await client.post(
                f"/api/events/{event['id']}/athletes/import",
                files={"file": ("atletas.csv", csv_content, "text/csv")},
            )
            import_ms = (time.perf_counter() - import_start) * 1000
            import_body = import_response.json()
            log("## Importacao de atletas")
            log(
                f"- {import_body['created_athletes']} atletas e "
                f"{import_body['created_teams']} equipes em {import_ms:.0f} ms "
                f"({import_ms / max(1, ATHLETES):.2f} ms/atleta), "
                f"{len(import_body['errors'])} erros"
            )

            read_durations = []
            for offset in range(0, ATHLETES, 50):
                elapsed, response = await _time(
                    client.get(
                        f"/api/events/{event['id']}/athletes",
                        params={"limit": 50, "offset": offset},
                    )
                )
                assert response.status_code == 200, response.text
                read_durations.append(elapsed)
            filtered = await client.get(
                f"/api/events/{event['id']}/athletes",
                params={"naipe": "F", "category": "SUB-12", "limit": 50},
            )
            log(
                f"- listagem paginada: mediana {statistics.median(read_durations):.1f} ms, "
                f"max {max(read_durations):.1f} ms; total filtrado "
                f"{filtered.json()['total']}"
            )
            log()

            setup_start = time.perf_counter()
            provas = []
            for p in range(N_PROVAS):
                prova = (
                    await client.post(
                        f"/api/events/{event['id']}/provas",
                        json={
                            "name": f"Prova {p + 1}",
                            "distance_m": 100,
                            "stroke": "livre",
                        },
                    )
                ).json()
                provas.append(prova)
                heats_here = _heats_for_prova(p)
                for h in range(heats_here):
                    heat = (
                        await client.post(
                            f"/api/provas/{prova['id']}/heats",
                            json={
                                "name": f"Bateria {h + 1}",
                                "heat_type": "bateria",
                                "distance_m": 100,
                            },
                        )
                    ).json()
                    lanes = []
                    for lane_number in range(1, LANES + 1):
                        lanes.append(
                            {
                                "lane_number": lane_number,
                                "participant_name": (
                                    f"Atleta P{p + 1} B{h + 1} R{lane_number}"
                                ),
                                "team_id": teams[
                                    (p * TOTAL_HEATS + h) % len(teams)
                                ]["id"],
                            }
                        )
                    await client.post(
                        f"/api/heats/{heat['id']}/lanes", json={"lanes": lanes}
                    )
            setup_ms = (time.perf_counter() - setup_start) * 1000
            total_heats = TOTAL_HEATS
            log("## Criacao de dados")
            log(
                f"- {total_heats} baterias + {total_heats * LANES} raias em "
                f"{setup_ms:.0f} ms ({setup_ms / total_heats:.1f} ms/bateria)"
            )
            log()

            log("## Endpoints de leitura")
            for label, path in [
                ("GET /api/events", "/api/events"),
                ("GET /api/events/{id}", f"/api/events/{event['id']}"),
                ("GET /api/events/{id}/provas", f"/api/events/{event['id']}/provas"),
                ("GET /api/provas/{id}", f"/api/provas/{provas[0]['id']}"),
                (
                    "GET /api/provas/{id}/heats",
                    f"/api/provas/{provas[0]['id']}/heats",
                ),
                (
                    "GET /api/provas/{id}/classification",
                    f"/api/provas/{provas[0]['id']}/classification",
                ),
                (
                    "GET /api/provas/{id}/summary",
                    f"/api/provas/{provas[0]['id']}/summary",
                ),
            ]:
                durations = []
                size = 0
                for _ in range(5):
                    elapsed, response = await _time(client.get(path))
                    durations.append(elapsed)
                    size = len(response.content)
                log(
                    f"- {label}: mediana {statistics.median(durations):.1f} ms, "
                    f"min {min(durations):.1f} ms, max {max(durations):.1f} ms, "
                    f"{size / 1024:.1f} KB"
                )
            log()

            log(f"## Concorrencia ({_heats_for_prova(0)} baterias da prova 1)")
            active = []
            for heat in (
                await client.get(f"/api/provas/{provas[0]['id']}/heats")
            ).json():
                await client.post(f"/api/heats/{heat['id']}/open-ready-check")
                current = (
                    await client.get(f"/api/provas/{provas[0]['id']}/heats")
                ).json()
                current = next(item for item in current if item["id"] == heat["id"])
                for lane in current["heat_lanes"]:
                    await client.post(f"/api/lanes/{lane['id']}/ready")
                await client.post(f"/api/heats/{heat['id']}/start")
                active.append(current)
            await asyncio.sleep(0.05)

            finish_calls = [
                client.post(f"/api/lanes/{lane['id']}/finish")
                for heat in active
                for lane in heat["heat_lanes"]
            ]
            start = time.perf_counter()
            responses = await asyncio.gather(*finish_calls)
            elapsed = (time.perf_counter() - start) * 1000
            ok = sum(1 for response in responses if response.status_code == 200)
            log(
                f"- {len(finish_calls)} finalizacoes simultaneas: {ok} aceitas, "
                f"{elapsed:.0f} ms no total ({elapsed / len(finish_calls):.1f} ms/req)"
            )

            classification = (
                await client.get(
                    f"/api/provas/{provas[0]['id']}/classification"
                )
            ).json()
            log(
                f"- classificacao consolidada: {len(classification['standings'])}"
                f" validos, {len(classification['excluded'])} excluidos, "
                f"provisoria={classification['is_provisional']}"
            )
            log()

            log("## Limites observados")
            log(
                "- Teste in-process (ASGI), sem latencia de rede Wi-Fi; numeros "
                "servem para comparar regressoes, nao como garantia de producao."
            )
            log(
                "- SQLite em WAL com um unico worker uvicorn: escritas sao "
                "serializadas; os locks por bateria evitam corrida no processo."
            )
            log(
                "- Multiplos workers exigiriam banco com concorrencia de escrita "
                "(PostgreSQL) ou particionamento; ver docs/ADR/005."
            )

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..",
        "docs",
        "audit",
    )
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "load_results.md")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"\nRelatorio salvo em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
