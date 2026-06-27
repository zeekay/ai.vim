#!/usr/bin/env python3
"""
Hanzo AI provider for Neural/hanzo.vim

Supports:
1. Direct LLM API calls (OpenAI-compatible via LLM Gateway)
2. MCP/ZAP protocol via WebSocket bridge
3. Local Ollama models
4. Claude, GPT-4, Gemini, and other providers via hanzo-llm
"""
import asyncio
import json
import os
import platform
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, NamedTuple, cast

# Try to import websockets for MCP/ZAP bridge
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# Constants
#
# Local-first routing endpoints. The native Hanzo engine (kept alive by the
# Hanzo desktop app's node manager) speaks the OpenAI-compatible API on :36900
# and needs no auth. The cloud account is the Hanzo gateway, reached with the
# resolved account credentials.
HANZO_LOCAL_URL = "http://127.0.0.1:36900"   # native local engine
HANZO_LOCAL_MODEL = "default"                # model id the local engine serves
HANZO_CLOUD_URL = "https://api.hanzo.ai"     # cloud account gateway
HANZO_MCP_BRIDGE = "ws://localhost:9228"     # Vim bridge port
DATA_HEADER = "data: "
DONE_MARKER = "[DONE]"
ANTHROPIC_VERSION = "2023-06-01"

# A /health probe result is trusted for this long (per URL), so a burst of
# requests/keystrokes does not re-probe the local engine each time.
_HEALTH_TTL_SECONDS = 5.0
_health_cache: "dict[str, tuple[float, bool]]" = {}

# Cloud vendors whose explicit selection (with a resolved credential) wins
# over the local engine even in auto mode.
_CLOUD_VENDORS = ("anthropic", "openai")

# Keys a `dev`-written auth.json may carry, in the order each store prefers.
_CODEX_KEYS = ("OPENAI_API_KEY", "openai_api_key")
_HANZO_KEYS = ("openai_api_key", "OPENAI_API_KEY")


# ---------------------------------------------------------------------------
# Shared credential resolution
#
# Mirrors the Hanzo `dev` CLI (core/src/auth.rs::discover_credentials) so the
# editor provider reads the SAME credentials that `:AILogin` / `dev login`
# write. Resolution order, per active provider:
#
#   anthropic: ANTHROPIC_API_KEY env -> Claude Code keychain (macOS only)
#   openai:    OPENAI_API_KEY env    -> ~/.codex/auth.json
#   hanzo:     HANZO_API_KEY env     -> ~/.hanzo/auth.json
#
# Stdlib only. The auth.json files are read defensively, matching the schema
# the `dev` CLI writes: api-key mode {"OPENAI_API_KEY": ...}, OAuth mode
# {"tokens": {"access_token": ...}}.
# ---------------------------------------------------------------------------


def build_auth_headers(provider: str, api_key: str) -> dict[str, str]:
    """Build request headers with the right auth scheme per vendor.

    Anthropic uses ``x-api-key`` + ``anthropic-version``; OpenAI and the
    Hanzo gateway use ``Authorization: Bearer``.
    """
    headers = {"Content-Type": "application/json"}

    if api_key:
        if provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    return headers


def _read_json_file(path: str) -> "dict[str, object] | None":
    """Read a JSON object from ``path``; return None on any error."""
    try:
        with open(path, encoding="utf-8") as handle:
            parsed: object = json.load(handle)
    except (OSError, ValueError):
        return None

    if isinstance(parsed, dict):
        return cast("dict[str, object]", parsed)

    return None


def _str_field(data: dict[str, object], key: str) -> str:
    """Return ``data[key]`` when it is a non-empty string, else ``""``."""
    value = data.get(key)

    if isinstance(value, str) and value:
        return value

    return ""


def _direct_key(data: dict[str, object], keys: tuple[str, ...]) -> str:
    """Return the first non-empty string value for any key in ``keys``."""
    for key in keys:
        found = _str_field(data, key)

        if found:
            return found

    return ""


