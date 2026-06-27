" Hanzo AI integration for Vim/Neovim
" Author: Hanzo AI Inc
" License: MIT
"
" This plugin extends dense-analysis/neural with:
" - Hanzo AI provider (Claude, GPT-4, Gemini, Ollama, LLM Gateway)
" - MCP/ZAP bridge for AI agent control
" - REPL integration via Jupyter kernels
" - Additional AI-powered commands

if exists('g:loaded_hanzo')
    finish
endif
let g:loaded_hanzo = 1

" Check for required features
if has('nvim')
    let s:has_features = has('timers') && has('nvim-0.5.0')
else
    let s:has_features = has('timers') && exists('*job_start') && exists('*ch_open')
endif

if !s:has_features
    if index(['', 'gitcommit'], &filetype) == -1
        echoerr 'Hanzo requires NeoVim >= 0.5.0 or Vim 8+ with +timers +job +channel'
    endif
    finish
endif

" ============================================================================
" Configuration Defaults
" ============================================================================

" Bridge settings
let g:hanzo_port = get(g:, 'hanzo_port', 9228)
let g:hanzo_auto_start = get(g:, 'hanzo_auto_start', 0)
let g:hanzo_debug = get(g:, 'hanzo_debug', 0)

" Model settings
let g:hanzo_model = get(g:, 'hanzo_model', 'claude-sonnet-4-20250514')
let g:hanzo_provider = get(g:, 'hanzo_provider', 'anthropic')
let g:hanzo_mode = get(g:, 'hanzo_mode', 'api')
let g:hanzo_llm_gateway = get(g:, 'hanzo_llm_gateway', 'http://localhost:4000')

" AI login / CLI delegation (the binary :AILogin reuses for OAuth flows)
let g:ai_cli = get(g:, 'ai_cli', 'dev')

" Keybind settings
let g:hanzo_set_default_keybinds = get(g:, 'hanzo_set_default_keybinds', 0)

" ============================================================================
" Bridge Commands
" ============================================================================

command! HanzoStart call hanzo#StartBridge()
command! HanzoStop call hanzo#StopBridge()
command! HanzoStatus call hanzo#BridgeStatus()

" ============================================================================
" AI Commands
" ============================================================================

" Main chat command
command! -nargs=? Hanzo call hanzo#Chat(<q-args>)
command! -nargs=? H call hanzo#Chat(<q-args>)

" Code operations
command! HanzoComplete call hanzo#Complete()
command! -range HanzoExplain call hanzo#Explain()
command! -nargs=1 -range HanzoRefactor call hanzo#Refactor(<q-args>)
command! -range HanzoFix call hanzo#Fix()
command! -range HanzoTests call hanzo#Tests()
command! -range HanzoDocs call hanzo#Docs()
command! -range HanzoReview call hanzo#Review()

" ============================================================================
" REPL Commands
" ============================================================================

command! -nargs=1 HanzoRepl call hanzo#Repl(<q-args>)
command! -nargs=1 HanzoEval call hanzo#Eval(<q-args>)
command! -range HanzoEvalSelection call hanzo#EvalSelection()
command! HanzoEvalLine call hanzo#EvalLine()

" ============================================================================
" Configuration Commands
" ============================================================================

command! -nargs=1 HanzoModel call hanzo#SetModel(<q-args>)
command! -nargs=1 HanzoMode call hanzo#SetMode(<q-args>)
command! HanzoModels call hanzo#Models()
command! HanzoVersion call hanzo#Version()

" ============================================================================
" AI Login (multi-vendor: Claude / ChatGPT / Hanzo / API key)
" ============================================================================

command! -nargs=? -complete=customlist,hanzo#LoginComplete AILogin call hanzo#Login(<f-args>)
command! AILogout call hanzo#Logout()
command! AIStatus call hanzo#Status()
command! AIWhoami call hanzo#Status()
" Back-compat: :HanzoLogin is :AILogin hanzo
command! HanzoLogin call hanzo#Login('hanzo')

" ============================================================================
" Mappings
" ============================================================================

" <Plug> mappings
nnoremap <silent> <Plug>(hanzo_prompt) :call hanzo#Chat(input('Hanzo> '))<CR>
nnoremap <silent> <Plug>(hanzo_complete) :HanzoComplete<CR>
vnoremap <silent> <Plug>(hanzo_explain) :HanzoExplain<CR>
vnoremap <silent> <Plug>(hanzo_refactor) :call hanzo#Refactor(input('Refactor: '))<CR>
vnoremap <silent> <Plug>(hanzo_fix) :HanzoFix<CR>
vnoremap <silent> <Plug>(hanzo_tests) :HanzoTests<CR>
vnoremap <silent> <Plug>(hanzo_docs) :HanzoDocs<CR>
vnoremap <silent> <Plug>(hanzo_review) :HanzoReview<CR>
vnoremap <silent> <Plug>(hanzo_eval) :HanzoEvalSelection<CR>
nnoremap <silent> <Plug>(hanzo_eval_line) :HanzoEvalLine<CR>

" Default keybinds (if enabled)
if g:hanzo_set_default_keybinds
    " Leader + h prefix for Hanzo commands
    if !hasmapto('<Plug>(hanzo_prompt)', 'n')
        nmap <Leader>h <Plug>(hanzo_prompt)
    endif
    if !hasmapto('<Plug>(hanzo_complete)', 'n')
        nmap <Leader>hc <Plug>(hanzo_complete)
    endif
    if !hasmapto('<Plug>(hanzo_explain)', 'v')
        vmap <Leader>he <Plug>(hanzo_explain)
    endif
    if !hasmapto('<Plug>(hanzo_refactor)', 'v')
        vmap <Leader>hr <Plug>(hanzo_refactor)
    endif
    if !hasmapto('<Plug>(hanzo_fix)', 'v')
        vmap <Leader>hf <Plug>(hanzo_fix)
    endif
    if !hasmapto('<Plug>(hanzo_tests)', 'v')
        vmap <Leader>ht <Plug>(hanzo_tests)
    endif
    if !hasmapto('<Plug>(hanzo_docs)', 'v')
        vmap <Leader>hd <Plug>(hanzo_docs)
    endif
    if !hasmapto('<Plug>(hanzo_review)', 'v')
        vmap <Leader>hv <Plug>(hanzo_review)
    endif
    if !hasmapto('<Plug>(hanzo_eval)', 'v')
        vmap <Leader>hx <Plug>(hanzo_eval)
    endif
    if !hasmapto('<Plug>(hanzo_eval_line)', 'n')
        nmap <Leader>hx <Plug>(hanzo_eval_line)
    endif
endif

" ============================================================================
" Auto-commands
" ============================================================================

" Auto-start bridge if configured
if g:hanzo_auto_start
    augroup HanzoAutoStart
        autocmd!
        autocmd VimEnter * call hanzo#StartBridge()
    augroup END
endif

" Clean up on exit
augroup HanzoCleanup
    autocmd!
    autocmd VimLeavePre * call hanzo#StopBridge()
augroup END
