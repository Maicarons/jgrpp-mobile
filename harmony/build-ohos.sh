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
# Native cmake.exe (Windows) cannot read MSYS /g/... paths embedded in files.
if command -v cygpath >/dev/null; then PREFIX_NATIVE="$(cygpath -m "$PREFIX")"; else PREFIX_NATIVE="$PREFIX"; fi

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
# Written into the source cmake/ dir (always on CMAKE_MODULE_PATH, like
# pelya's AndroidSDL.cmake) so include(OhosSDL) resolves reliably.
cat > "$SRC_DIR/cmake/OhosSDL.cmake" <<EOF
# Generated by harmony/build-ohos.sh - points the OpenTTD build at the
# OHOS cross-compiled dependencies in $PREFIX_NATIVE. Do not commit.
set(UNIX 1)
set(SDL2_DIR "$PREFIX_NATIVE/lib/cmake/SDL2" CACHE PATH "")
find_package(SDL2 REQUIRED)

set(ZLIB_LIBRARY "$PREFIX_NATIVE/lib/libz.a" CACHE FILEPATH "")
set(ZLIB_INCLUDE_DIR "$PREFIX_NATIVE/include" CACHE PATH "")
# PNG disabled for now (only used for screenshots); libpng's config generation
# step does not cross-compile cleanly with the OHOS sysroot.
set(FREETYPE_INCLUDE_DIR_freetype2 "$PREFIX_NATIVE/include/freetype2" CACHE PATH "")
set(FREETYPE_INCLUDE_DIR_ft2build "$PREFIX_NATIVE/include/freetype2" CACHE PATH "")
set(FREETYPE_LIBRARY "$PREFIX_NATIVE/lib/libfreetype.a" CACHE FILEPATH "")
set(LIBLZMA_INCLUDE_DIR "$PREFIX_NATIVE/include" CACHE PATH "")
set(LIBLZMA_LIBRARY "$PREFIX_NATIVE/lib/liblzma.a" CACHE FILEPATH "")
set(LZO_INCLUDE_DIR "$PREFIX_NATIVE/include" CACHE PATH "")
set(LZO_LIBRARY "$PREFIX_NATIVE/lib/liblzo2.a" CACHE FILEPATH "")
EOF

# Host tools (strgen/settingsgen) must be built natively first.
# Build type must match the game build below: HOST_BINARY_DIR paths embed it.
if [ ! -x "$WORK_DIR/host-tools/strgen" ] && [ ! -f "$WORK_DIR/host-tools/src/strgen/RelWithDebInfo/strgen.exe" ]; then
    cmake -S "$SRC_DIR" -B "$WORK_DIR/host-tools" -G Ninja -DOPTION_TOOLS_ONLY=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo
    cmake --build "$WORK_DIR/host-tools" -j "$JOBS"
fi

GAME_BUILD="$WORK_DIR/openttd-$OHOS_ARCH"

# OpenTTD requires recent-C++20 frontend features (P0634 'typename',
# parenthesised aggregate init) that the bundled OHOS clang 15 rejects.
# When OHOS_CLANG_PREFIX points at a newer clang toolchain directory,
# drive the OHOS sysroot + SDK libc++ headers with that frontend instead.
case "$OHOS_ARCH" in
    arm64-v8a)  OHOS_TRIPLE=aarch64-linux-ohos ;;
    armeabi-v7a) OHOS_TRIPLE=arm-linux-ohos ;;
    *)          OHOS_TRIPLE=x86_64-linux-ohos ;;
