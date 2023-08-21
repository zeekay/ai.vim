
" Author: evanmcneely <evanmcneely@me.com>
" Description: Pre-processing rules for Vimscript files.

function! neural#pre_process#vim#Process(buffer, input) abort
    let a:input.prompt = 'You are working in vimscript. '
    \   . a:input.prompt
    \   . '\n\n'
    \   . a:buffer
endfunction


