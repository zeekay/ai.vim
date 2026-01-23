" Hanzo AI source for Neural
" Supports: Direct API, MCP/ZAP bridge, Ollama

let s:script = expand('<sfile>:p:h:h:h:h') . '/neural_sources/hanzo.py'

function! neural#source#hanzo#Get() abort
    return {
    \   'name': 'Hanzo',
    \   'script_language': 'python',
    \   'script': s:script,
    \}
endfunction
