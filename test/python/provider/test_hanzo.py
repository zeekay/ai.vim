import json
import socket
from pathlib import Path

import pytest

from neural.provider import hanzo


def _write(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _clear_cloud_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "HANZO_API_KEY",
        "HANZO_LLM_GATEWAY",
    ):
        monkeypatch.delenv(var, raising=False)


def _closed_port() -> int:
    """Return a localhost port that is bound then released, so closed."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()

    return port


def _always_up(_url: str, timeout: float = 0.7) -> bool:
    return True


def _always_down(_url: str, timeout: float = 0.7) -> bool:
    return False


def test_anthropic_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")

    assert hanzo.resolve_shared_credential("anthropic") == "sk-ant-xxx"


def test_openai_reads_codex_oauth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _write(
        tmp_path / ".codex" / "auth.json",
        {"tokens": {"access_token": "oai-access-token"}},
    )

    token = hanzo.resolve_shared_credential("openai", str(tmp_path))

    assert token == "oai-access-token"


def test_openai_reads_codex_api_key_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _write(
        tmp_path / ".codex" / "auth.json",
        {"auth_mode": "apikey", "OPENAI_API_KEY": "sk-openai"},
    )

    token = hanzo.resolve_shared_credential("openai", str(tmp_path))

    assert token == "sk-openai"


def test_hanzo_reads_auth_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HANZO_API_KEY", raising=False)
    _write(
        tmp_path / ".hanzo" / "auth.json",
        {"auth_mode": "apikey", "OPENAI_API_KEY": "hanzo-iam-token"},
    )

    token = hanzo.resolve_shared_credential("hanzo", str(tmp_path))

    assert token == "hanzo-iam-token"


def test_env_beats_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HANZO_API_KEY", "env-wins")
    _write(
        tmp_path / ".hanzo" / "auth.json",
        {"OPENAI_API_KEY": "file-loses"},
    )

    token = hanzo.resolve_shared_credential("hanzo", str(tmp_path))

    assert token == "env-wins"


def test_nothing_resolves_no_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HANZO_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    assert hanzo.resolve_shared_credential("anthropic", str(tmp_path)) == ""
    assert hanzo.resolve_shared_credential("openai", str(tmp_path)) == ""
    assert hanzo.resolve_shared_credential("hanzo", str(tmp_path)) == ""
    assert hanzo.resolve_shared_credential("google", str(tmp_path)) == ""


@pytest.mark.parametrize(
    ("provider", "key", "expected"),
    [
        pytest.param(
            "anthropic",
            "sk-ant",
            {
                "Content-Type": "application/json",
                "x-api-key": "sk-ant",
                "anthropic-version": hanzo.ANTHROPIC_VERSION,
            },
            id="anthropic",
        ),
        pytest.param(
            "openai",
            "sk-oai",
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer sk-oai",
            },
            id="openai",
        ),
        pytest.param(
            "hanzo",
            "tok",
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer tok",
            },
            id="hanzo",
        ),
        pytest.param(
            "anthropic",
            "",
            {"Content-Type": "application/json"},
            id="no-key",
        ),
    ],
)
def test_build_auth_headers(
    provider: str,
    key: str,
    expected: dict[str, str],
) -> None:
    assert hanzo.build_auth_headers(provider, key) == expected


def test_load_config_resolves_from_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HANZO_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("HOME", str(tmp_path))
    _write(
        tmp_path / ".hanzo" / "auth.json",
        {"auth_mode": "apikey", "OPENAI_API_KEY": "gateway-token"},
    )

    config = hanzo.load_config({"provider": "hanzo", "model": "zen"})
    headers = hanzo.build_auth_headers(config.provider, config.api_key)

    assert config.api_key == "gateway-token"
    assert headers["Authorization"] == "Bearer gateway-token"


# ---------------------------------------------------------------------------
# Local-first routing (resolve_endpoint)
# ---------------------------------------------------------------------------


def test_route_local_uses_engine_no_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "local"}))

    assert endpoint.route == "local"
    assert "36900" in endpoint.base_url
    assert endpoint.model == "default"
    assert "Authorization" not in endpoint.headers
    assert "x-api-key" not in endpoint.headers


def test_route_cloud_uses_gateway_with_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("HANZO_API_KEY", "tok")

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "cloud"}))

    assert endpoint.route == "cloud"
    assert endpoint.base_url == "https://api.hanzo.ai"
    assert endpoint.headers["Authorization"] == "Bearer tok"


def test_auto_picks_local_when_engine_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(hanzo, "_probe_health", _always_up)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert endpoint.route == "local"
    assert "36900" in endpoint.base_url
    assert endpoint.model == "default"
    assert "Authorization" not in endpoint.headers


def test_auto_falls_back_to_cloud_when_engine_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(hanzo, "_probe_health", _always_down)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert endpoint.route == "cloud"
    assert endpoint.base_url == "https://api.hanzo.ai"


def test_auto_explicit_cloud_vendor_wins_over_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    # Engine is up, but the user explicitly chose a cloud vendor with a key.
    monkeypatch.setattr(hanzo, "_probe_health", _always_up)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({
        "route": "auto",
        "provider": "openai",
        "provider_explicit": True,
        "api_key": "sk-oai",
    }))

    assert endpoint.route == "cloud"
    assert endpoint.headers["Authorization"] == "Bearer sk-oai"


def test_auto_default_provider_stays_local_even_with_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    # A key is present, but the anthropic default was not explicitly chosen,
    # so local-first must still win when the engine is up.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setattr(hanzo, "_probe_health", _always_up)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({
        "route": "auto",
        "provider": "anthropic",
    }))

    assert endpoint.route == "local"


def test_gateway_override_replaces_cloud_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({
        "route": "cloud",
        "llm_gateway": "http://localhost:4000",
    }))

    assert endpoint.base_url == "http://localhost:4000"


def test_auto_dead_port_falls_back_to_cloud_no_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real probe (not monkeypatched) against a closed port: must refuse fast,
    # report unhealthy, and fall back to cloud without raising.
    _clear_cloud_env(monkeypatch)
    dead = f"http://127.0.0.1:{_closed_port()}"

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({
        "route": "auto",
        "local_url": dead,
    }))

    assert endpoint.route == "cloud"
    assert endpoint.base_url == "https://api.hanzo.ai"


def test_invalid_route_defaults_to_auto() -> None:
    assert hanzo.load_config({"route": "nonsense"}).route == "auto"
