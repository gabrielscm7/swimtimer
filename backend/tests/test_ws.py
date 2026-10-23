def _create_event(ws_client, name="Evento WS"):
    response = ws_client.post(
        "/api/events", json={"name": name, "date": "2026-10-23", "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_heat(ws_client, event_id):
    response = ws_client.post(
        f"/api/events/{event_id}/heats",
        json={
            "heat_type": "bateria",
            "stroke": "livre",
            "distance_m": 25,
            "naipe": "MISTO",
            "category": "livre",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ws_sends_server_status(ws_client):
    with ws_client.websocket_connect("/ws") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "server_status"
        assert message["scope"] == "home"
        assert "connected" in message["payload"]
        assert "active_heats" in message["payload"]


def test_ws_broadcasts_scoped_messages(ws_client):
    event = _create_event(ws_client)
    heat = _create_heat(ws_client, event["id"])
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )

    with ws_client.websocket_connect("/ws") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "server_status"

        ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")

        received = []
        for _ in range(50):
            message = websocket.receive_json()
            received.append(message)
            relevant = {
                item["type"]
                for item in received
                if item.get("heat_id") == heat["id"]
            }
            if {"heat_state", "ready_update"} <= relevant:
                break

    heat_state = next(
        message
        for message in received
        if message["type"] == "heat_state"
        and message.get("heat_id") == heat["id"]
    )
    assert heat_state["scope"] == "heat"
    assert heat_state["payload"]["status"] == "ready_check"

    ready_update = next(
        message
        for message in received
        if message["type"] == "ready_update"
        and message.get("heat_id") == heat["id"]
    )
    assert ready_update["scope"] == "heat"
    assert ready_update["payload"]["lanes_pending"] == [1]
    assert ready_update["payload"]["all_ready"] is False


def _recv_of_type(websocket, wanted, limit=50):
    """Consome mensagens até encontrar o tipo desejado (ignora broadcasts
    iniciais de heat_state de provas ativas deixadas por outros testes)."""
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"não recebeu mensagem do tipo {wanted}")


def _recv_matching(websocket, wanted, key, value, limit=200):
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == wanted and message.get(key) == value:
            return message
    raise AssertionError(f"não recebeu {wanted} com {key}={value}")


def test_ws_action_error_keeps_connection(ws_client):
    event = _create_event(ws_client, name="Evento WS erro")
    heat = _create_heat(ws_client, event["id"])
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )
    heat = ws_client.get(f"/api/events/{event['id']}/heats").json()[0]
    lane_id = heat["heat_lanes"][0]["id"]

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")

        websocket.send_json({"type": "finish", "lane_id": lane_id})
        error = _recv_of_type(websocket, "error")
        assert error["message"] == "bateria_nao_ativa"

        websocket.send_json({"type": "lap", "lane_id": lane_id})
        second = _recv_of_type(websocket, "error")
        assert second["message"] == "nao_e_maratona"


def test_ws_internal_error_keeps_connection(ws_client, monkeypatch):
    from app.services import lane_actions

    async def _boom(session, lane_id, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(lane_actions, "_do_finish", _boom)

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")

        websocket.send_json({"type": "finish", "lane_id": "qualquer"})
        error = _recv_of_type(websocket, "error")
        assert error["message"] == "erro_interno"

        websocket.send_json({"type": "finish", "lane_id": "qualquer"})
        again = _recv_of_type(websocket, "error")
        assert again["message"] == "erro_interno"


def test_ws_sends_prova_state_on_connect(ws_client):
    event = _create_event(ws_client, name="Evento WS prova")
    heat = ws_client.post(
        f"/api/events/{event['id']}/heats",
        json={
            "heat_type": "bateria",
            "stroke": "livre",
            "distance_m": 100,
            "naipe": "MISTO",
            "category": "livre",
        },
    ).json()
    prova = ws_client.get(f"/api/provas/{heat['prova_id']}").json()
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )
    current = ws_client.get(f"/api/heats/{heat['id']}").json()
    ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")
    ws_client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/ready")
    ws_client.post(f"/api/heats/{heat['id']}/start")

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json(
            {"type": "subscribe", "event_id": event["id"]}
        )
        _recv_of_type(websocket, "subscribed")
        state = _recv_matching(
            websocket, "prova_state", "prova_id", prova["id"]
        )
        assert state["scope"] == "prova"
        assert state["payload"]["id"] == prova["id"]
        assert state["payload"]["status"] == "in_progress"
        assert state["payload"]["heat_count"] == 1


def test_ws_reconnect_recovers_active_state(ws_client):
    event = _create_event(ws_client, name="Evento WS reconexao")
    heat = _create_heat(ws_client, event["id"])
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )
    current = ws_client.get(f"/api/events/{event['id']}/heats").json()[0]
    ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")
    ws_client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/ready")
    ws_client.post(f"/api/heats/{heat['id']}/start")

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json(
            {"type": "subscribe", "event_id": event["id"]}
        )
        _recv_of_type(websocket, "subscribed")
        message = _recv_matching(
            websocket, "heat_state", "heat_id", heat["id"]
        )
        assert message["payload"]["status"] == "active"


