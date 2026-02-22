" Hanzo AI provider for Neural
" Supports: Direct API, MCP/ZAP bridge, Ollama

function! neural#provider#hanzo#Get() abort
    return {
    \   'name': 'hanzo',
    \   'script_language': 'python',
    \   'script': neural#GetScriptDir() . '/hanzo.py',
    \}
endfunction
