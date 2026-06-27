import json
import socket
from collections.abc import Callable
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


_Probe = Callable[..., "tuple[int, bytes]"]


def _probe_up(_url: str, _timeout: float = 0.5) -> tuple[int, bytes]:
    """Fake _http_probe: every backend answers 2xx (empty body)."""
    return (200, b"")


def _probe_down(_url: str, _timeout: float = 0.5) -> tuple[int, bytes]:
    """Fake _http_probe: nothing is listening anywhere."""
    return (0, b"")


def _routed_probe(routes: dict[str, tuple[int, bytes]]) -> _Probe:
    """Fake _http_probe routing by URL substring (e.g. "11434/api/tags").

    The first matching fragment wins; unmatched URLs report down. This lets a
    test bring exactly one backend up by its host:port + path.
    """
    def probe(url: str, _timeout: float = 0.5) -> tuple[int, bytes]:
        for fragment, response in routes.items():
            if fragment in url:
                return response

        return (0, b"")

    return probe


def _ollama_tags(*names: str) -> bytes:
    return json.dumps(
        {"models": [{"name": name} for name in names]},
    ).encode("utf-8")


def _openai_models(*ids: str) -> bytes:
    return json.dumps(
        {"data": [{"id": model_id} for model_id in ids]},
    ).encode("utf-8")


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
    monkeypatch.setattr(hanzo, "_http_probe", _probe_up)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert endpoint.route == "local"
    assert "36900" in endpoint.base_url
    assert endpoint.model == "default"
    assert "Authorization" not in endpoint.headers


def test_auto_falls_back_to_cloud_when_engine_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(hanzo, "_http_probe", _probe_down)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert endpoint.route == "cloud"
    assert endpoint.base_url == "https://api.hanzo.ai"


def test_auto_explicit_cloud_vendor_wins_over_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    # Engine is up, but the user explicitly chose a cloud vendor with a key.
    monkeypatch.setattr(hanzo, "_http_probe", _probe_up)

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
    monkeypatch.setattr(hanzo, "_http_probe", _probe_up)

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
    # report unhealthy, and fall back to cloud without raising. Constrain to
    # the hanzo backend so the test does not depend on a dev's local Ollama.
    _clear_cloud_env(monkeypatch)
    dead = f"http://127.0.0.1:{_closed_port()}"

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({
        "route": "auto",
        "local_url": dead,
        "local_backends": ["hanzo"],
    }))

    assert endpoint.route == "cloud"
    assert endpoint.base_url == "https://api.hanzo.ai"


def test_invalid_route_defaults_to_auto() -> None:
    assert hanzo.load_config({"route": "nonsense"}).route == "auto"


# ---------------------------------------------------------------------------
# Multi-backend local detection (detect_local_backends + inspect_*)
# ---------------------------------------------------------------------------


def test_config_default_backends_order() -> None:
    assert hanzo.load_config({}).local_backends == (
        "hanzo", "ollama", "lmstudio",
    )


def test_config_custom_backends_order() -> None:
    config = hanzo.load_config({"local_backends": ["ollama", "hanzo"]})

    assert config.local_backends == ("ollama", "hanzo")


@pytest.mark.parametrize("raw", [[], "nope", None, [123, ""]])
def test_config_backends_fall_back_to_default(raw: object) -> None:
    config = hanzo.load_config({"local_backends": raw})

    assert config.local_backends == ("hanzo", "ollama", "lmstudio")


def _ollama_model(monkeypatch: pytest.MonkeyPatch, body: bytes) -> str:
    """Resolve the model the Ollama detector picks for a /api/tags body."""
    monkeypatch.setattr(
        hanzo, "_http_probe", _routed_probe({"11434/api/tags": (200, body)}),
    )
    detected = hanzo.detect_local_backends(
        hanzo.load_config({"local_backends": ["ollama"]}),
    )

    return detected[0].model if detected else ""


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (_ollama_tags("a", "b"), "a"),
        (b'{"models": [{"model": "fallback"}]}', "fallback"),
        (_ollama_tags(), ""),
        (b"not json", ""),
        (b"[]", ""),
    ],
)
def test_ollama_model_parsing_via_detection(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    expected: str,
) -> None:
    assert _ollama_model(monkeypatch, body) == expected


def _lmstudio_model(monkeypatch: pytest.MonkeyPatch, body: bytes) -> str:
    """Resolve the model the LM Studio detector picks for a /v1/models body."""
    monkeypatch.setattr(
        hanzo, "_http_probe", _routed_probe({"1234/v1/models": (200, body)}),
    )
    detected = hanzo.detect_local_backends(
        hanzo.load_config({"local_backends": ["lmstudio"]}),
    )

    return detected[0].model if detected else ""


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (_openai_models("x", "y"), "x"),
        (_openai_models(), ""),
        (b"garbage", ""),
        (b'{"data": "nope"}', ""),
    ],
)
def test_lmstudio_model_parsing_via_detection(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    expected: str,
) -> None:
    assert _lmstudio_model(monkeypatch, body) == expected