def test_ws_messages_carry_event_id(ws_client):
    event = _create_event(ws_client, name="Evento WS event_id")
    heat = _create_heat(ws_client, event["id"])
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")

        found = {}
        for _ in range(80):
            message = websocket.receive_json()
            if (
                message.get("type") == "heat_state"
                and message.get("heat_id") == heat["id"]
            ):
                found.setdefault("heat_state", message)
            elif (
                message.get("type") == "ready_update"
                and message.get("heat_id") == heat["id"]
            ):
                found.setdefault("ready_update", message)
            elif (
                message.get("type") == "prova_state"
                and message.get("prova_id") == heat["prova_id"]
            ):
                found.setdefault("prova_state", message)
            if len(found) == 3:
                break

        assert set(found) == {"heat_state", "ready_update", "prova_state"}
        assert found["heat_state"]["event_id"] == event["id"]
        assert found["heat_state"]["payload"]["event_id"] == event["id"]
        assert found["ready_update"]["event_id"] == event["id"]
        assert found["prova_state"]["event_id"] == event["id"]


def test_ws_subscribe_filters_other_events(ws_client):
    event_a = _create_event(ws_client, name="Evento WS A")
    heat_a = _create_heat(ws_client, event_a["id"])
    event_b = _create_event(ws_client, name="Evento WS B")
    heat_b = _create_heat(ws_client, event_b["id"])

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json(
            {"type": "subscribe", "event_id": event_a["id"]}
        )
        subscribed = _recv_of_type(websocket, "subscribed")
        assert subscribed["event_id"] == event_a["id"]

        ws_client.post(f"/api/heats/{heat_b['id']}/open-ready-check")
        ws_client.post(f"/api/heats/{heat_a['id']}/open-ready-check")

        received = []
        for _ in range(80):
            message = websocket.receive_json()
            received.append(message)
            if (
                message.get("type") == "heat_state"
                and message.get("heat_id") == heat_a["id"]
            ):
                break

        assert any(
            message.get("type") == "heat_state"
            and message.get("heat_id") == heat_a["id"]
            for message in received
        )
        assert all(
            message.get("heat_id") != heat_b["id"] for message in received
        )
        assert all(
            message.get("event_id") != event_b["id"]
            for message in received
        )


def test_ws_without_subscribe_receives_all_events(ws_client):
    event_a = _create_event(ws_client, name="Evento WS tudo A")
    heat_a = _create_heat(ws_client, event_a["id"])
    event_b = _create_event(ws_client, name="Evento WS tudo B")
    heat_b = _create_heat(ws_client, event_b["id"])

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        ws_client.post(f"/api/heats/{heat_a['id']}/open-ready-check")
        ws_client.post(f"/api/heats/{heat_b['id']}/open-ready-check")

        seen = set()
        for _ in range(120):
            message = websocket.receive_json()
            if message.get("type") == "heat_state":
                seen.add(message.get("heat_id"))
            if {heat_a["id"], heat_b["id"]} <= seen:
                break
        assert {heat_a["id"], heat_b["id"]} <= seen


def test_ws_subscribe_unknown_event_errors(ws_client):
    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json(
            {"type": "subscribe", "event_id": "inexistente"}
        )
        error = _recv_of_type(websocket, "error")
        assert error["message"] == "evento_nao_encontrado"


def test_settings_updated_broadcast(ws_client):
    event = _create_event(ws_client, name="Evento WS settings")
    with ws_client.websocket_connect("/ws") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "server_status"
        websocket.send_json({"type": "subscribe", "event_id": event["id"]})
        assert websocket.receive_json()["type"] == "subscribed"
        response = ws_client.patch(
            f"/api/events/{event['id']}",
            json={"public_name_mode": "initials"},
        )
        assert response.status_code == 200, response.text

        message = None
        for _ in range(30):
            candidate = websocket.receive_json()
            if candidate.get("type") == "settings_updated":
                message = candidate
                break
        assert message is not None
        assert message["scope"] == "event"
        assert message["event_id"] == event["id"]
        assert message["payload"]["public_name_mode"] == "initials"
