"""Verificacao visual automatizada do telao (Playwright).

Uso:
    playwright install chromium   # uma vez
    python scripts/tv_check.py

Sobe uma instancia efemera do backend (SQLite temporario), semeia o evento
demo e percorre os estados do telao em 1920x1080, 1366x768 e 1280x720.
Falha se o palco rolar (`scrollHeight > clientHeight`), se algum elemento
sair do viewport ou se houver tabela vazia. As capturas ficam em
docs/screenshots/.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = Path(__file__).resolve().parent
for entry in (BACKEND, SCRIPTS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import seed_demo  # noqa: E402

VIEWPORTS = [(1920, 1080), (1366, 768), (1280, 720)]
SHOTS_DIR = ROOT / "docs" / "screenshots"
STATE_TIMEOUT_MS = 20000
PAUSE_MS = 400

CHECK_JS = """
() => {
  const stage = document.querySelector("#pub-stage");
  if (!stage) return { error: "sem palco" };
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const outside = [];
  for (const el of stage.querySelectorAll("*")) {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (Number(style.opacity) === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    if (
      rect.left < -1 ||
      rect.top < -1 ||
      rect.right > vw + 1 ||
      rect.bottom > vh + 1
    ) {
      outside.push(`${el.tagName}.${String(el.className).slice(0, 40)}`);
      if (outside.length >= 6) break;
    }
  }
  const emptyTables = [];
  for (const table of stage.querySelectorAll(".pub-table")) {
    if (!table.querySelector(".pub-trow")) emptyTables.push("pub-table");
  }
  for (const table of stage.querySelectorAll("table")) {
    if (!table.querySelector("tbody tr")) emptyTables.push("table");
  }
  for (const section of stage.querySelectorAll(".pub-section")) {
    if (!section.querySelector(".pub-trow")) emptyTables.push("section");
  }
  const pageLabel = stage.querySelector(".pub-foot-page");
  return {
    state: stage.dataset.state || "",
    scrollHeight: stage.scrollHeight,
    clientHeight: stage.clientHeight,
    outside,
    emptyTables,
    pageLabel: pageLabel ? pageLabel.textContent.trim() : "",
  };
}
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int):
    import uvicorn

    from app.main import app

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("o servidor nao iniciou")


def seed_events(base_url: str):
    import httpx

    async def run():
        async with httpx.AsyncClient(
            base_url=base_url, timeout=180
        ) as client:
            seeded = []
            for width, height in VIEWPORTS:
                label = f"{width}x{height}"
                demo = await seed_demo.build_demo(
                    client, event_name=f"Demo {label}"
                )
                waiting = await seed_demo.build_waiting_event(
                    client, event_name=f"Espera {label}"
                )
                seeded.append((demo, waiting))
            return seeded

    return asyncio.run(run())


def wait_state(page, name: str, timeout: int = STATE_TIMEOUT_MS) -> None:
    page.wait_for_selector(
        f'#pub-stage[data-state="{name}"]', timeout=timeout
    )


def check_state(page, expected: str, label: str, name: str) -> dict:
    page.wait_for_timeout(PAUSE_MS)
    report = page.evaluate(CHECK_JS)
    problems = []
    if report.get("error"):
        problems.append(report["error"])
    if report.get("state") != expected:
        problems.append(f"estado {report.get('state')} != {expected}")
    overflow = report.get("scrollHeight", 0) - report.get("clientHeight", 0)
    if overflow > 1:
        problems.append(
            f"palco rola {overflow}px "
            f"({report.get('scrollHeight')} > {report.get('clientHeight')})"
        )
    if report.get("outside"):
        problems.append(f"fora do viewport: {report['outside']}")
    if report.get("emptyTables"):
        problems.append(f"tabela vazia: {report['emptyTables']}")
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    shot = SHOTS_DIR / f"{label}-{name}.png"
    page.screenshot(path=str(shot), full_page=False)
    if problems:
        raise AssertionError(f"{label}/{name}: " + "; ".join(problems))
    return report


def check_sections(page, expected: int, label: str, name: str) -> None:
    count = len(page.query_selector_all("#pub-stage .pub-section"))
    if count != expected:
        raise AssertionError(
            f"{label}/{name}: {count} secoes renderizadas (esperado {expected})"
        )
    body = page.inner_text("#pub-stage")
    if expected == 1 and "Feminino" in body:
        raise AssertionError(
            f"{label}/{name}: prova sem naipe misto exibiu tabela Feminino"
        )


