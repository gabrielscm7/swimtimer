from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .. import database
from ..models import Event, Heat, Prova
from ..services import lane_actions
from ..services.broadcast import (
    _broadcast_server_status,
    _heat_state_message,
    _prova_state_message,
    manager,
)
from ..services.payloads import _heat_payload, _prova_payload

router = APIRouter()


async def _handle_ws_message(data: dict, websocket: WebSocket) -> None:
    message_type = data.get("type")
    if message_type == "ping":
        await manager.send_to(websocket, {"type": "pong"})
        return
    if message_type == "subscribe":
        event_id = data.get("event_id") or None
        public = bool(data.get("public"))
        event = None
        if event_id:
            async with database.AsyncSessionLocal() as session:
                event = await session.get(Event, event_id)
                if event is None:
                    await manager.send_to(
                        websocket,
                        {
                            "type": "error",
                            "message": "evento_nao_encontrado",
                        },
                    )
                    return
                name_mode = event.public_name_mode if public else None
                manager.subscribe(websocket, event_id, name_mode)
                await manager.send_to(
                    websocket, {"type": "subscribed", "event_id": event_id}
                )
                await _send_initial_state(session, websocket, event_id)
                return
        manager.subscribe(websocket, event_id)
        await manager.send_to(
            websocket, {"type": "subscribed", "event_id": event_id}
        )
        return
    if message_type == "finish":
        handler = lane_actions._do_finish
    elif message_type == "lap":
        handler = lane_actions._do_lap
    else:
        return

    op_id = data.get("op_id")
    lane_id = data.get("lane_id")
    if not lane_id:
        await manager.send_to(
            websocket,
            {"type": "error", "op_id": op_id, "message": "lane_id_ausente"},
        )
        return
    source_ip = websocket.client.host if websocket.client else None
    async with database.AsyncSessionLocal() as session:
        try:
            result = await handler(
                session,
                lane_id,
                op_id=op_id,
                client_ts=data.get("client_ts"),
                source_ip=source_ip,
            )
            await manager.send_to(
                websocket,
                {
                    "type": "ack",
                    "op_id": op_id,
                    "ok": True,
                    "result": result,
                },
            )
        except lane_actions.LaneActionError as exc:
            await session.rollback()
            await manager.send_to(
                websocket,
                {
                    "type": "error",
                    "op_id": op_id,
                    "message": exc.detail,
                    "lane_id": lane_id,
                },
            )
        except Exception:
            await session.rollback()
            await manager.send_to(
                websocket,
                {
                    "type": "error",
                    "op_id": op_id,
                    "message": "erro_interno",
                    "lane_id": lane_id,
                },
            )


async def _send_initial_state(
    session, websocket: WebSocket, event_id: str
) -> None:
    result = await session.execute(
        select(Heat)
        .where(
            Heat.event_id == event_id,
            Heat.status.in_(("ready_check", "active")),
        )
        .order_by(Heat.order_num)
    )
    active_heats = list(result.scalars().all())
    seen_provas: set[str] = set()
    for heat in active_heats:
        await manager.send_to(
            websocket,
            _heat_state_message(await _heat_payload(session, heat)),
        )
        if heat.prova_id in seen_provas:
            continue
        seen_provas.add(heat.prova_id)
        prova = await session.get(Prova, heat.prova_id)
        if prova is not None:
            await manager.send_to(
                websocket,
                _prova_state_message(await _prova_payload(session, prova)),
            )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await _broadcast_server_status()
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception:
                await manager.send_to(
                    websocket, {"type": "error", "message": "mensagem_invalida"}
                )
                continue
            try:
                await _handle_ws_message(data, websocket)
            except Exception:
                await manager.send_to(
                    websocket, {"type": "error", "message": "erro_interno"}
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await _broadcast_server_status()
    except Exception:
        manager.disconnect(websocket)
        await _broadcast_server_status()