esac
GAME_EXTRA_ARGS=()
TOOLCHAIN_USED="$TOOLCHAIN_FILE"
if [ -n "${OHOS_CLANG_PREFIX:-}" ]; then
    # Newer frontend (clang 16+; e.g. /d/DevEnv/mingw64/bin or /usr/lib/llvm-18)
    # understands the C++20 features OpenTTD needs (P0634 'typename', P0960
    # parenthesised aggregate init). The bundled OHOS clang 15 rejects them.
    # We use it ONLY for compilation; linking is routed back to OHOS clang 15
    # because only that driver knows the musl crt object layout (it picks
    # Scrt1.o, whereas clang 19 looks for the glibc crtbeginS.o that the SDK
    # does not ship). The wrapper below makes the compile/link split.
    CLANG_CC="$OHOS_CLANG_PREFIX/clang";    [ -f "$CLANG_CC.exe" ] && CLANG_CC="$CLANG_CC.exe"
    CLANG_CXX="$OHOS_CLANG_PREFIX/clang++"; [ -f "$CLANG_CXX.exe" ] && CLANG_CXX="$CLANG_CXX.exe"
    OHOS_CC="$OHOS_NATIVE_SDK/llvm/bin/clang";    [ -f "$OHOS_CC.exe" ] && OHOS_CC="$OHOS_CC.exe"
    OHOS_CXX="$OHOS_NATIVE_SDK/llvm/bin/clang++"; [ -f "$OHOS_CXX.exe" ] && OHOS_CXX="$OHOS_CXX.exe"
    WRAPDIR="$WORK_DIR/bin"
    mkdir -p "$WRAPDIR"
    # The newer frontend (clang19) does not auto-discover the OHOS libc++ the
    # way OHOS clang15 does (clang looks for ../include/c++/v1 next to its own
    # binary). We must point it at the SDK's libc++ headers and the clang15
    # resource dir (musl-aware builtins). These SDK paths live under
    # "Program Files" on Windows, so we inject them *inside* the wrapper where we
    # control quoting, rather than through CMake/Ninja flags (whose re-quoting
    # mangles space-containing paths -> "'atomic' file not found").
    # The OHOS SDK ships two libc++ header trees: the generic LLVM one at
    # llvm/include/c++/v1 (inline namespace __1) and the OHOS one at
    # llvm/include/libcxx-ohos/include/c++/v1 (inline namespace __n1). Only the
    # latter matches the prebuilt libc++_shared.so (also __n1); using the wrong
    # tree compiles objects whose std::__1 symbols can never be satisfied.
    OHHDRS="$OHOS_NATIVE_SDK/llvm/include/libcxx-ohos/include/c++/v1"
    RES_DIR="$(ls -d "$OHOS_NATIVE_SDK/llvm/lib/clang/"*/ | head -1)"
    RES_DIR="${RES_DIR%/}"  # strip trailing slash: a trailing '\' would escape
                            # the closing quote when embedded in the .cmd flags.
    LIBDIR="$OHOS_NATIVE_SDK/llvm/lib/$OHOS_TRIPLE"
    SYSLIB="$OHOS_NATIVE_SDK/sysroot/usr/lib/$OHOS_TRIPLE"
    if command -v cygpath >/dev/null; then
        OHHDRS_W=$(cygpath -w "$OHHDRS"); RES_W=$(cygpath -w "$RES_DIR")
        LIBDIR_W=$(cygpath -w "$LIBDIR"); SYSLIB_W=$(cygpath -w "$SYSLIB")
    else
        OHHDRS_W="$OHHDRS"; RES_W="$RES_DIR"; LIBDIR_W="$LIBDIR"; SYSLIB_W="$SYSLIB"
    fi
    COMP_FLAGS="-nostdinc++ -isystem \"$OHHDRS_W\" -resource-dir \"$RES_W\" -D_LIBCPP_ENABLE_EXPERIMENTAL"
    # Link against the OHOS shared libc++ (libc++_shared.so). The OHOS toolchain
    # normally injects this, but swapping the compiler for our wrapper bypasses
    # that injection, so we name it explicitly. It is a shared lib, so its
    # position on the link line is irrelevant to symbol resolution.
    LINK_FLAGS="-L\"$LIBDIR_W\" -L\"$SYSLIB_W\" -lc++_shared"
    make_wrapper() {
        local base="$1" fe="$2" fo="$3"
        cat > "$WRAPDIR/$base.sh" <<WRAP
#!/bin/sh
# Compile (has -c) -> newer frontend (C++20); link (no -c) -> OHOS clang 15.
# SDK include/lib paths are injected here so the wrapper controls quoting.
case " \$* " in
  *" -c "*) exec "$fe" $COMP_FLAGS "\$@" ;;
  *) exec "$fo" $LINK_FLAGS "\$@" ;;