def collect_sections(
    page, expected: set[str], label: str, name: str, timeout_ms: int = 15000
) -> set[str]:
    seen: set[str] = set()
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        keys = page.eval_on_selector_all(
            "#pub-stage .pub-section",
            "els => els.map((el) => el.dataset.section)",
        )
        seen |= {key for key in keys if key}
        if expected.issubset(seen):
            return seen
        page.wait_for_timeout(120)
    raise AssertionError(
        f"{label}/{name}: secoes vistas {sorted(seen)} "
        f"(esperado {sorted(expected)})"
    )


def wait_page_change(page, previous: str, timeout_ms: int = 8000) -> str:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        node = page.query_selector(".pub-foot-page")
        label = node.inner_text() if node else ""
        if label and label != previous:
            return label
        page.wait_for_timeout(100)
    raise AssertionError("a pagina do telao nao rotacionou")


def check_all_pages(
    page, state: str, label: str, prefix: str, max_pages: int = 12
) -> None:
    report = check_state(page, state, label, f"{prefix}-pagina-1")
    current = report.get("pageLabel", "")
    total = 1
    if "/" in current:
        try:
            total = int(current.split("/")[1])
        except ValueError:
            total = 1
    for index in range(2, min(total, max_pages) + 1):
        current = wait_page_change(page, current)
        check_state(page, state, label, f"{prefix}-pagina-{index}")


def finish_lanes(api, heat_id: str, *, start: bool = False) -> None:
    if start:
        api.post(f"/api/heats/{heat_id}/open-ready-check").raise_for_status()
        heat = api.get(f"/api/heats/{heat_id}").json()
        for lane in heat["heat_lanes"]:
            api.post(f"/api/lanes/{lane['id']}/ready").raise_for_status()
        api.post(f"/api/heats/{heat_id}/start").raise_for_status()
        time.sleep(0.1)
    heat = api.get(f"/api/heats/{heat_id}").json()
    for lane in heat["heat_lanes"]:
        api.post(f"/api/lanes/{lane['id']}/finish").raise_for_status()


def run_viewport(browser, base_url: str, demo: dict, waiting: dict, size) -> None:
    import httpx

    width, height = size
    label = f"{width}x{height}"
    context = browser.new_context(
        viewport={"width": width, "height": height}
    )
    page = context.new_page()
    errors: list[str] = []
    page.on(
        "pageerror",
        lambda exc: errors.append(f"pageerror: {exc}"),
    )
    api = httpx.Client(base_url=base_url, timeout=60)

    try:
        page.goto(
            f"{base_url}/publico.html?event={waiting['event_id']}"
            "&preview=1&fast=1",
            wait_until="domcontentloaded",
        )
        wait_state(page, "waiting")
        check_state(page, "waiting", label, "01-espera")
        _, second_heat = waiting["heats"]
        api.patch(
            f"/api/events/{waiting['event_id']}/heats/order",
            json={"heat_id": second_heat, "position": 1},
        ).raise_for_status()
        page.wait_for_function(
            "() => (document.querySelector("
            "'#pub-stage .pub-up-item') || {})"
            ".textContent?.includes('100m')",
            timeout=10000,
        )
        first_after = page.inner_text("#pub-stage .pub-up-item")
        if "100m" not in first_after:
            raise AssertionError(
                f"{label}/01-espera: reordenacao nao refletiu ({first_after})"
            )

        page.goto(
            f"{base_url}/publico.html?event={demo['event_id']}"
            "&preview=1&fast=1",
            wait_until="domcontentloaded",
        )
        wait_state(page, "racing")
        check_state(page, "racing", label, "02-ao-vivo")

        finish_lanes(api, demo["active_heat_id"])
        wait_state(page, "heat_result")
        check_state(page, "heat_result", label, "03-resultado-bateria")

        wait_state(page, "interval")
        check_state(page, "interval", label, "04-intervalo")

        api.post(
            f"/api/heats/{demo['scheduled_heat_id']}/open-ready-check"
        ).raise_for_status()
        wait_state(page, "ready")
        check_state(page, "ready", label, "05-ready")

        finish_lanes(api, demo["scheduled_heat_id"], start=True)
        wait_state(page, "prova_result")
        report = check_state(
            page, "prova_result", label, "06-resultado-prova"
        )
        check_sections(page, 1, label, "06-resultado-prova")
        if "/" not in report.get("pageLabel", ""):
            raise AssertionError(
                f"{label}/06-resultado-prova: indicador de pagina ausente"
            )
        wait_page_change(page, report["pageLabel"])
        check_state(
            page, "prova_result", label, "06b-resultado-prova-pagina-2"
        )

        wait_state(page, "ended")
        check_all_pages(page, "ended", label, "07-encerrado")

        api.put(
            f"/api/events/{demo['event_id']}/presentation",
            json={
                "enabled": True,
                "rotation": True,
                "slide_duration_s": 15,
                "show_next_prova": True,
                "pinned_ref": f"prova:{demo['mixed_prova_id']}",
                "slides": [
                    {"kind": "prova", "target_id": demo["male_prova_id"]},
                    {"kind": "prova", "target_id": demo["mixed_prova_id"]},
                    {
                        "kind": "bateria",
                        "target_id": demo["active_heat_id"],
                    },
                ],
            },
        ).raise_for_status()
        wait_state(page, "slide")
        check_state(page, "slide", label, "08-slide-curado")
        collect_sections(
            page, {"overall", "M", "F"}, label, "08-slide-curado"
        )
        check_state(
            page, "slide", label, "08b-slide-curado-pagina-2"
        )

        if errors:
            raise AssertionError(f"{label}: erros JS: {errors}")
    finally:
        api.close()
        context.close()


