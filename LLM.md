# Hanzo Hanzo.Vim

## Overview
A coding agent

## Tech Stack
- **Language**: Python

## Build & Run
```bash
uv sync
uv run pytest
```

## Structure
```
hanzo.vim/
  Dockerfile
  LICENSE.md
  README.md
  autoload/
  doc/
  docs/
  ftplugin/
  lua/
  plugin/
  pyproject.toml
  python3/
  run-tests
  src/
  test/
  typings/
```

## Key Files
- `README.md` -- Project documentation
- `pyproject.toml` -- Python project config
- `Dockerfile` -- Container build
- `plugin/hanzo.vim` -- commands + config defaults (incl. `g:ai_cli`,
  `g:hanzo_route`); registers the Hanzo provider as Neural's default so `:AI`
  is local-first out of the box
- `autoload/hanzo.vim` -- command impls (incl. `:AILogin` family,
  `hanzo#NeuralProvider`, `hanzo#ResolveRoute`, `:AIStatus` route line)
- `src/neural/provider/hanzo.py` -- AI provider + shared credential resolver
  + `resolve_endpoint()` local-first routing
- `doc/hanzo.txt` -- `:help hanzo-ailogin`, `:help hanzo-routing`

## Local-first routing (native engine vs cloud account)
`:AI`/`:Hanzo` -> Neural -> `src/neural/provider/hanzo.py`. `resolve_endpoint()`
is the ONE place that picks the target: native local engine when up, else cloud.
- `g:hanzo_route` = `auto` (default) | `local` | `cloud`.
- `auto`: `GET {g:hanzo_local_url}/health` (cached ~5s); 2xx -> local (no auth),
  else cloud. An explicitly chosen cloud vendor (`g:hanzo_provider`
  anthropic/openai, tracked via `g:hanzo_provider_explicit`) with a resolved
  cred wins first.
- local engine: `g:hanzo_local_url` (`http://127.0.0.1:36900`), model
  `g:hanzo_local_model` (`default`), no auth -- it is spawned/kept alive by the
  Hanzo desktop app, NOT by this plugin. Do NOT route through `dev` (the agent
  harness garbles small local models); talk to its OpenAI HTTP API directly.
- cloud account: `g:hanzo_cloud_url` (`https://api.hanzo.ai`), creds via
  `resolve_shared_credential`/`build_auth_headers`. `g:hanzo_llm_gateway`
  (default "") optionally overrides the cloud base (e.g. a local `:4000`).
- Both endpoints are OpenAI-compatible `POST {base}/v1/chat/completions`.
- `python3 src/neural/provider/hanzo.py --resolve` prints the resolved route as
  JSON (stdin `{"config":{...}}`); `:AIStatus` uses it via `hanzo#ResolveRoute`.

## AI Login (multi-vendor, not vendor-locked)
`:AILogin` / `:AILogout` / `:AIStatus` delegate OAuth to the installed `dev`
CLI (Hanzo Dev): `dev login [--chatgpt] [--device-code] [--with-api-key]`.
The provider (`hanzo.py::resolve_shared_credential`) reads the SAME stores in
`dev`'s order (`auth.rs::discover_credentials`): env -> `~/.codex/auth.json`
(openai) / `~/.hanzo/auth.json` (hanzo), Claude Code keychain (anthropic,
macOS). Header per vendor: Anthropic `x-api-key`, OpenAI/Hanzo `Bearer`.
Keys via `inputsecret()` piped to `dev` over stdin; `dev` owns the `0600`
store. `:HanzoLogin` is an alias for `:AILogin hanzo`. Override the CLI with
`g:ai_cli` (default `dev`).