esac
WRAP
        chmod +x "$WRAPDIR/$base.sh"
    }
    make_wrapper ohos-clang  "$CLANG_CC"  "$OHOS_CC"
    make_wrapper ohos-clang++ "$CLANG_CXX" "$OHOS_CXX"
    # The OHOS toolchain unconditionally sets CMAKE_CXX_COMPILER to its own
    # clang (lines 333-334), as a *normal* variable which shadows any -D
    # override we pass. So instead we ship a patched copy of the toolchain
    # that points at our wrapper, and use that for the game build.
    TOOLCHAIN_FILE_PATCHED="$WORK_DIR/bin/ohos.toolchain.wrapped.cmake"
    case "$(uname -s)" in
      *MINGW*|*MSYS*|*CYGWIN*)
        # Forward slashes: CMake on Windows accepts them and they avoid the
        # backslash-escaping traps in both sed and CMake's set() strings.
        GAME_CC="$(cygpath -m "$WRAPDIR/ohos-clang.cmd")"
        GAME_CXX="$(cygpath -m "$WRAPDIR/ohos-clang++.cmd")" ;;
      *)
        GAME_CC="$WRAPDIR/ohos-clang.sh"
        GAME_CXX="$WRAPDIR/ohos-clang++.sh" ;;
    esac
    # Copying the toolchain to a new dir breaks its relative paths (it reads
    # oh-uni-package.json relative to CMAKE_CURRENT_LIST_DIR). Instead, write a
    # thin wrapper that include()s the original in place, then overrides only
    # the compiler with our wrapper. The include keeps every relative path
    # correct; the override (a normal var, last wins) swaps in the wrapper.
    if command -v cygpath >/dev/null; then
        TOOLCHAIN_FILE_WIN="$(cygpath -m "$TOOLCHAIN_FILE")"
    else
        TOOLCHAIN_FILE_WIN="$TOOLCHAIN_FILE"
    fi
    cat > "$TOOLCHAIN_FILE_PATCHED" <<WRAP
# Generated by harmony/build-ohos.sh - wraps the OHOS toolchain but swaps the
# compiler for our compile/link wrapper (newer clang frontend for C++20).
include("$TOOLCHAIN_FILE_WIN")
set(CMAKE_C_COMPILER "$GAME_CC")
set(CMAKE_CXX_COMPILER "$GAME_CXX")
WRAP
    TOOLCHAIN_USED="$TOOLCHAIN_FILE_PATCHED"
    # On Windows CMake drives the wrapper .cmd. We must NOT delegate to a
    # .sh here, because Git Bash's sh mangles the MSYS script path
    # (%~dp0ohos-clang++.sh -> backslashes eaten). Instead call clang
    # directly, with Windows (cygpath -w) paths baked in, branching on -c.
    case "$(uname -s)" in
      *MINGW*|*MSYS*|*CYGWIN*)
        CLANG_CC_W=$(cygpath -w "$CLANG_CC"); CLANG_CXX_W=$(cygpath -w "$CLANG_CXX")
        OHOS_CC_W=$(cygpath -w "$OHOS_CC"); OHOS_CXX_W=$(cygpath -w "$OHOS_CXX")
        make_cmd() {
            local base="$1" fe="$2" fo="$3"
            cat > "$WRAPDIR/$base.cmd" <<WRAP
@echo off
setlocal
set COMPILE=0
for %%a in (%*) do if "%%~a"=="-c" set COMPILE=1
if %COMPILE%==1 (
  "$fe" $COMP_FLAGS %*
) else (
  "$fo" $LINK_FLAGS %*
)
WRAP
        }
        make_cmd ohos-clang  "$CLANG_CC_W"  "$OHOS_CC_W"
        make_cmd ohos-clang++ "$CLANG_CXX_W" "$OHOS_CXX_W" ;;
      *)
        : ;;
    esac
    # The libc++ include / resource-dir / -L paths are injected by the wrapper
    # (see COMP_FLAGS / LINK_FLAGS above) so they never pass through CMake/Ninja
    # flag re-quoting, which mangles the space-containing "Program Files" SDK
    # path. The toolchain still supplies --target/--sysroot/-D__MUSL__ etc.
    GAME_EXTRA_ARGS=(
        -DCMAKE_C_COMPILER="$GAME_CC"
        -DCMAKE_CXX_COMPILER="$GAME_CXX"
    )
