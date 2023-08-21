" Author: evanmcneely <evanmcneely@me.com>
" Description: Pre-processing rules for lua files.

function! neural#pre_process#lua#Process(buffer, input) abort
    let a:input.prompt = 'You are working in Lua. ' 
    \   . a:input.prompt
    \   . '\n\n"""\n\n'
    \   . a:buffer
endfunction