def _access_token(data: dict[str, object]) -> str:
    """Return ``tokens.access_token`` when present and non-empty."""
    tokens = data.get("tokens")

    if isinstance(tokens, dict):
        return _str_field(cast("dict[str, object]", tokens), "access_token")

    return ""


def _codex_token(home: str) -> str:
    """Resolve the OpenAI token from ~/.codex/auth.json."""
    data = _read_json_file(os.path.join(home, ".codex", "auth.json"))

    if data is None:
        return ""

    # OAuth mode stores tokens.access_token; api-key mode OPENAI_API_KEY.
    return _access_token(data) or _direct_key(data, _CODEX_KEYS)


def _hanzo_token(home: str) -> str:
    """Resolve the Hanzo IAM token from ~/.hanzo/auth.json."""
    data = _read_json_file(os.path.join(home, ".hanzo", "auth.json"))

    if data is None:
        return ""

    # Login stores the token under openai_api_key/OPENAI_API_KEY; OAuth
    # refresh stores tokens.access_token.
    return _direct_key(data, _HANZO_KEYS) or _access_token(data)


def _claude_keychain_token() -> str:
    """Read the Anthropic token from the Claude Code macOS keychain."""
    if platform.system() != "Darwin":
        return ""

    try:
        result = subprocess.run(
            [
                "security", "find-generic-password",
                "-s", "Claude Code-credentials", "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    if result.returncode != 0:
        return ""

    try:
        parsed: object = json.loads(result.stdout.strip())
    except ValueError:
        return ""

    if not isinstance(parsed, dict):
        return ""

    oauth = cast("dict[str, object]", parsed).get("claudeAiOauth")

    if isinstance(oauth, dict):
        return _str_field(cast("dict[str, object]", oauth), "accessToken")

    return ""


def resolve_shared_credential(provider: str, home: str = "") -> str:
    """Resolve an API key/token for ``provider`` from shared stores.

    Mirrors the Hanzo `dev` CLI resolution order. Returns an empty string
    when nothing resolves, so callers can fall back to other config.
    """
    home = home or os.path.expanduser("~")

    if provider == "anthropic":
        return (
            os.environ.get("ANTHROPIC_API_KEY", "")
            or _claude_keychain_token()
        )

    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "") or _codex_token(home)

    if provider == "hanzo":
        return os.environ.get("HANZO_API_KEY", "") or _hanzo_token(home)

    return ""


class HanzoConfig:
    """Configuration for Hanzo provider."""

    def __init__(
        self,
        *,
        # Connection settings
        mode: str = "api",  # "api", "mcp", "ollama"
        url: str = "",
        api_key: str = "",

        # Model settings
        model: str = "claude-sonnet-4-20250514",
        provider: str = "anthropic",  # anthropic, openai, google, ollama
        provider_explicit: bool = False,

        # Local-first routing
        route: str = "auto",  # auto | local | cloud
        local_url: str = HANZO_LOCAL_URL,
        local_model: str = HANZO_LOCAL_MODEL,
        cloud_url: str = HANZO_CLOUD_URL,
        gateway: str = "",  # optional cloud-base override (e.g. :4000)

        # Generation settings
        temperature: float = 0.2,
        top_p: float = 1.0,
        max_tokens: int = 4096,

        # MCP settings
        mcp_bridge_port: int = 9228,

        # System prompt
        system_prompt: str = "",
    ):
        self.mode = mode
        self.url = url
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.provider_explicit = provider_explicit
        self.route = route
        self.local_url = local_url
        self.local_model = local_model
        self.cloud_url = cloud_url
        self.gateway = gateway
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.mcp_bridge_port = mcp_bridge_port
        self.system_prompt = system_prompt


def load_config(raw_config: dict[str, Any]) -> HanzoConfig:
    """Load and validate configuration."""
    if not isinstance(raw_config, dict):
        raise ValueError("hanzo config is not a dictionary")

    # Determine mode
    mode = raw_config.get("mode", "api")
    if mode not in ("api", "mcp", "ollama"):
        mode = "api"

    # URL defaults. In api mode the request target (local engine vs cloud
    # account) is chosen by resolve_endpoint(), so url stays empty here; only
    # ollama uses this field directly.
    url = raw_config.get("url", "")
    if not url and mode == "ollama":
        url = "http://localhost:11434"

    # Model selection
    model = raw_config.get("model", "claude-sonnet-4-20250514")

    # Provider inference from model name
    provider = raw_config.get("provider", "")
    if not provider:
        if "claude" in model.lower():
            provider = "anthropic"
        elif "gpt" in model.lower() or "o1" in model.lower():
            provider = "openai"
        elif "gemini" in model.lower():
            provider = "google"
        elif mode == "ollama":
            provider = "ollama"
        else:
            provider = "anthropic"

    # API key / token resolution, in priority order:
    #   1. explicit api_key from config (existing users keep working)
    #   2. shared credential stores per provider, mirroring the `dev` CLI
    #      (env -> ~/.codex/auth.json -> ~/.hanzo/auth.json)
    #   3. generic env-var fallback (back-compat, e.g. GOOGLE_API_KEY)
    api_key = raw_config.get("api_key", "")
    if not api_key:
        api_key = resolve_shared_credential(provider)
    if not api_key:
        for env_var in [
            "HANZO_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
        ]:
            api_key = os.environ.get(env_var, "")
            if api_key:
                break

    # Explicit provider intent: set by the user via g:hanzo_provider /
    # :AILogin. Distinguishes a deliberate cloud choice from the default,
    # so auto-routing does not silently favour cloud just because a key
    # happens to be in the environment.
    provider_explicit = bool(raw_config.get("provider_explicit", False))

    # Local-first routing config (mirrors the g:hanzo_* vim defaults).
    route = raw_config.get("route", "auto")
    if route not in ("auto", "local", "cloud"):
        route = "auto"

    local_url = raw_config.get("local_url", "") or HANZO_LOCAL_URL
    local_model = raw_config.get("local_model", "") or HANZO_LOCAL_MODEL
    cloud_url = raw_config.get("cloud_url", "") or HANZO_CLOUD_URL
    gateway = (
        raw_config.get("llm_gateway", "")
        or os.environ.get("HANZO_LLM_GATEWAY", "")
    )

    # Generation settings
    temperature = float(raw_config.get("temperature", 0.2))
    top_p = float(raw_config.get("top_p", 1.0))
    max_tokens = int(raw_config.get("max_tokens", 4096))

    # MCP settings
    mcp_bridge_port = int(raw_config.get("mcp_bridge_port", 9228))

    # System prompt
    system_prompt = raw_config.get("system_prompt", "")
    if not system_prompt:
        system_prompt = (
            "You are an expert programmer assistant integrated into "
            "Vim/Neovim.\n"
            "Provide concise, accurate code and explanations.\n"
            "When writing code, match the existing style in the file.\n"
            "Focus on the specific task requested."
        )

    return HanzoConfig(
        mode=mode,
        url=url,
        api_key=api_key,
        model=model,
        provider=provider,
        provider_explicit=provider_explicit,
        route=route,
        local_url=local_url,
        local_model=local_model,
        cloud_url=cloud_url,
        gateway=gateway,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        mcp_bridge_port=mcp_bridge_port,
        system_prompt=system_prompt,
    )


# ---------------------------------------------------------------------------
# Local-first routing
#
# resolve_endpoint() is the single place that decides where a request goes:
# the native local engine (no auth) when it is up, else the cloud account.
# Both speak the OpenAI-compatible POST {base}/v1/chat/completions, so the
# request/stream code below is shared.
# ---------------------------------------------------------------------------


class Endpoint(NamedTuple):
    """A resolved request target: where to send and how to authenticate."""

    route: str  # "local" or "cloud"
    base_url: str
    model: str
    headers: dict[str, str]


def _probe_health(url: str, timeout: float = 0.7) -> bool:
    """Return True if ``GET {url}/health`` answers 2xx.

    The result is cached per URL for a few seconds so a burst of requests
    does not re-probe the engine on every keystroke.
    """
    now = time.monotonic()
    cached = _health_cache.get(url)

    if cached is not None and now - cached[0] < _HEALTH_TTL_SECONDS:
        return cached[1]

    ok = False

    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 0)
            ok = isinstance(status, int) and 200 <= status < 300
    except (urllib.error.URLError, OSError, ValueError):
        ok = False

    _health_cache[url] = (now, ok)

    return ok


