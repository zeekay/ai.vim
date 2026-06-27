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
- `plugin/hanzo.vim` -- commands + config defaults (incl. `g:ai_cli`)
- `autoload/hanzo.vim` -- command impls (incl. `:AILogin` family)
- `src/neural/provider/hanzo.py` -- AI provider + shared credential resolver
- `doc/hanzo.txt` -- `:help hanzo-ailogin`

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
