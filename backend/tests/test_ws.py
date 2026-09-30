def _create_competition(ws_client, name="Prova WS"):
    response = ws_client.post(
        "/api/competition",
        json={"name": name, "duration_s": 3600, "meters_lap": 50},
    )
    assert response.status_code == 201, response.text
    state = ws_client.get("/api/competition/current")
    assert state.status_code == 200
    return state.json()["lanes"]


def test_ws_sends_initial_state(ws_client):
    with ws_client.websocket_connect("/ws") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "state"
        assert "competition" in message
        assert "lanes" in message


def test_ws_broadcasts_lap_and_state(ws_client):
    lanes = _create_competition(ws_client)
    lane_id = lanes[0]["id"]

    with ws_client.websocket_connect("/ws") as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "state"

        websocket.send_json({"type": "lap", "lane_id": lane_id})

        received = [websocket.receive_json(), websocket.receive_json()]

    types = [message["type"] for message in received]
    assert "lap" in types
    assert "state" in types

    lap_message = next(m for m in received if m["type"] == "lap")
    assert lap_message["lane_id"] == lane_id
    assert lap_message["laps"] == 1
    assert lap_message["meters"] == 50


def test_ws_undo(ws_client):
    lanes = _create_competition(ws_client)
    lane_id = lanes[0]["id"]

    with ws_client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "lap", "lane_id": lane_id})
        websocket.receive_json()
        websocket.receive_json()

        websocket.send_json({"type": "undo", "lane_id": lane_id})
        state = websocket.receive_json()

    assert state["type"] == "state"
    lane = next(item for item in state["lanes"] if item["id"] == lane_id)
    assert lane["laps"] == 0


def test_ws_unknown_type_returns_error(ws_client):
    with ws_client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "nao_existe"})
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["message"] == "tipo_desconhecido"