def check_results_preview(browser, base_url: str, demo: dict) -> None:
    import httpx

    label = "resultados"
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    api = httpx.Client(base_url=base_url, timeout=60)
    try:
        before = api.get(
            f"/api/events/{demo['event_id']}/presentation"
        ).json()["pinned_ref"]
        page.goto(
            f"{base_url}/resultados.html?event={demo['event_id']}",
            wait_until="domcontentloaded",
        )
        page.wait_for_selector("#res-tv-preview")
        source = page.get_attribute("#res-tv-preview", "src")
        if "preview=1" not in (source or ""):
            raise AssertionError(f"{label}: iframe sem preview=1 ({source})")
        page.wait_for_selector("#res-tv-frame iframe")
        preview = page.frame_locator("#res-tv-preview")
        preview.locator("#pub-stage[data-state]").wait_for(timeout=20000)
        after_load = api.get(
            f"/api/events/{demo['event_id']}/presentation"
        ).json()["pinned_ref"]
        if after_load != before:
            raise AssertionError(
                f"{label}: preview alterou o estado do servidor"
            )

        page.click("#res-send-tv")
        page.wait_for_selector("#toast.show", timeout=10000)
        after_send = api.get(
            f"/api/events/{demo['event_id']}/presentation"
        ).json()["pinned_ref"]
        expected = f"prova:{demo['male_prova_id']}"
        if after_send != expected:
            raise AssertionError(
                f"{label}: pin apos enviar = {after_send} (esperado {expected})"
            )
        preview.locator('#pub-stage[data-state="slide"]').wait_for(
            timeout=20000
        )
        page.wait_for_timeout(600)
        if errors:
            raise AssertionError(f"{label}: erros JS: {errors}")
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS_DIR / f"{label}-previa-telao.png"))
    finally:
        api.close()
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep", action="store_true", help="mantem o banco temporario"
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright ausente. Rode: uv run --no-project --python 3.11 "
            "--with-requirements backend/requirements.txt "
            "--with-requirements backend/requirements-dev.txt "
            "python scripts/tv_check.py"
        )
        raise SystemExit(2)

    temp_dir = tempfile.mkdtemp(prefix="swimtimer_tv_")
    db_path = Path(temp_dir) / "tv.db"
    seed_demo.configure_env(db_path)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = start_server(port)

    try:
        seeded = seed_events(base_url)
        failures: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for (demo, waiting), size in zip(seeded, VIEWPORTS):
                    label = f"{size[0]}x{size[1]}"
                    print(f"… {label}")
                    try:
                        run_viewport(
                            browser, base_url, demo, waiting, size
                        )
                    except AssertionError as exc:
                        failures.append(str(exc))
                        print(f"  FALHOU: {exc}")
                    else:
                        print("  ok")
                if seeded:
                    print("… resultados (previa do telao)")
                    try:
                        check_results_preview(
                            browser, base_url, seeded[0][0]
                        )
                    except AssertionError as exc:
                        failures.append(str(exc))
                        print(f"  FALHOU: {exc}")
                    else:
                        print("  ok")
            finally:
                browser.close()
        if failures:
            print()
            for failure in failures:
                print(f"- {failure}")
            raise SystemExit(1)
        print()
        print(f"OK — {len(VIEWPORTS)} resolucoes, capturas em {SHOTS_DIR}")
    finally:
        server.should_exit = True
        if args.keep:
            print(f"Banco temporario: {db_path}")


if __name__ == "__main__":
    main()
