from plugins.yangyang.webui.security import REDACTED, check_auth, is_localhost, redact_mapping


def test_localhost_auth_allowed_without_token():
    assert check_auth(client_host="127.0.0.1", authorization_header=None, expected_token=None)[0]
    assert check_auth(client_host="::1", authorization_header=None, expected_token=None)[0]


def test_remote_requires_token():
    assert not check_auth(client_host="10.0.0.1", authorization_header=None, expected_token=None)[0]
    assert not check_auth(client_host="10.0.0.1", authorization_header="Basic abc", expected_token="x" * 32)[0]
    assert check_auth(client_host="10.0.0.1", authorization_header="Bearer " + "x" * 32, expected_token="x" * 32)[0]


def test_redact_mapping_keys_and_values():
    data = {"OPENAI_API_KEY": "fake" + "_secret", "nested": {"base_url": "https://example.invalid"}, "safe": "ok"}
    out = redact_mapping(data)
    assert out["OPENAI_API_KEY"] == REDACTED
    assert out["nested"]["base_url"] == REDACTED
    assert out["safe"] == "ok"


def test_redact_mapping_sensitive_value():
    out = redact_mapping({"message": "Bearer " + "a" * 16})
    assert out["message"] == REDACTED
