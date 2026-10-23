import csv
import hashlib
import html
import io
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Event, Heat, Prova
from . import journal
from .backup import _copy_database, db_file_path
from .payloads import _classification_payload, _prova_heats
from .snapshots import latest_by_heat, snapshot_summary

CSV_HEADER = [
    "prova",
    "bateria",
    "raia",
    "atleta",
    "equipe",
    "tempo",
    "status",
    "revisao",
    "oficial",
]


async def _event_entries(
    session: AsyncSession, event: Event
) -> tuple[list[dict], dict[str, object]]:
    result = await session.execute(
        select(Prova).where(Prova.event_id == event.id).order_by(Prova.order_num)
    )
    provas = list(result.scalars().all())
    latest = await latest_by_heat(session, event.id)
    rows: list[dict] = []
    for prova in provas:
        classification = await _classification_payload(session, prova)
        heats = await _prova_heats(session, prova.id)
        for heat in heats:
            snapshot = latest.get(heat.id)
            entries = next(
                (
                    item["entries"]
                    for item in classification["battery_results"]
                    if item["heat_id"] == heat.id
                ),
                [],
            )
            for entry in entries:
                rows.append(
                    {
                        "prova": prova.name,
                        "bateria": heat.name,
                        "raia": entry["lane_number"],
                        "atleta": entry.get("participant_name") or "",
                        "equipe": entry.get("team_name") or "",
                        "tempo": entry.get("race_time_display") or "",
                        "status": entry.get("status") or "",
                        "revisao": snapshot.revision if snapshot else "",
                        "oficial": (
                            "sim"
                            if snapshot and snapshot.status == "official"
                            else "nao"
                        ),
                        "heat": heat,
                        "prova_obj": prova,
                        "snapshot": snapshot,
                    }
                )
    return rows, latest


async def build_results_csv(session: AsyncSession, event: Event) -> str:
    rows, _latest = await _event_entries(session, event)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(
            [
                row["prova"],
                row["bateria"],
                row["raia"],
                row["atleta"],
                row["equipe"],
                row["tempo"],
                row["status"],
                row["revisao"],
                row["oficial"],
            ]
        )
    return "\ufeff" + buffer.getvalue()


def _slug(value: str) -> str:
    keep = [char if char.isalnum() else "-" for char in value.lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "bateria"


async def render_sumula_html(
    session: AsyncSession,
    heat: Heat,
    *,
    prova: Prova | None = None,
    event: Event | None = None,
    snapshot=None,
) -> str:
    """Sumula imprimivel (nome completo, independente do modo publico)."""
    if prova is None:
        prova = await session.get(Prova, heat.prova_id)
    if event is None:
        event = await session.get(Event, heat.event_id)
    if snapshot is None:
        latest = await latest_by_heat(session, heat.event_id)
        snapshot = latest.get(heat.id)

    classification = (
        await _classification_payload(session, prova)
        if prova is not None
        else {"battery_results": []}
    )
    entries = next(
        (
            item["entries"]
            for item in classification["battery_results"]
            if item["heat_id"] == heat.id
        ),
        [],
    )
    summary = snapshot_summary(snapshot)
    revision = summary["revision"] if summary else "-"
    status = summary["status"] if summary else "sem-revisao"
    badge = {"official": "OFICIAL", "corrected": "RETIFICADO"}.get(
        status, "PROVISORIO"
    )

    rows = "".join(
        "<tr>"
        f"<td>{entry['lane_number']}</td>"
        f"<td>{html.escape(entry.get('participant_name') or '-')}</td>"
        f"<td>{html.escape(entry.get('team_name') or '-')}</td>"
        f"<td>{html.escape(entry.get('race_time_display') or '-')}</td>"
        f"<td>{html.escape(entry.get('status') or '-')}</td>"
        "</tr>"
        for entry in entries
    )
    event_name = html.escape(event.name) if event else ""
    prova_name = html.escape(prova.name) if prova else ""
    heat_name = html.escape(heat.name)
    printed_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Sumula - {prova_name} - {heat_name}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  h2 {{ font-size: 14px; margin: 0 0 16px; font-weight: normal; }}
  .meta {{ display: flex; gap: 24px; font-size: 12px; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ border: 1px solid #444; padding: 6px; text-align: left; }}
  th {{ background: #eee; }}
  .badge {{ font-weight: bold; }}
  .signatures {{ display: flex; gap: 40px; margin-top: 48px; font-size: 12px; }}
  .signatures div {{ border-top: 1px solid #444; padding-top: 4px; width: 220px; }}
  @media print {{
    body {{ margin: 12mm; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
<h1>{event_name} - {prova_name}</h1>
<h2>{heat_name} &middot; <span class="badge">{badge}</span>
 &middot; revisao {revision}</h2>
<div class="meta">
  <span>Status: {html.escape(heat.status)}</span>
  <span>Distancia: {heat.distance_m or '-'} m</span>
  <span>Impresso em: {printed_at}</span>
</div>
<table>
<thead><tr><th>Raia</th><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<div class="signatures">
  <div>Arbitro</div><div>Mesario</div>
</div>
</body>
</html>
"""


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def build_bundle(session: AsyncSession, event: Event) -> bytes:
    rows, _latest = await _event_entries(session, event)
    files: list[tuple[str, bytes]] = []

    db_path = db_file_path()
    if db_path is not None and db_path.is_file():
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "swimtimer.db"
            _copy_database(db_path, copy)
            files.append(("backup/swimtimer.db", copy.read_bytes()))

    files.append(
        (
            "results.csv",
            (await build_results_csv(session, event)).encode("utf-8"),
        )
    )

    seen: set[str] = set()
    for row in rows:
        heat = row["heat"]
        if heat.id in seen:
            continue
        seen.add(heat.id)
        content = await render_sumula_html(
            session,
            heat,
            prova=row["prova_obj"],
            event=event,
            snapshot=row["snapshot"],
        )
        name = (
            f"sumulas/{(row['prova_obj'].order_num if row['prova_obj'] else 0):02d}"
            f"_{heat.order_num:02d}_{_slug(heat.name)}.html"
        )
        files.append((name, content.encode("utf-8")))

    journal_file = journal.journal_path(event.id)
    if journal_file.is_file():
        files.append((f"journal/{event.id}.ndjson", journal_file.read_bytes()))

    manifest_lines = [
        f"{_sha256_bytes(content)}  {name}" for name, content in files
    ]
    files.append(
        ("manifest.sha256", "\n".join(manifest_lines).encode("utf-8") + b"\n")
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files:
            bundle.writestr(name, content)
    return buffer.getvalue()
