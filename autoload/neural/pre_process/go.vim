" Author: w0rp <devw0rp@gmail.com>
" Description: Pre-processing rules for Go files.

function! neural#pre_process#go#Process(buffer, input) abort
    let l:has_package = search('^package ', 'wnc') != 0

    let a:input.prompt = 'You are working in golang. '
    \   . (l:has_package ? 'Do not write package main or main func. ' : '')
    \   . a:input.prompt
    \   . '. Here is some context you can work with:\n\n' 
    \   . a:buffer
endfunction
