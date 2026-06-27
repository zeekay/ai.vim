" Hanzo AI integration for Vim/Neovim
" Provides: MCP/ZAP bridge, REPL, IDE control, Browser integration
"
" This file extends Neural with Hanzo-specific functionality:
" - WebSocket bridge for AI agent control
" - REPL integration via Jupyter kernels
" - Additional AI-powered commands

let s:script_dir = expand('<sfile>:p:h:h')
let s:bridge_job = v:null
let s:bridge_channel = v:null
let s:pending = {}

" ============================================================================
" Configuration
" ============================================================================

function! hanzo#GetConfig() abort
    return {
    \   'port': get(g:, 'hanzo_port', 9228),
    \   'auto_start': get(g:, 'hanzo_auto_start', 0),
    \   'debug': get(g:, 'hanzo_debug', 0),
    \   'model': get(g:, 'hanzo_model', 'claude-sonnet-4-20250514'),
    \   'provider': get(g:, 'hanzo_provider', 'anthropic'),
    \   'provider_explicit': get(g:, 'hanzo_provider_explicit', 0),
    \   'mode': get(g:, 'hanzo_mode', 'api'),
    \   'route': get(g:, 'hanzo_route', 'auto'),
    \   'local_url': get(g:, 'hanzo_local_url', 'http://127.0.0.1:36900'),
    \   'local_model': get(g:, 'hanzo_local_model', 'default'),
    \   'cloud_url': get(g:, 'hanzo_cloud_url', 'https://api.hanzo.ai'),
    \   'llm_gateway': get(g:, 'hanzo_llm_gateway', ''),
    \}
endfunction

" Build the Neural provider entry for the Hanzo provider, carrying the routing
" config the Python provider needs (g:hanzo_route + the endpoints). This is the
" single source for both :AI (default registration) and :Hanzo (hanzo#Chat).
function! hanzo#NeuralProvider() abort
    let l:config = hanzo#GetConfig()

    return {
    \   'type': 'hanzo',
    \   'mode': l:config.mode,
    \   'provider': l:config.provider,
    \   'provider_explicit': l:config.provider_explicit,
    \   'model': l:config.model,
    \   'route': l:config.route,
    \   'local_url': l:config.local_url,
    \   'local_model': l:config.local_model,
    \   'cloud_url': l:config.cloud_url,
    \   'llm_gateway': l:config.llm_gateway,
    \}
endfunction

" ============================================================================
" Bridge Management (for AI Agent Control)
" ============================================================================

function! hanzo#StartBridge() abort
    if s:bridge_job != v:null
        echo "Hanzo bridge already running"
        return
    endif

    let l:config = hanzo#GetConfig()
    let l:bridge_script = s:script_dir . '/python3/bridge.py'

    if !filereadable(l:bridge_script)
        echoerr "Hanzo bridge script not found: " . l:bridge_script
        return
    endif

    let s:bridge_job = job_start(['python3', l:bridge_script, string(l:config.port)], {
    \   'out_cb': function('s:OnBridgeOutput'),
    \   'err_cb': function('s:OnBridgeError'),
    \   'exit_cb': function('s:OnBridgeExit'),
    \})

    if job_status(s:bridge_job) == 'run'
        echo "Hanzo bridge started on port " . l:config.port
        " Connect after brief delay
        call timer_start(500, {-> s:ConnectBridge()})
    else
        echoerr "Failed to start Hanzo bridge"
        let s:bridge_job = v:null
    endif
endfunction

function! hanzo#StopBridge() abort
    if s:bridge_channel != v:null
        call ch_close(s:bridge_channel)
        let s:bridge_channel = v:null
    endif

    if s:bridge_job != v:null
        call job_stop(s:bridge_job)
        let s:bridge_job = v:null
        echo "Hanzo bridge stopped"
    endif
endfunction

