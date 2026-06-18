from fastapi.testclient import TestClient

from plugins.yangyang.webui.web_api import configure_webui, web_app


class FakeConfig:
    def get(self, path, default=None):
        values = {
            "dry_run": True,
            "owner_toolbox_light_native_loop_enabled": True,
            "owner_toolbox_light_native_loop_max_steps": 7,
            "model_profile_switcher": {"private_active": "v4_flash"},
        }
        return values.get(path, default)

    def get_bool(self, path, default=False):
        return bool(self.get(path, default))


client = TestClient(web_app)


def setup_module():
    configure_webui(config_provider=lambda: FakeConfig(), auth_token_provider=lambda: "x" * 32)


def test_ping_localhost_ok():
    response = client.get("/api/ping", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_dashboard_ok():
    response = client.get("/api/dashboard", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["data"]["owner_toolbox_max_steps"] == 7


def test_no_write_routes_registered():
    methods = set()
    for route in web_app.routes:
        methods.update(getattr(route, "methods", set()) or set())
    assert not ({"POST", "PUT", "DELETE", "PATCH"} & methods)