def _local_endpoint(config: HanzoConfig) -> Endpoint:
    """Native local engine endpoint. It needs no auth header."""
    return Endpoint(
        route="local",
        base_url=config.local_url,
        model=config.local_model,
        headers={"Content-Type": "application/json"},
    )


def _cloud_endpoint(config: HanzoConfig) -> Endpoint:
    """Cloud account endpoint: the Hanzo gateway (or a gateway override).

    An explicitly chosen cloud vendor uses its own credential; otherwise the
    Hanzo account token (Bearer) authenticates against the gateway.
    """
    base = config.gateway or config.cloud_url

    if config.provider_explicit and config.provider in _CLOUD_VENDORS:
        provider, api_key = config.provider, config.api_key
    else:
        provider = "hanzo"
        api_key = resolve_shared_credential("hanzo") or config.api_key

    return Endpoint(
        route="cloud",
        base_url=base,
        model=config.model,
        headers=build_auth_headers(provider, api_key),
    )


def resolve_endpoint(config: HanzoConfig) -> Endpoint:
    """Pick the local engine or the cloud account for this request.

    - ``local``: always the native engine (no auth).
    - ``cloud``: always the cloud account (resolved account creds).
    - ``auto`` (default): an explicitly chosen cloud vendor with a resolved
      credential wins; else the local engine when its /health is up; else
      the cloud account.
    """
    if config.route == "local":
        return _local_endpoint(config)

    if config.route == "cloud":
        return _cloud_endpoint(config)

    explicit_cloud = (
        config.provider_explicit
        and config.provider in _CLOUD_VENDORS
        and bool(config.api_key)
    )

    if explicit_cloud:
        return _cloud_endpoint(config)

    if _probe_health(config.local_url):
        return _local_endpoint(config)

    return _cloud_endpoint(config)


