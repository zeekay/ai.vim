" Author: evanmcneely <evanmcneely@me.com>
" Description: Pre-processing rules for JavaScript files.

function! neural#pre_process#javascriptreact#Process(buffer, input) abort
    let a:input.prompt = 'You are working in JavaScript and React. '
    \   . a:input.prompt
    \   . '\n\n"""\n\n'
    \   . a:buffer
endfunction