def test_detect_hanzo_up_others_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only the Hanzo engine (:36900 /health) answers; Ollama and LM Studio
    # are not running and must be reported absent without hanging.
    monkeypatch.setattr(
        hanzo, "_http_probe", _routed_probe({"36900/health": (200, b"")}),
    )

    detected = hanzo.detect_local_backends(hanzo.load_config({}))

    assert [backend.name for backend in detected] == ["hanzo"]
    assert detected[0].model == "default"
    assert detected[0].host == "127.0.0.1:36900"
    assert detected[0].up is True


def test_inspect_reports_all_backends_with_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hanzo, "_http_probe", _routed_probe({"36900/health": (200, b"")}),
    )

    report = hanzo.inspect_local_backends(hanzo.load_config({}))

    assert [backend.name for backend in report] == [
        "hanzo", "ollama", "lmstudio",
    ]
    assert report[0].up is True
    assert report[1].up is False
    assert report[2].up is False
    assert report[1].label == "Ollama"
    assert report[2].label == "LM Studio"


def test_auto_resolves_to_local_hanzo_when_only_hanzo_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(
        hanzo, "_http_probe", _routed_probe({"36900/health": (200, b"")}),
    )

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert endpoint.route == "local"
    assert "36900" in endpoint.base_url
    assert endpoint.model == "default"
    assert "Authorization" not in endpoint.headers


def test_detect_skips_ollama_when_up_but_no_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ollama answering /api/tags with an empty list is not usable for routing.
    monkeypatch.setattr(
        hanzo,
        "_http_probe",
        _routed_probe({"11434/api/tags": (200, _ollama_tags())}),
    )

    assert hanzo.detect_local_backends(hanzo.load_config({})) == []


def test_auto_picks_ollama_when_hanzo_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hanzo engine down, Ollama up: auto must route to Ollama with its model.
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(
        hanzo,
        "_http_probe",
        _routed_probe({"11434/api/tags": (200, _ollama_tags("llama3.2"))}),
    )

    detected = hanzo.detect_local_backends(hanzo.load_config({}))
    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert [backend.name for backend in detected] == ["ollama"]
    assert endpoint.route == "local"
    assert "11434" in endpoint.base_url
    assert endpoint.model == "llama3.2"
    assert "Authorization" not in endpoint.headers


def test_auto_picks_lmstudio_when_only_it_is_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(
        hanzo,
        "_http_probe",
        _routed_probe({"1234/v1/models": (200, _openai_models("qwen-coder"))}),
    )

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "auto"}))

    assert endpoint.route == "local"
    assert "1234" in endpoint.base_url
    assert endpoint.model == "qwen-coder"


def test_backend_order_decides_winner_when_several_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both Hanzo and Ollama up, but the configured order prefers Ollama.
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(
        hanzo,
        "_http_probe",
        _routed_probe({
            "36900/health": (200, b""),
            "11434/api/tags": (200, _ollama_tags("llama3.2")),
        }),
    )

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({
        "route": "auto",
        "local_backends": ["ollama", "hanzo"],
    }))

    assert endpoint.route == "local"
    assert "11434" in endpoint.base_url


def test_auto_all_local_down_falls_back_to_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(hanzo, "_http_probe", _probe_down)

    config = hanzo.load_config({"route": "auto"})

    assert hanzo.detect_local_backends(config) == []
    assert hanzo.resolve_endpoint(config).route == "cloud"


def test_route_local_falls_back_to_hanzo_engine_when_none_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An explicit local route must stay local even if nothing answers a probe.
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(hanzo, "_http_probe", _probe_down)

    endpoint = hanzo.resolve_endpoint(hanzo.load_config({"route": "local"}))

    assert endpoint.route == "local"
    assert "36900" in endpoint.base_url
    assert "Authorization" not in endpoint.headers


def test_probe_is_cached_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The probe is cached per URL so a burst of requests hits the network once.
    # Use a unique closed port so this URL is absent from the shared cache, and
    # drive it through the public resolve_endpoint (no private access).
    _clear_cloud_env(monkeypatch)
    calls = {"n": 0}

    def counting_open(*_args: object, **_kwargs: object) -> object:
        calls["n"] += 1
        raise OSError("refused")

    monkeypatch.setattr(hanzo.urllib.request, "urlopen", counting_open)
    dead = f"http://127.0.0.1:{_closed_port()}"
    config = hanzo.load_config({
        "route": "local",
        "local_url": dead,
        "local_backends": ["hanzo"],
    })

    hanzo.resolve_endpoint(config)
    hanzo.resolve_endpoint(config)

    assert calls["n"] == 1
