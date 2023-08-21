" Author: evanmcneely <evanmcneely@me.com>
" Description: Pre-processing rules for TypeScript files.

function! neural#pre_process#typescript#Process(buffer, input) abort
    let a:input.prompt = 'You are working in TypeScript. '
    \   . a:input.prompt
    \   . '\n\n"""\n\n'
    \   . a:buffer
endfunction

