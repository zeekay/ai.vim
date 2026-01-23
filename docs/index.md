---
title: hanzo.vim
description: Hanzo AI plugin for Vim and Neovim
---

## Installation

### Using vim-plug

```vim
Plug 'hanzoai/hanzo.vim'
```

### Using lazy.nvim

```lua
{
  'hanzoai/hanzo.vim',
  config = function()
    require('hanzo').setup()
  end
}
```

### Manual Installation

```bash
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

```vim
" Provider settings
let g:hanzo_provider = 'hanzo'  " hanzo, anthropic, openai, ollama
let g:hanzo_model = 'claude-sonnet-4-20250514'

" API keys (can also use environment variables)
let g:hanzo_api_key = $HANZO_API_KEY

" UI settings
let g:hanzo_sidebar_width = 40
let g:hanzo_sidebar_position = 'right'

" MCP integration
let g:hanzo_mcp_enabled = 1
```

## Keybindings

| Key | Action |
|-----|--------|
| `<leader>hc` | Open chat |
| `<leader>he` | Explain code |
| `<leader>hr` | Refactor code |
| `<leader>ht` | Generate tests |

## Requirements

- Vim 8.2+ or Neovim 0.8+
- Python 3.8+ (for neural features)
- Node.js 18+ (for MCP integration)

## Related Projects

- [hanzo.el](https://github.com/hanzoai/hanzo.el) - Emacs package
- [ide-extension](https://github.com/hanzoai/ide-extension) - VS Code & JetBrains
- [browser-extension](https://github.com/hanzoai/browser-extension) - Browser extensions

## License

MIT - See [LICENSE](https://github.com/hanzoai/hanzo.vim/blob/main/LICENSE.md)
