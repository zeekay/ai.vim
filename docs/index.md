---
title: hanzo.vim
description: Hanzo AI plugin for Vim and Neovim
---

# hanzo.vim

Hanzo AI plugin for Vim and Neovim with support for Claude, GPT-4, Gemini, Ollama, and more.

## Installation

```vim
" vim-plug
Plug 'hanzoai/hanzo.vim'
```

```bash
# Manual
git clone https://github.com/hanzoai/hanzo.vim ~/.vim/pack/plugins/start/hanzo.vim
```

## Quick Start

```vim
" Set your API key
let g:hanzo_model = 'claude-sonnet-4-20250514'
let g:hanzo_provider = 'anthropic'

" Use :Hanzo or :H to chat
:Hanzo write a hello world function
```

## Features

- **Multi-Provider**: Claude, GPT-4, Gemini, Ollama
- **MCP/ZAP Bridge**: AI agent control
- **REPL Integration**: Jupyter kernels
- **Extended Commands**: Complete, Explain, Refactor, Fix, Tests, Docs, Review

## Commands

| Command | Description |
|---------|-------------|
| `:Hanzo <prompt>` | Send prompt to AI |
| `:HanzoComplete` | Complete code |
| `:HanzoExplain` | Explain selection |
| `:HanzoRefactor` | Refactor code |
| `:HanzoFix` | Fix issues |
| `:HanzoTests` | Generate tests |
| `:HanzoDocs` | Generate docs |
| `:HanzoReview` | Code review |

## Configuration

See [README](https://github.com/hanzoai/hanzo.vim) for full configuration options.
