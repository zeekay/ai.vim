" Author: evanmcneely <evanmcneely@me.com>
" Description: Pre-processing rules for python files.

function! neural#pre_process#python#Process(buffer, input) abort
    let a:input.prompt = 'You are working in Python. '
    \   . a:input.prompt
    \   . '\n\n"""\n\n'
    \   . a:buffer
endfunction

