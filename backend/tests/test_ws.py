def _create_event(ws_client, name="Evento WS"):
    response = ws_client.post(
        "/api/events", json={"name": name, "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_heat(ws_client, event_id):
    response = ws_client.post(
        f"/api/events/{event_id}/heats",
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

        received = [websocket.receive_json(), websocket.receive_json()]

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
