def _create_event(ws_client, name="Evento WS"):
    response = ws_client.post(
        "/api/events", json={"name": name, "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_heat(ws_client, event_id):
    response = ws_client.post(
        f"/api/events/{event_id}/provas",
        json={"name": "Bateria 1", "distance_m": 25},
    )
    assert response.status_code == 201, response.text
    prova = response.json()
    response = ws_client.post(
        f"/api/provas/{prova['id']}/heats",
        json={"name": "Bateria 1", "heat_type": "bateria", "distance_m": 25},
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
        for _ in range(10):
            message = websocket.receive_json()
            received.append(message)
            types = {item["type"] for item in received}
            if {"heat_state", "ready_update"} <= types:
                break

    types = {message["type"] for message in received}
    assert "heat_state" in types
    assert "ready_update" in types

    heat_state = next(
        message for message in received if message["type"] == "heat_state"
    )
    assert heat_state["scope"] == "heat"
    assert heat_state["heat_id"] == heat["id"]
    assert heat_state["payload"]["status"] == "ready_check"

    ready_update = next(
        message for message in received if message["type"] == "ready_update"
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
        assert error["message"] == "prova_nao_ativa"

        websocket.send_json({"type": "lap", "lane_id": lane_id})
        second = _recv_of_type(websocket, "error")
        assert second["message"] == "nao_e_maratona"


def test_ws_internal_error_keeps_connection(ws_client, monkeypatch):
    import app.main as main_module

    async def _boom(session, lane_id):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(main_module, "_do_finish", _boom)

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
    prova = ws_client.post(
        f"/api/events/{event['id']}/provas",
        json={"name": "100 Livres", "distance_m": 100},
    ).json()
    heat = ws_client.post(
        f"/api/provas/{prova['id']}/heats",
        json={"name": "Bateria 1", "heat_type": "bateria", "distance_m": 100},
    ).json()
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )
    current = ws_client.get(f"/api/provas/{prova['id']}/heats").json()[0]
    ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")
    ws_client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/ready")
    ws_client.post(f"/api/heats/{heat['id']}/start")

    with ws_client.websocket_connect("/ws") as websocket:
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
        message = _recv_matching(
            websocket, "heat_state", "heat_id", heat["id"]
        )
        assert message["payload"]["status"] == "active"
