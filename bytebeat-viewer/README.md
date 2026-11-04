# Bytebeat Viewer (Windows)

A small native Windows app that plays one bytebeat and shows dollchan's
**Combined** view (white waveform over the blue diagram, 1024×256, draw scale 5).
No browser or webview: the formula runs in an embedded QuickJS engine with the
same JavaScript setup dollchan uses (Math functions as globals, `int`, `window`,
Bytebeat / Signed Bytebeat / Floatbeat / Funcbeat modes, stereo arrays).

## Change the song

    python3 make_song.py "https://dollchan.net/bytebeat/#v3b64...."      # paste a dollchan link
    python3 make_song.py --code "t*(t>>5|t>>8)" --rate 8000 --mode Bytebeat --title "My song"
    ./build.sh

## Build

Linux: `sudo apt install g++-mingw-w64-x86-64` then `./build.sh`.
Windows: MSYS2 MinGW64 shell, `CC=gcc CXX=g++ ./build.sh`.

## Keys

Space pause/resume · R restart · Up/Down volume · Left/Right zoom · F11 fullscreen · Esc quit
