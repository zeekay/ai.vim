import json
from pathlib import Path

import pytest

from neural.provider import hanzo


def _write(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


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