function! hanzo#BridgeStatus() abort
    let l:config = hanzo#GetConfig()

    if s:bridge_job == v:null
        echo "Hanzo bridge: not running"
    elseif job_status(s:bridge_job) == 'run'
        echo "Hanzo bridge: running on port " . l:config.port
        if s:bridge_channel != v:null && ch_status(s:bridge_channel) == 'open'
            echo "  Channel: connected"
        else
            echo "  Channel: disconnected"
        endif
    else
        echo "Hanzo bridge: " . job_status(s:bridge_job)
    endif
endfunction

function! s:ConnectBridge() abort
    let l:config = hanzo#GetConfig()

    try
        let s:bridge_channel = ch_open('localhost:' . l:config.port, {
        \   'mode': 'json',
        \   'callback': function('s:OnBridgeMessage'),
        \})
        if ch_status(s:bridge_channel) == 'open'
            if l:config.debug
                echo "Hanzo bridge connected"
            endif
        endif
    catch
        " Retry connection
        call timer_start(1000, {-> s:ConnectBridge()})
    endtry
endfunction

function! s:OnBridgeMessage(channel, msg) abort
    let l:config = hanzo#GetConfig()

    if l:config.debug
        echom "Hanzo recv: " . string(a:msg)
    endif

    let l:id = get(a:msg, 'id', '')
    let l:action = get(a:msg, 'action', '')

    " Handle pending responses
    if l:id != '' && has_key(s:pending, l:id)
        let l:Callback = s:pending[l:id]
        unlet s:pending[l:id]
        call l:Callback(a:msg)
        return
    endif

    " Handle incoming requests from AI agent
    call hanzo#HandleRequest(a:msg)
endfunction

function! s:OnBridgeOutput(channel, msg) abort
    if hanzo#GetConfig().debug
        echom "Hanzo: " . a:msg
    endif
endfunction

function! s:OnBridgeError(channel, msg) abort
    echoerr "Hanzo error: " . a:msg
endfunction

function! s:OnBridgeExit(job, status) abort
    let s:bridge_job = v:null
    let s:bridge_channel = v:null
    if hanzo#GetConfig().debug
        echom "Hanzo bridge exited with status " . a:status
    endif
endfunction

" ============================================================================
" Bridge Communication
" ============================================================================

function! hanzo#Send(msg, ...) abort
    if s:bridge_channel == v:null || ch_status(s:bridge_channel) != 'open'
        echoerr "Hanzo bridge not connected"
        return
    endif

    let l:msg_id = ''
    if a:0 > 0
        " Generate unique ID for callback
        let l:msg_id = 'vim_' . localtime() . '_' . rand()
        let a:msg.id = l:msg_id
        let s:pending[l:msg_id] = a:1
    endif

    call ch_sendexpr(s:bridge_channel, a:msg)
    return l:msg_id
endfunction

