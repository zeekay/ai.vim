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
import sys
from typing import Any, Optional

# Try to import websockets for MCP/ZAP bridge
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# Constants
HANZO_LLM_GATEWAY = "http://localhost:4000"  # Default LLM Gateway
HANZO_MCP_BRIDGE = "ws://localhost:9228"     # Vim bridge port
DATA_HEADER = "data: "
DONE_MARKER = "[DONE]"


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

    # URL defaults
    url = raw_config.get("url", "")
    if not url:
        if mode == "ollama":
            url = "http://localhost:11434"
        elif mode == "mcp":
            url = ""  # Uses WebSocket
        else:
            # Check for LLM Gateway first, then direct API
            url = os.environ.get("HANZO_LLM_GATEWAY", HANZO_LLM_GATEWAY)

    # API key from config or environment
    api_key = raw_config.get("api_key", "")
    if not api_key:
        # Try multiple environment variables
        for env_var in [
            "HANZO_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
        ]:
            api_key = os.environ.get(env_var, "")
            if api_key:
                break

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

    # Generation settings
    temperature = float(raw_config.get("temperature", 0.2))
    top_p = float(raw_config.get("top_p", 1.0))
    max_tokens = int(raw_config.get("max_tokens", 4096))

    # MCP settings
    mcp_bridge_port = int(raw_config.get("mcp_bridge_port", 9228))

    # System prompt
    system_prompt = raw_config.get("system_prompt", "")
    if not system_prompt:
        system_prompt = """You are an expert programmer assistant integrated into Vim/Neovim.
Provide concise, accurate code and explanations.
When writing code, match the existing style in the file.
Focus on the specific task requested."""

    return HanzoConfig(
        mode=mode,
        url=url,
        api_key=api_key,
        model=model,
        provider=provider,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        mcp_bridge_port=mcp_bridge_port,
        system_prompt=system_prompt,
    )


async def call_via_mcp(config: HanzoConfig, prompt: str) -> None:
    """Call LLM via MCP/ZAP WebSocket bridge."""
    if not HAS_WEBSOCKETS:
        raise RuntimeError("websockets not installed. Run: pip install websockets")

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
                }
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
    except ConnectionRefusedError:
        raise RuntimeError(f"Cannot connect to MCP bridge on port {config.mcp_bridge_port + 1}. Start Vim with :HanzoStart")


def call_openai_compatible(config: HanzoConfig, prompt: str) -> None:
    """Call OpenAI-compatible API (works with LLM Gateway, OpenAI, Anthropic via proxy)."""
    import urllib.request
    import urllib.error

    headers = {
        "Content-Type": "application/json",
    }

    # Set authorization header
    if config.api_key:
        if config.provider == "anthropic":
            headers["x-api-key"] = config.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {config.api_key}"

    # Build messages
    messages = []
    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})
    messages.append({"role": "user", "content": prompt})

    data: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "top_p": config.top_p,
        "stream": True,
    }

    # Determine endpoint
    if config.provider == "anthropic" and "api.anthropic.com" in config.url:
        endpoint = f"{config.url}/v1/messages"
    else:
        endpoint = f"{config.url}/v1/chat/completions"

    req = urllib.request.Request(
        endpoint,
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
        except:
            pass
        raise RuntimeError(f"API error ({error.code}): {message}")


def call_ollama(config: HanzoConfig, prompt: str) -> None:
    """Call local Ollama instance."""
    import urllib.request
    import urllib.error

    messages = []
    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": config.model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.max_tokens,
        }
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
        raise RuntimeError(f"Ollama error ({error.code}): {error.read().decode()}")


def main() -> None:
    """Main entry point."""
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