async def call_via_mcp(config: HanzoConfig, prompt: str) -> None:
    """Call LLM via MCP/ZAP WebSocket bridge."""
    if not HAS_WEBSOCKETS:
        raise RuntimeError(
            "websockets not installed. Run: pip install websockets",
        )

    uri = f"ws://localhost:{config.mcp_bridge_port + 1}"

    try:
        async with websockets.connect(uri) as ws:
            # Send LLM request via MCP bridge
            request = {
                "action": "llm",
                "params": {
                    "prompt": prompt,
                    "model": config.model,
                    "provider": config.provider,
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                    "stream": True,
                    "system_prompt": config.system_prompt,
                },
            }
            await ws.send(json.dumps(request))

            # Process streaming response
            async for message in ws:
                data = json.loads(message)
                if "error" in data:
                    raise RuntimeError(data["error"])
                elif "chunk" in data:
                    print(data["chunk"], end="", flush=True)
                elif "done" in data:
                    break

            print()
    except ConnectionRefusedError as error:
        port = config.mcp_bridge_port + 1
        raise RuntimeError(
            f"Cannot connect to MCP bridge on port {port}. "
            "Start Vim with :HanzoStart",
        ) from error


def call_openai_compatible(config: HanzoConfig, prompt: str) -> None:
    """Stream a completion from the resolved OpenAI-compatible endpoint.

    The target (local engine vs cloud account) is chosen by
    ``resolve_endpoint``; both speak ``POST {base}/v1/chat/completions``.
    """
    target = resolve_endpoint(config)
    headers = dict(target.headers)

    # Build messages
    messages: list[dict[str, str]] = []
    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})
    messages.append({"role": "user", "content": prompt})

    data: dict[str, Any] = {
        "model": target.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "top_p": config.top_p,
        "stream": True,
    }

    # Anthropic's native API uses /v1/messages; the local engine and the
    # Hanzo gateway are OpenAI-compatible.
    is_anthropic_native = (
        config.provider == "anthropic"
        and "api.anthropic.com" in target.base_url
    )
    request_url = (
        f"{target.base_url}/v1/messages"
        if is_anthropic_native
        else f"{target.base_url}/v1/chat/completions"
    )

    req = urllib.request.Request(
        request_url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    # Handle SSL for macOS
    context = (
        ssl._create_unverified_context()
        if platform.system() == "Darwin"
        else None
    )

    try:
        with urllib.request.urlopen(req, context=context) as response:
            while True:
                line_bytes = response.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                if line.startswith(DATA_HEADER):
                    line_data = line[len(DATA_HEADER):]
                    if line_data == DONE_MARKER:
                        break

                    try:
                        obj = json.loads(line_data)

                        # OpenAI format
                        if "choices" in obj:
                            delta = obj["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                print(content, end="", flush=True)

                        # Anthropic format
                        elif "delta" in obj:
                            content = obj["delta"].get("text", "")
                            if content:
                                print(content, end="", flush=True)
                        elif "content_block" in obj:
                            content = obj["content_block"].get("text", "")
                            if content:
                                print(content, end="", flush=True)
                    except json.JSONDecodeError:
                        continue

        print()

    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="ignore")
        try:
            err_data = json.loads(message)
            if "error" in err_data:
                message = err_data["error"].get("message", message)
        except ValueError:
            pass
        raise RuntimeError(
            f"API error ({error.code}): {message}",
        ) from error


def call_ollama(config: HanzoConfig, prompt: str) -> None:
    """Call local Ollama instance."""
    messages: list[dict[str, str]] = []
    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})
    messages.append({"role": "user", "content": prompt})

    data: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.max_tokens,
        },
    }

    req = urllib.request.Request(
        f"{config.url}/api/chat",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            while True:
                line_bytes = response.readline()
                if not line_bytes:
                    break

                try:
                    obj = json.loads(line_bytes.decode("utf-8"))
                    if "message" in obj:
                        content = obj["message"].get("content", "")
                        if content:
                            print(content, end="", flush=True)
                    if obj.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

        print()

    except urllib.error.HTTPError as error:
        body = error.read().decode()
        raise RuntimeError(f"Ollama error ({error.code}): {body}") from error


def _print_resolution() -> None:
    """Print the resolved route as JSON for :AIStatus. Reads config on stdin.

    Input:  {"config": {...}} on a single line.
    Output: {"route", "base_url", "model", "provider", "authenticated"}.
    """
    payload = json.loads(sys.stdin.readline() or "{}")
    config = load_config(payload.get("config", {}))
    target = resolve_endpoint(config)
    authenticated = bool(
        target.headers.get("Authorization")
        or target.headers.get("x-api-key"),
    )

    print(json.dumps({
        "route": target.route,
        "base_url": target.base_url,
        "model": target.model,
        "provider": config.provider,
        "authenticated": authenticated,
    }))


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "--resolve":
        _print_resolution()
        return

    input_data = json.loads(sys.stdin.readline())

    try:
        config = load_config(input_data.get("config", {}))
    except ValueError as err:
        sys.exit(f"Configuration error: {err}")

    prompt = input_data.get("prompt", "")
    if not prompt:
        sys.exit("No prompt provided")

    try:
        if config.mode == "mcp":
            asyncio.run(call_via_mcp(config, prompt))
        elif config.mode == "ollama":
            call_ollama(config, prompt)
        else:
            call_openai_compatible(config, prompt)
    except Exception as err:
        sys.exit(f"Hanzo error: {err}")


if __name__ == "__main__":
    main()
