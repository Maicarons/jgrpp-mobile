#!/usr/bin/env bash
# Cross-compile jgrpp-mobile for OpenHarmony/HarmonyOS (arm64-v8a).
#
# Produces libopenttd.so plus its dependencies (SDL3 with the OHOS backend,
# sdl2-compat, zlib, libpng, freetype, lzo, liblzma) and copies them into
# harmony/app/entry/libs/arm64-v8a/ for DevEco Studio / hvigor packaging.
#
# Requirements on PATH (or override via env):
#   cmake, ninja or make, git, wget/curl, tar
# Env overrides:
#   OHOS_NATIVE_SDK   path to the native OHOS SDK (default: auto-detect DevEco)
#   OHOS_ARCH         arm64-v8a (default) | armeabi-v7a | x86_64
#   SDL_OHOS_REPO     SDL source repo with the OHOS port (default: libsdl-org/SDL PR #13152 branch)
set -euo pipefail

HARMONY_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$(cd "$HARMONY_DIR/.." && pwd)"
WORK_DIR="${WORK_DIR:-$HARMONY_DIR/build}"
OHOS_ARCH="${OHOS_ARCH:-arm64-v8a}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 8)}"

if [ -z "${OHOS_NATIVE_SDK:-}" ]; then
    for CANDIDATE in \
        "/g/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/native" \
        "$LOCALAPPDATA/Huawei/Sdk/default/openharmony/native" \
        /opt/native; do
        if [ -f "$CANDIDATE/build/cmake/ohos.toolchain.cmake" ]; then
            OHOS_NATIVE_SDK="$CANDIDATE"
            break
        fi
    done
fi
if [ -z "${OHOS_NATIVE_SDK:-}" ] || [ ! -f "$OHOS_NATIVE_SDK/build/cmake/ohos.toolchain.cmake" ]; then
    echo "ERROR: OHOS native SDK not found; set OHOS_NATIVE_SDK" >&2
    exit 1
fi
TOOLCHAIN_FILE="$OHOS_NATIVE_SDK/build/cmake/ohos.toolchain.cmake"

PREFIX="$WORK_DIR/prefix/$OHOS_ARCH"
mkdir -p "$WORK_DIR/src" "$PREFIX"

fetch() { # fetch <url> <tarball-name>
    local url="$1" out="$WORK_DIR/src/$2"
    [ -f "$out" ] && return 0
    if command -v wget >/dev/null; then wget -q -O "$out" "$url"; else curl -sfL -o "$out" "$url"; fi
}

build_cmake() { # build_cmake <srcdir> <extra cmake args...>
    local srcdir="$1"; shift
    local builddir="$srcdir/build-ohos-$OHOS_ARCH"
    rm -rf "$builddir"
    cmake -S "$srcdir" -B "$builddir" -G Ninja \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
        -DOHOS_ARCH="$OHOS_ARCH" -DOHOS_PLATFORM=OHOS -DOHOS_STL=c++_shared \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_PLATFORM_NO_VERSIONED_SONAME=1 \
        "$@"
    cmake --build "$builddir" -j "$JOBS"
    cmake --install "$builddir"
}

echo "== [1/6] zlib =="
if [ ! -f "$PREFIX/lib/libz.a" ]; then
    fetch https://github.com/madler/zlib/archive/refs/tags/v1.3.1.tar.gz zlib-1.3.1.tar.gz
    rm -rf "$WORK_DIR/src/zlib"; mkdir -p "$WORK_DIR/src/zlib"
    tar -xzf "$WORK_DIR/src/zlib-1.3.1.tar.gz" -C "$WORK_DIR/src/zlib" --strip-components=1
    build_cmake "$WORK_DIR/src/zlib"
fi

echo "== [2/6] freetype / lzo / liblzma =="
if [ ! -f "$PREFIX/lib/libfreetype.a" ]; then
    fetch https://github.com/freetype/freetype/archive/refs/tags/VER-2-13-3.tar.gz freetype-2.13.3.tar.gz
    rm -rf "$WORK_DIR/src/freetype"; mkdir -p "$WORK_DIR/src/freetype"
    tar -xzf "$WORK_DIR/src/freetype-2.13.3.tar.gz" -C "$WORK_DIR/src/freetype" --strip-components=1
    build_cmake "$WORK_DIR/src/freetype" -DFT_DISABLE_HARFBUZZ=ON -DFT_DISABLE_BROTLI=ON -DFT_DISABLE_PNG=ON -DFT_DISABLE_ZLIB=OFF -DBUILD_SHARED_LIBS=OFF
fi
if [ ! -f "$PREFIX/lib/liblzo2.a" ]; then
    fetch https://www.oberhumer.com/opensource/lzo/download/lzo-2.10.tar.gz lzo-2.10.tar.gz
    rm -rf "$WORK_DIR/src/lzo"; mkdir -p "$WORK_DIR/src/lzo"
    tar -xzf "$WORK_DIR/src/lzo-2.10.tar.gz" -C "$WORK_DIR/src/lzo" --strip-components=1
    build_cmake "$WORK_DIR/src/lzo" -DENABLE_SHARED=OFF -DENABLE_STATIC=ON
fi
if [ ! -f "$PREFIX/lib/liblzma.a" ]; then
    fetch https://github.com/tukaani-project/xz/releases/download/v5.4.6/xz-5.4.6.tar.gz xz-5.4.6.tar.gz
    rm -rf "$WORK_DIR/src/xz"; mkdir -p "$WORK_DIR/src/xz"
    tar -xzf "$WORK_DIR/src/xz-5.4.6.tar.gz" -C "$WORK_DIR/src/xz" --strip-components=1
    build_cmake "$WORK_DIR/src/xz" -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=OFF
