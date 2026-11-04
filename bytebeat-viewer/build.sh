#!/bin/sh
# Cross-compile BytebeatViewer.exe with MinGW-w64 (apt install g++-mingw-w64-x86-64).
# On Windows with MSYS2/MinGW, the same commands work with gcc/g++ instead of the prefixed names.
set -e
CC=${CC:-x86_64-w64-mingw32-gcc}
CXX=${CXX:-x86_64-w64-mingw32-g++}
mkdir -p build
Q=third_party/quickjs
for f in quickjs dtoa libregexp libunicode cutils; do
  [ build/$f.o -nt $Q/$f.c ] || $CC -O2 -c $Q/$f.c -o build/$f.o -D_GNU_SOURCE -DCONFIG_VERSION=\"$(cat $Q/VERSION)\" -w
done
$CXX -O2 -std=c++17 -I$Q main.cpp build/quickjs.o build/dtoa.o build/libregexp.o build/libunicode.o build/cutils.o \
  -o BytebeatViewer.exe -mwindows -static -lwinmm -lgdi32 -luser32 -Wl,-Bstatic -lpthread
echo built BytebeatViewer.exe