else
    GAME_EXTRA_ARGS=(-DCMAKE_CXX_FLAGS="-D_LIBCPP_ENABLE_EXPERIMENTAL")
fi

rm -rf "$GAME_BUILD"
cmake -S "$SRC_DIR" -B "$GAME_BUILD" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_USED" \
    -DOHOS_ARCH="$OHOS_ARCH" -DOHOS_PLATFORM=OHOS -DOHOS_STL=c++_shared \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
    "${GAME_EXTRA_ARGS[@]}" \
    -DTHREADS_PREFER_PTHREAD_FLAG=ON \
    -DHOST_BINARY_DIR="$WORK_DIR/host-tools" \
    -DPERSONAL_DIR=openttd -DGLOBAL_DIR="(not set)" -DSHARED_DIR="(not set)" \
    -DCMAKE_PLATFORM_NO_VERSIONED_SONAME=1
cmake --build "$GAME_BUILD" -j "$JOBS"

echo "== [6/6] install libs into harmony/app =="
LIBS_OUT="$HARMONY_DIR/app/entry/libs/$OHOS_ARCH"
mkdir -p "$LIBS_OUT"
cp -f "$GAME_BUILD/libopenttd.so" "$LIBS_OUT/"
cp -f "$PREFIX/lib/libSDL3.so" "$PREFIX/lib/libSDL2.so" "$LIBS_OUT/"
# Ship under the SONAME too: sdl2-compat's libSDL2.so has SONAME
# libSDL2-2.0.so, and some OHOS loaders require the on-disk name to match.
cp -f "$PREFIX/lib/libSDL2.so" "$LIBS_OUT/libSDL2-2.0.so" 2>/dev/null || true
cp -f "$PREFIX/lib/libSDL3.so.0" "$LIBS_OUT/" 2>/dev/null || true
SYSROOT_LIB="$OHOS_NATIVE_SDK/sysroot/usr/lib/aarch64-linux-ohos"
# libc++_shared.so ships under the LLVM lib dir (not sysroot) for the OHOS NDK.
LIBCXX_LIB="$OHOS_NATIVE_SDK/llvm/lib/$OHOS_TRIPLE/libc++_shared.so"
cp -f "$LIBCXX_LIB" "$LIBS_OUT/" 2>/dev/null || true

echo "== [7/7] install OpenTTD runtime data into HAP rawfile =="
# The game build generates base graphics, fonts, languages and AI/game
# scripts under $GAME_BUILD. The app deploys them via copyGameFilesFromRawfile(),
# so we mirror the needed trees into entry/.../rawfile/openttd/.
DATA_OUT="$HARMONY_DIR/app/entry/src/main/resources/rawfile/openttd"
rm -rf "$DATA_OUT"
mkdir -p "$DATA_OUT"
for d in baseset lang ai game media scripts gm; do
    src="$GAME_BUILD/$d"
    [ -d "$src" ] || continue
    # Skip dirs whose only contents are CMake bookkeeping files.
    files=$(find "$src" -maxdepth 1 -type f ! -name '*.cmake' ! -name 'CTestTestfile.cmake' 2>/dev/null)
    [ -n "$files" ] || continue
    mkdir -p "$DATA_OUT/$d"
    # shellcheck disable=SC2086
    cp -f $files "$DATA_OUT/$d/" 2>/dev/null || true
done
echo "Data copied to: $DATA_OUT"

echo "Done. Libraries installed to: $LIBS_OUT"