fi

echo "== [3/6] SDL3 (OpenHarmony backend, PR #13152) =="
if [ ! -d "$WORK_DIR/src/SDL-ohos" ]; then
    git clone --depth 1 https://github.com/libsdl-org/SDL.git "$WORK_DIR/src/SDL-ohos"
    git -C "$WORK_DIR/src/SDL-ohos" fetch --depth 1 origin pull/13152/head:ohos
    git -C "$WORK_DIR/src/SDL-ohos" checkout ohos
fi
if [ ! -f "$PREFIX/lib/libSDL3.so" ]; then
    build_cmake "$WORK_DIR/src/SDL-ohos" -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST_LIBRARY=OFF -DSDL_TESTS=OFF
fi

echo "== [4/6] sdl2-compat (SDL2 API on top of SDL3) =="
if [ ! -d "$WORK_DIR/src/sdl2-compat" ]; then
    git clone --depth 1 https://github.com/libsdl-org/sdl2-compat.git "$WORK_DIR/src/sdl2-compat"
fi
if [ ! -f "$PREFIX/lib/libSDL2.so" ]; then
    build_cmake "$WORK_DIR/src/sdl2-compat" -DSDL2COMPAT_TESTS=OFF -DBUILD_SHARED_LIBS=ON \
        -DSDL2COMPAT_X11=OFF \
        -DSDL3_DIR="$PREFIX/lib/cmake/SDL3" \
        -DCMAKE_INSTALL_LIBDIR=lib
fi

echo "== [5/6] jgrpp (libopenttd.so) =="
# OhosSDL.cmake is consumed from CMAKE_MODULE_PATH like AndroidSDL.cmake.
cat > "$WORK_DIR/OhosSDL.cmake" <<EOF
# Generated by harmony/build-ohos.sh - points the OpenTTD build at the
# OHOS cross-compiled dependencies in $PREFIX
set(UNIX 1)
set(SDL2_DIR "$PREFIX/lib/cmake/SDL2" CACHE PATH "")
find_package(SDL2 REQUIRED)

set(ZLIB_LIBRARY "$PREFIX/lib/libz.a" CACHE FILEPATH "")
set(ZLIB_INCLUDE_DIR "$PREFIX/include" CACHE PATH "")
# PNG disabled for now (only used for screenshots); libpng's config generation
# step does not cross-compile cleanly with the OHOS sysroot.
set(FREETYPE_INCLUDE_DIR_freetype2 "$PREFIX/include/freetype2" CACHE PATH "")
set(FREETYPE_INCLUDE_DIR_ft2build "$PREFIX/include/freetype2" CACHE PATH "")
set(FREETYPE_LIBRARY "$PREFIX/lib/libfreetype.a" CACHE FILEPATH "")
set(LIBLZMA_INCLUDE_DIR "$PREFIX/include" CACHE PATH "")
set(LIBLZMA_LIBRARY "$PREFIX/lib/liblzma.a" CACHE FILEPATH "")
set(LZO_INCLUDE_DIR "$PREFIX/include" CACHE PATH "")
set(LZO_LIBRARY "$PREFIX/lib/liblzo2.a" CACHE FILEPATH "")
EOF

# Host tools (strgen/settingsgen) must be built natively first.
if [ ! -x "$WORK_DIR/host-tools/strgen" ] && [ ! -f "$WORK_DIR/host-tools/strgen.exe" ]; then
    cmake -S "$SRC_DIR" -B "$WORK_DIR/host-tools" -DOPTION_TOOLS_ONLY=ON -DCMAKE_BUILD_TYPE=Release
    cmake --build "$WORK_DIR/host-tools" -j "$JOBS"
fi

GAME_BUILD="$WORK_DIR/openttd-$OHOS_ARCH"
rm -rf "$GAME_BUILD"
cmake -S "$SRC_DIR" -B "$GAME_BUILD" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DOHOS_ARCH="$OHOS_ARCH" -DOHOS_PLATFORM=OHOS -DOHOS_STL=c++_shared \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_MODULE_PATH="$SRC_DIR/cmake;$WORK_DIR" \
    -DHOST_BINARY_DIR="$WORK_DIR/host-tools" \
    -DPERSONAL_DIR=openttd -DGLOBAL_DIR="(not set)" -DSHARED_DIR="(not set)" \
    -DCMAKE_PLATFORM_NO_VERSIONED_SONAME=1
cmake --build "$GAME_BUILD" -j "$JOBS"

echo "== [6/6] install libs into harmony/app =="
LIBS_OUT="$HARMONY_DIR/app/entry/libs/$OHOS_ARCH"
mkdir -p "$LIBS_OUT"
cp -f "$GAME_BUILD/libopenttd.so" "$LIBS_OUT/"
cp -f "$PREFIX/lib/libSDL3.so" "$PREFIX/lib/libSDL2.so" "$LIBS_OUT/"
cp -f "$PREFIX/lib/libSDL3.so.0" "$LIBS_OUT/" 2>/dev/null || true
SYSROOT_LIB="$OHOS_NATIVE_SDK/sysroot/usr/lib/aarch64-linux-ohos"
cp -f "$SYSROOT_LIB/libc++_shared.so" "$LIBS_OUT/" 2>/dev/null || true

echo "Done. Libraries installed to: $LIBS_OUT"
