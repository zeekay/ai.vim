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
    \   'mode': get(g:, 'hanzo_mode', 'api'),
    \   'llm_gateway': get(g:, 'hanzo_llm_gateway', 'http://localhost:4000'),
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
    " Configure Neural to use Hanzo provider
    let l:config = hanzo#GetConfig()

    " Set up Neural config
    if !exists('g:neural')
        let g:neural = {}
    endif

    let g:neural.providers = [{
    \   'type': 'hanzo',
    \   'model': l:config.model,
    \   'mode': l:config.mode,
    \   'url': l:config.llm_gateway,
    \}]

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
