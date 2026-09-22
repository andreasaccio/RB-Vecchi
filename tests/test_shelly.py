from unittest.mock import Mock

from rbvecchi.shelly import ShellyClient


def response(payload):
    obj = Mock()
    obj.raise_for_status.return_value = None
    obj.json.return_value = payload
    return obj


def test_get_status_parses_gen3_payload() -> None:
    client = ShellyClient("http://192.168.1.100", "admin", "")
    client.session.get = Mock(return_value=response({
        "input:0": {"id": 0, "state": True},
        "switch:0": {"id": 0, "output": False, "temperature": {"tC": 42.5}},
        "wifi": {"rssi": -58},
        "sys": {"uptime": 12345},
    }))

    status = client.get_status()
    assert status.raw_input_state is True
    assert status.relay_output is False
    assert status.wifi_rssi == -58
    assert status.uptime_seconds == 12345
    assert status.temperature_c == 42.5


def test_pulse_uses_toggle_after() -> None:
    client = ShellyClient("http://192.168.1.100", "admin", "")
    client.session.post = Mock(return_value=response({"was_on": False}))

    client.pulse_relay(0.7)
    _, kwargs = client.session.post.call_args
    assert kwargs["json"]["id"] == 0
    assert kwargs["json"]["on"] is True
    assert kwargs["json"]["toggle_after"] == 0.7