function! hanzo#HandleRequest(msg) abort
    let l:action = get(a:msg, 'action', '')
    let l:id = get(a:msg, 'id', '')

    " File operations
    if l:action == 'file.info'
        call s:Reply(l:id, hanzo#GetFileInfo())
    elseif l:action == 'file.open'
        call hanzo#OpenFile(a:msg.path, get(a:msg, 'line', 1))
        call s:Reply(l:id, {'success': 1})
    elseif l:action == 'file.save'
        write
        call s:Reply(l:id, {'success': 1})
    elseif l:action == 'file.close'
        bdelete
        call s:Reply(l:id, {'success': 1})

    " Editor operations
    elseif l:action == 'editor.selection'
        call s:Reply(l:id, {'text': hanzo#GetSelection()})
    elseif l:action == 'editor.insert'
        call hanzo#Insert(a:msg.text, a:msg.line, get(a:msg, 'column', 1))
        call s:Reply(l:id, {'success': 1})
    elseif l:action == 'editor.replace'
        call hanzo#Replace(a:msg.text, a:msg.line, a:msg.column, a:msg.endLine, a:msg.endColumn)
        call s:Reply(l:id, {'success': 1})
    elseif l:action == 'editor.goto'
        call hanzo#GoTo(a:msg.line, get(a:msg, 'column', 1))
        call s:Reply(l:id, {'success': 1})
    elseif l:action == 'editor.text'
        let l:lines = getline(get(a:msg, 'line', 1), get(a:msg, 'endLine', '$'))
        call s:Reply(l:id, {'text': join(l:lines, "\n")})

    " Vim commands
    elseif l:action == 'command'
        execute a:msg.command
        call s:Reply(l:id, {'success': 1})

    " Diagnostics (via ALE or built-in)
    elseif l:action == 'diagnostics'
        call s:Reply(l:id, hanzo#GetDiagnostics())

    " Unknown action
    else
        if hanzo#GetConfig().debug
            echom "Unknown action: " . l:action
        endif
    endif
endfunction

function! s:Reply(id, data) abort
    if a:id != ''
        let l:response = extend({'id': a:id}, a:data)
        call hanzo#Send(l:response)
    endif
endfunction

" ============================================================================
" Editor Operations
" ============================================================================

function! hanzo#GetFileInfo() abort
    return {
    \   'path': expand('%:p'),
    \   'name': expand('%:t'),
    \   'line': line('.'),
    \   'column': col('.'),
    \   'modified': &modified,
    \   'filetype': &filetype,
    \   'bufnr': bufnr('%'),
    \   'winnr': winnr(),
    \}
endfunction

function! hanzo#GetSelection() abort
    let [l:lnum1, l:col1] = getpos("'<")[1:2]
    let [l:lnum2, l:col2] = getpos("'>")[1:2]
    let l:lines = getline(l:lnum1, l:lnum2)
    if len(l:lines) == 0
        return ''
    endif
    let l:lines[-1] = l:lines[-1][:l:col2 - 1]
    let l:lines[0] = l:lines[0][l:col1 - 1:]
    return join(l:lines, "\n")
endfunction

function! hanzo#Insert(text, line, col) abort
    call cursor(a:line, a:col)
    execute "normal! i" . a:text
endfunction

function! hanzo#Replace(text, line1, col1, line2, col2) abort
    call cursor(a:line1, a:col1)
    execute "normal! v"
    call cursor(a:line2, a:col2)
    execute "normal! c" . a:text
endfunction

function! hanzo#GoTo(line, col) abort
    call cursor(a:line, a:col)
    normal! zz
endfunction

function! hanzo#OpenFile(path, ...) abort
    execute 'edit ' . fnameescape(a:path)
    if a:0 > 0
        call cursor(a:1, 1)
        normal! zz
    endif
endfunction

function! hanzo#GetDiagnostics() abort
    let l:diagnostics = []

    " Try ALE first
    if exists('*ale#engine#GetLoclist')
        let l:ale_items = ale#engine#GetLoclist(bufnr('%'))
        for l:item in l:ale_items
            call add(l:diagnostics, {
            \   'line': l:item.lnum,
            \   'column': l:item.col,
            \   'message': l:item.text,
            \   'severity': l:item.type == 'E' ? 'error' : 'warning',
            \   'source': get(l:item, 'linter_name', 'ale'),
            \})
        endfor
    endif

    " Try built-in diagnostics (Vim 9+ / Neovim)
    if has('nvim')
        lua << EOF
        local diags = vim.diagnostic.get(0)
        for _, d in ipairs(diags) do
            local severity = "info"
            if d.severity == vim.diagnostic.severity.ERROR then
                severity = "error"
            elseif d.severity == vim.diagnostic.severity.WARN then
                severity = "warning"
            end
            vim.fn.add(vim.g.hanzo_diagnostics or {}, {
                line = d.lnum + 1,
                column = d.col + 1,
                message = d.message,
                severity = severity,
                source = d.source or "nvim",
            })
        end
EOF
        if exists('g:hanzo_diagnostics')
            let l:diagnostics = extend(l:diagnostics, g:hanzo_diagnostics)
            unlet g:hanzo_diagnostics
        endif
    endif

    return {'diagnostics': l:diagnostics}
endfunction

" ============================================================================
" AI Commands (extend Neural)
" ============================================================================

function! hanzo#Chat(prompt) abort
    " Route :Hanzo/:H through the Hanzo provider with local-first routing.
    if !exists('g:neural')
        let g:neural = {}
    endif

    let g:neural.providers = [hanzo#NeuralProvider()]

    " Forward to Neural
    call neural#Prompt(a:prompt)
endfunction

function! hanzo#Complete() abort
    " Get context around cursor
    let l:line = line('.')
    let l:col = col('.')
    let l:context_start = max([1, l:line - 20])
    let l:context_end = min([line('$'), l:line + 5])
    let l:context = join(getline(l:context_start, l:context_end), "\n")

    let l:prompt = printf("Complete the code at line %d, column %d. Context:\n\n```%s\n%s\n```\n\nProvide only the completion, no explanation.",
    \   l:line, l:col, &filetype, l:context)

    call hanzo#Chat(l:prompt)
endfunction

function! hanzo#Explain() abort
    let l:selection = hanzo#GetSelection()
    if empty(l:selection)
        echoerr "No selection"
        return
    endif

    let l:prompt = printf("Explain this %s code:\n\n```%s\n%s\n```",
    \   &filetype, &filetype, l:selection)

    call hanzo#Chat(l:prompt)
endfunction

function! hanzo#Refactor(instruction) abort
    let l:selection = hanzo#GetSelection()
    if empty(l:selection)
        echoerr "No selection"
        return
    endif

    let l:prompt = printf("Refactor this %s code according to: %s\n\n```%s\n%s\n```\n\nProvide only the refactored code.",
    \   &filetype, a:instruction, &filetype, l:selection)

    call hanzo#Chat(l:prompt)
endfunction

function! hanzo#Fix() abort
    let l:selection = hanzo#GetSelection()
    if empty(l:selection)
        " Use current line
        let l:selection = getline('.')
    endif

    let l:prompt = printf("Fix any bugs or issues in this %s code:\n\n```%s\n%s\n```\n\nProvide only the fixed code.",
    \   &filetype, &filetype, l:selection)

    call hanzo#Chat(l:prompt)
endfunction

function! hanzo#Tests() abort
    let l:selection = hanzo#GetSelection()
    if empty(l:selection)
        echoerr "No selection"
        return
    endif

    let l:prompt = printf("Write comprehensive tests for this %s code:\n\n```%s\n%s\n```",
    \   &filetype, &filetype, l:selection)

    call hanzo#Chat(l:prompt)
endfunction

function! hanzo#Docs() abort
    let l:selection = hanzo#GetSelection()
    if empty(l:selection)
        echoerr "No selection"
        return
    endif

    let l:prompt = printf("Add documentation/comments to this %s code:\n\n```%s\n%s\n```\n\nProvide the code with documentation added.",
    \   &filetype, &filetype, l:selection)

    call hanzo#Chat(l:prompt)
endfunction

function! hanzo#Review() abort
    let l:selection = hanzo#GetSelection()
    if empty(l:selection)
        " Review entire buffer
        let l:selection = join(getline(1, '$'), "\n")
    endif

    let l:prompt = printf("Review this %s code for bugs, performance issues, and improvements:\n\n```%s\n%s\n```",
    \   &filetype, &filetype, l:selection)

    call hanzo#Chat(l:prompt)
endfunction

" ============================================================================
" REPL Integration
" ============================================================================

function! hanzo#Repl(lang) abort
    call hanzo#Send({
    \   'action': 'repl.start',
    \   'language': a:lang,
    \})
endfunction

function! hanzo#Eval(code) abort
    call hanzo#Send({
    \   'action': 'repl.eval',
    \   'code': a:code,
    \})
endfunction

function! hanzo#EvalSelection() abort
    let l:code = hanzo#GetSelection()
    if !empty(l:code)
        call hanzo#Eval(l:code)
    endif
endfunction

function! hanzo#EvalLine() abort
    let l:code = getline('.')
    if !empty(l:code)
        call hanzo#Eval(l:code)
    endif
endfunction

" ============================================================================
" Model Selection
" ============================================================================

function! hanzo#SetModel(model) abort
    let g:hanzo_model = a:model
    echo "Hanzo model set to: " . a:model
endfunction

function! hanzo#SetMode(mode) abort
    if a:mode =~ '^\(api\|mcp\|ollama\)$'
        let g:hanzo_mode = a:mode
        echo "Hanzo mode set to: " . a:mode
    else
        echoerr "Invalid mode. Use: api, mcp, or ollama"
    endif
endfunction

function! hanzo#Models() abort
    echo "Available models:"
    echo ""
    echo "  Anthropic:"
    echo "    claude-sonnet-4-20250514 (default)"
    echo "    claude-opus-4-20250514"
    echo "    claude-3-5-sonnet-20241022"
    echo ""
    echo "  OpenAI:"
    echo "    gpt-4-turbo"
    echo "    gpt-4o"
    echo "    o1-preview"
    echo ""
    echo "  Google:"
    echo "    gemini-1.5-pro"
    echo "    gemini-1.5-flash"
    echo ""
    echo "  Ollama (local):"
    echo "    ollama:llama3.2"
    echo "    ollama:codellama"
    echo "    ollama:deepseek-coder"
    echo ""
    echo "Current: " . get(g:, 'hanzo_model', 'claude-sonnet-4-20250514')
    echo "Mode: " . get(g:, 'hanzo_mode', 'api')
endfunction

function! hanzo#Version() abort
    echo "hanzo.vim v0.1.0"
    echo "  Neural integration: " . (exists('g:loaded_neural') ? 'yes' : 'no')
    echo "  Bridge: " . (s:bridge_job != v:null ? 'running' : 'stopped')
    echo "  Model: " . get(g:, 'hanzo_model', 'claude-sonnet-4-20250514')
    echo "  Mode: " . get(g:, 'hanzo_mode', 'api')
endfunction

" ============================================================================
" AI Login (multi-vendor: Claude / ChatGPT / Hanzo / API key)
" ============================================================================
"
" Not vendor-locked. OAuth/device-code flows are delegated to the installed
" `dev` CLI (Hanzo Dev), and the provider shares its credential stores
" (~/.codex/auth.json, ~/.hanzo/auth.json) and the
" ANTHROPIC_API_KEY/OPENAI_API_KEY/HANZO_API_KEY env vars. We never echo,
" log, or place a key on a command line: keys are read via inputsecret() and
" piped to `dev` over stdin; `dev` owns the on-disk secure store (0600).

function! s:DevCli() abort
    return get(g:, 'ai_cli', 'dev')
endfunction

function! s:HasDev() abort
    return executable(s:DevCli())
endfunction

" The environment variable the provider reads back for each vendor.
function! s:ProviderEnvVar(provider) abort
    if a:provider ==# 'anthropic'
        return 'ANTHROPIC_API_KEY'
    elseif a:provider ==# 'openai'
        return 'OPENAI_API_KEY'
    elseif a:provider ==# 'hanzo'
        return 'HANZO_API_KEY'
    endif

    return ''
endfunction

" Normalise a vendor name to one of: claude, chatgpt, hanzo, apikey.
function! s:NormalizeVendor(vendor) abort
    let l:v = tolower(trim(a:vendor))

    if l:v ==# 'anthropic'
        return 'claude'
    elseif l:v ==# 'openai' || l:v ==# 'gpt'
        return 'chatgpt'
    elseif l:v ==# 'key' || l:v ==# 'api-key' || l:v ==# 'api_key'
        return 'apikey'
    endif

    return l:v
endfunction

" Build the `dev login ...` argv for OAuth/device-code vendors.
" Returns [] for the key-based vendors (claude/apikey).
function! hanzo#LoginArgv(vendor) abort
    let l:v = s:NormalizeVendor(a:vendor)

    if l:v ==# 'hanzo'
        return [s:DevCli(), 'login', '--device-code']
    elseif l:v ==# 'chatgpt'
        return [s:DevCli(), 'login', '--chatgpt', '--device-code']
    endif

    return []
endfunction

function! s:OnLoginExit(...) abort
    call hanzo#Status()
endfunction

" Run an interactive command in a terminal so the device code + URL render
" and the OAuth callback can complete.
function! s:RunTerminal(argv) abort
    if has('nvim')
        new
        call termopen(a:argv, {'on_exit': function('s:OnLoginExit')})
        startinsert
    elseif exists('*term_start')
        call term_start(a:argv, {
        \   'term_name': 'AILogin',
        \   'exit_cb': function('s:OnLoginExit'),
        \})
    else
        " No +terminal: run synchronously as a last resort.
        call system(join(map(copy(a:argv), 'shellescape(v:val)'), ' '))
        call hanzo#Status()
    endif
endfunction

" Write an auth.json matching the schema `dev` writes for API-key auth.
function! s:WriteAuthJson(path, key) abort
    let l:dir = fnamemodify(a:path, ':h')

    if !isdirectory(l:dir)
        call mkdir(l:dir, 'p', 0700)
    endif

    call writefile([json_encode({'auth_mode': 'apikey', 'OPENAI_API_KEY': a:key})], a:path)
    call setfperm(a:path, 'rw-------')
endfunction

" Fallback when `dev` is absent: persist the key where the provider reads it.
function! s:PersistKeyNoDev(provider, key) abort
    let l:env = s:ProviderEnvVar(a:provider)

    if a:provider ==# 'openai'
        call s:WriteAuthJson(expand('~/.codex/auth.json'), a:key)
        echo 'Wrote ~/.codex/auth.json (0600).'
    elseif a:provider ==# 'hanzo'
        call s:WriteAuthJson(expand('~/.hanzo/auth.json'), a:key)
        echo 'Wrote ~/.hanzo/auth.json (0600).'
    endif

    if !empty(l:env)
        echo 'To persist across sessions, add to your shell profile:'
        echo '  export ' . l:env . '=<your key>'
    endif

    echo 'Install the `dev` CLI for OAuth logins: https://github.com/hanzoai/dev'
endfunction

" Prompt for an API key (inputsecret) and store it for `provider`.
function! s:LoginApiKey(provider) abort
    let l:provider = empty(a:provider)
    \   ? get(g:, 'hanzo_provider', 'anthropic')
    \   : a:provider
    let l:key = inputsecret('Enter ' . l:provider . ' API key: ')

    if empty(l:key)
        if l:provider ==# 'anthropic'
            echo 'No key entered. Set $ANTHROPIC_API_KEY or run :AILogin claude again.'
        else
            echo 'No key entered.'
        endif

        return
    endif

    " Make the key available to the in-session provider immediately. The
    " value never appears in the :execute string (only the variable name).
    let l:env = s:ProviderEnvVar(l:provider)

    if !empty(l:env)
        execute 'let $' . l:env . ' = l:key'
    endif

    let g:hanzo_provider = l:provider
    " Logging in is a deliberate provider choice: let auto-routing honor it.
    let g:hanzo_provider_explicit = 1

    if s:HasDev()
        " Pipe the key via stdin: never on the command line or in history.
        call system(s:DevCli() . ' login --with-api-key', l:key)
        echo 'Stored ' . l:provider . ' key via ' . s:DevCli() . '.'
        call hanzo#Status()
    else
        call s:PersistKeyNoDev(l:provider, l:key)
    endif
endfunction

" Start an OAuth/device-code flow via `dev`, falling back to API key.
function! s:LoginOAuth(vendor) abort
    if !s:HasDev()
        echo 'The `dev` CLI is required for OAuth logins but was not found on PATH.'
        echo 'Falling back to API-key login for the active provider.'
        call s:LoginApiKey(get(g:, 'hanzo_provider', 'anthropic'))

        return
    endif

    let g:hanzo_provider = s:NormalizeVendor(a:vendor) ==# 'hanzo'
    \   ? 'hanzo'
    \   : 'openai'
    " Logging in is a deliberate provider choice: let auto-routing honor it.
    let g:hanzo_provider_explicit = 1
    echo 'Starting ' . a:vendor . ' login via '
    \   . s:DevCli() . ' (device-code)...'
    call s:RunTerminal(hanzo#LoginArgv(a:vendor))
endfunction

" :AILogin [vendor] -- interactive menu when no vendor is given.
function! hanzo#Login(...) abort
    let l:vendor = a:0 > 0 ? s:NormalizeVendor(a:1) : ''

    if empty(l:vendor)
        let l:choice = inputlist([
        \   'Select AI login:',
        \   '1) Claude (Anthropic API key)',
        \   '2) ChatGPT (OpenAI OAuth, device-code)',
        \   '3) Hanzo (hanzo.id OAuth, device-code)',
        \   '4) API key (active provider)',
        \])
        echo "\n"

        if l:choice == 1
            let l:vendor = 'claude'
        elseif l:choice == 2
            let l:vendor = 'chatgpt'
        elseif l:choice == 3
            let l:vendor = 'hanzo'
        elseif l:choice == 4
            let l:vendor = 'apikey'
        else
            echo 'AILogin cancelled.'

            return
        endif
    endif

    if l:vendor ==# 'hanzo' || l:vendor ==# 'chatgpt'
        call s:LoginOAuth(l:vendor)
    elseif l:vendor ==# 'claude'
        call s:LoginApiKey('anthropic')
    elseif l:vendor ==# 'apikey'
        call s:LoginApiKey(get(g:, 'hanzo_provider', 'anthropic'))
    else
        echohl ErrorMsg
        echomsg 'Unknown AILogin vendor: ' . l:vendor
        \   . ' (use claude|chatgpt|hanzo|apikey)'
        echohl None
    endif
endfunction

" :AILogout -- clear the shared credential stores via `dev`.
function! hanzo#Logout() abort
    if s:HasDev()
        echo system(s:DevCli() . ' logout')
    else
        echo s:DevCli() . ' CLI not found; unset API key env vars to log out.'
    endif
endfunction

" Ask the Python provider which endpoint a request would use right now (it
" probes the local engine /health). Returns {} when it cannot be determined.
function! hanzo#ResolveRoute() abort
    let l:script = s:script_dir . '/src/neural/provider/hanzo.py'

    if !filereadable(l:script)
        return {}
    endif

    let l:input = json_encode({'config': hanzo#NeuralProvider()})
    let l:out = system('python3 ' . shellescape(l:script) . ' --resolve', l:input)

    if v:shell_error != 0 || empty(l:out)
        return {}
    endif

    try
        let l:parsed = json_decode(l:out)
    catch
        return {}
    endtry

    return type(l:parsed) == v:t_dict ? l:parsed : {}
endfunction

" :AIStatus / :AIWhoami -- show the active route, login state, and provider.
function! hanzo#Status() abort
    let l:route = hanzo#ResolveRoute()

    if empty(l:route)
        echo 'route: unknown (could not probe local engine)'
    elseif get(l:route, 'route', '') ==# 'local'
        echo printf('route=local engine %s (%s) [UP]',
        \   get(l:route, 'base_url', ''), get(l:route, 'model', ''))
    else
        let l:note = get(l:route, 'authenticated', v:false)
        \   ? '' : ' [no credential]'
        echo printf('route=cloud provider=%s (cloud %s)%s',
        \   get(l:route, 'provider', ''), get(l:route, 'base_url', ''), l:note)
    endif

    if s:HasDev()
        " `dev login status` reports state only; it never prints the secret.
        echo system(s:DevCli() . ' login status')
    else
        echo s:DevCli() . ' CLI not found; using env/config credentials.'
    endif

    echo 'Active provider: ' . get(g:, 'hanzo_provider', 'anthropic')
endfunction

" Command-line completion for :AILogin.
function! hanzo#LoginComplete(arglead, cmdline, cursorpos) abort
    let l:matches = []

    for l:vendor in ['claude', 'chatgpt', 'hanzo', 'apikey']
        if stridx(l:vendor, a:arglead) == 0
            call add(l:matches, l:vendor)
        endif
    endfor

    return l:matches
endfunction
