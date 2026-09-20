"""Client/server contract checks for device-bound auth and file change cursors."""

from types import SimpleNamespace
from unittest.mock import patch

from core.cloud_api import CloudAPIClient
from core.cloud.http import HttpClient


class _Response:
    status_code = 200

    def json(self):
        return {"token": "access", "refresh_token": "refresh"}


def test_login_and_register_bind_refresh_session_to_current_device():
    client = CloudAPIClient("https://example.com")
    try:
        with patch("core.cloud.auth_client.settings", return_value=SimpleNamespace(device_id="desktop-7")), \
             patch.object(client, "_request", return_value=_Response()) as request, \
             patch.object(client._http, "_handle_auth_response"):
            client.login("a@example.com", "password")
            assert request.call_args.kwargs["json"]["device_id"] == "desktop-7"
            client.register("b@example.com", "password")
            assert request.call_args.kwargs["json"]["device_id"] == "desktop-7"
    finally:
        client.close()


def test_refresh_preserves_device_binding_in_request():
    http = HttpClient("https://example.com")
    old_client = http._client
    old_client.close()

    class Transport:
        request = None

        def post(self, path, json, timeout):
            self.request = (path, json, timeout)
            return _Response()

    transport = Transport()
    http._client = transport
    http.set_tokens("old-access", "old-refresh")
    with patch("core.cloud.http.settings", return_value=SimpleNamespace(device_id="desktop-7")), \
         patch.object(http, "_apply_refresh_response", return_value=True):
        assert http.refresh_token()
    assert transport.request[0] == "/api/v1/auth/refresh"
    assert transport.request[1] == {
        "refresh_token": "old-refresh", "device_id": "desktop-7",
    }


def test_file_events_use_new_cursor_while_legacy_call_stays_compatible():
    client = CloudAPIClient("https://example.com")
    try:
        with patch.object(client, "_request", return_value=_Response()) as request:
            client.files_list(device_id="desktop-7", since_change_id=23)
            assert request.call_args.kwargs["params"] == {
                "device_id": "desktop-7", "limit": 100, "since_change_id": 23,
            }
            client.files_list(42, "desktop-7")
            assert request.call_args.kwargs["params"] == {
                "device_id": "desktop-7", "limit": 100, "since_id": 42,
            }
    finally:
        client.close()
