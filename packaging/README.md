# Vendored packaging tree

The Android build does not run out of a plain source tree.  It needs
[pelya/commandergenius](https://github.com/pelya/commandergenius) (branch
`sdl_android`) — the scaffolding that provides the `ndk-build` glue, the Gradle
project, the SDL Java launcher, and every third-party native library `jgrpp`
links against (SDL 1.2, SDL_image/mixer/ttf with their nested jpeg/png/ogg/
flac/vorbis/freetype/harfbuzz sources, ICU, zlib, lzma, lzo, expat,
fontconfig, timidity).

Upstream is frozen, so **this repository is the authoritative copy**.  The
release workflow does not clone anything: it unpacks `packaging/tree/*.tar.xz`
and builds.  Nothing here is generated at build time, so a release build is
reproducible from the repository plus the Android SDK/NDK.

## Contents

One archive per component.  Every member path is already relative to the
packaging tree root, so unpacking is a plain loop over the directory:

| archive | size | members | from |
| --- | ---: | ---: | --- |
| `01-commandergenius.tar.xz` | 43.2 MB | 5718 | `pelya/commandergenius` @ `92979c25` |
| `02-iconv-src.tar.xz` | 37.5 MB | 17 | `pelya/libiconv-libicu-android` @ `1d9e3e38` |
| `03-sdl2.tar.xz` | 5.5 MB | 2147 | `libsdl-org/SDL` @ `0efeb82a` |
| `04-sdl2_image.tar.xz` | 10.6 MB | 1566 | `libsdl-org/SDL_image` @ `c91323df` |
| `05-sdl2_mixer.tar.xz` | 10.8 MB | 2389 | `libsdl-org/SDL_mixer` @ `7808d9af` |
| `06-sdl2_ttf.tar.xz` | 25.8 MB | 4810 | `libsdl-org/SDL_ttf` @ `3091df32` |

Sizes are decimal MB (133.4 MB in total), the same unit
`verify-packaging.py` prints; the builder, `MANIFEST.txt` and this table agree
byte for byte.

`MANIFEST.txt` lists the exact commit of every component and of each nested
submodule, the sha256 of each archive, and what was pruned and patched.

### Why archives instead of the files

The tree uses `git` symlinks and executable bits as build machinery: about 94
symlinks (`project/jni/png/include -> sdl2_image/external/libpng`,
`project/app/src/main/assets -> project/assets`, the root `src` and
`AndroidAppSettings.cfg` indirections, …) and the shell scripts that drive the
build must keep their executable bit.  Windows checkouts cannot represent
either, so the tree could never be committed as loose files without silently
breaking the Linux build.  `git archive` records symlinks, modes and the
executable bits exactly as upstream stores them, and `tar`/`xz` round-trip
them losslessly.

The archives also preserve **line endings**.  That is not automatic: a Windows
checkout of these repositories normally has `core.autocrlf` on, and
`git archive` converts like a checkout does, so `make-packaging-tarball.py`
passes `-c core.autocrlf=false`.  Without it every script would arrive with
CRLF and the Linux build would die on `bad interpreter` and on broken `\` line
continuations in `AndroidBuild.sh`.  `verify-packaging.py` re-checks all 418
`.sh`/`.mk`/`.cfg`/`.gradle`/`.cmake` files for CRLF, and knows the three
desktop-only helpers SDL and harfbuzz store with CRLF upstream.

Each archive is well under GitHub's 100 MB per-file limit (the largest is
43.2 MB).

### How the release workflow consumes it

```bash
mkdir -p "$RUNNER_TEMP/sdl-android"
cd "$RUNNER_TEMP/sdl-android"
for a in "$GITHUB_WORKSPACE"/packaging/tree/*.tar.xz; do tar -xJf "$a"; done
ln -sfn openttd-jgrpp project/jni/application/src   # pick the app
cp "$GITHUB_WORKSPACE/stage-data.sh" . && chmod +x stage-data.sh
./changeAppSettings.sh                              # generates Settings.mk, project/src, build.gradle
./build.sh                                          # ndk-build + CMake + (stage-data.sh) + copyAssets + Gradle
```

`project/jni/application/src` is git-ignored in upstream and every checkout
creates it; the launch glue, the Java sources and the assets all go through it,
so it has to exist before `changeAppSettings.sh` runs.

`project/assets`, `project/src`, `project/libs` and the generated
`project/jni/Settings.mk` do **not** exist in the archives either — the build
creates them (`copyAssets.sh` does `mkdir -p project/assets`, for example), and
the symlinks that point at them are in the archive so the build can write
through them.

## Verifying

```bash
python packaging/verify-packaging.py
```

Reads the archives without extracting them (so it works on Windows too) and
checks the invariants above: which paths must be there, which symlinks must
resolve once the app is selected, which scripts must be executable, which paths
must be gone, that no `Android.mk` still includes a pruned codec directory that
is enabled by default, that no script arrived with CRLF, that the patches below
are baked in, and that no archive approaches the 100 MB limit.  Run it after
touching anything in `packaging/`.

## Rebuilding

```bash
git clone -b sdl_android https://github.com/pelya/commandergenius.git
cd commandergenius
git submodule update --init --recursive --depth=1 \
    project/jni/iconv/src project/jni/sdl2 project/jni/sdl2_image \
    project/jni/sdl2_mixer project/jni/sdl2_ttf
cd -
python packaging/make-packaging-tarball.py <path-to-checkout> packaging/tree
```

The builder reads everything through `git archive` (never from the working
tree), so a stale or locally modified checkout cannot leak into the archives.
`packaging/tree` is written from scratch; `MANIFEST.txt` is regenerated with the
new commits and hashes.

`project/jni/sdl2_image/external/libjxl/third_party/skcms` is not initialised
(the `libjxl` subtree is pruned anyway) — the recursive submodule update above
is best-effort for that one and its failure is harmless.

### Patches baked in

These used to be `sed`/`awk` steps in the workflow; they live in the archives
now, each next to a comment saying why:

| file | change | why |
| --- | --- | --- |
| `.../openttd-jgrpp/AndroidAppSettings.cfg` | `APP_PLATFORM=android-24` | the NDK's minimum supported API, and `jgrpp` needs it |
| `project/app/build-template.gradle` | `minSdk 21` → `24` | same floor for the Gradle side |
| `.../openttd-jgrpp/AndroidBuild.sh` | `-DANDROID_PLATFORM=android-24` on the CMake call | pelya passes no platform to the app's CMake build |
| `build.sh` | `./stage-data.sh` hook before `./copyAssets.sh` | the APK's game data (`AndroidData/*.zip.xz`) has to be packed from *this* build's own `lang/` and `baseset/`; the script itself lives in this repository, and the hook is a no-op without it |
| `sdl2_image/external/libpng/pnglibconf.h` | materialised from `scripts/pnglibconf.h.prebuilt` | libpng ships the generated header only in `scripts/` |

`minifyEnabled`/`shrinkResources` stay `true` as upstream ships them.

### Pruned

The archives carry only what this app builds.  Verified against the generated
`APP_MODULES` (`sdl-1.2 sdl_native_helpers jpeg png ogg flac vorbis freetype
timidity expat fontconfig lzma lzo2 icui18n iculx icu-le-hb harfbuzz icudata
icuuc`) and a scan of the symlinks that reach into the submodules:

* every other `project/jni/application/*` sample app (54 MB),
* `project/jni/python` (57 MB; only the sample apps use it),
* every `.gitmodules`,
* the optional image codecs `sdl2_image/external/{libjxl,libavif,dav1d,libwebp,libtiff}`
  and audio codecs `sdl2_mixer/external/{libxmp,mpg123,opus,opusfile}` (~155 MB),
  none of which any built module references.

`wavpack` (4 MB) and `libgme` (1 MB) are **kept** for a reason worth recording:
nothing builds them either, but SDL2_mixer's own `Android.mk` defaults
`SUPPORT_WAVPACK` and `SUPPORT_GME` to `true` and adds the `wavpack` and `gme`
modules to `LOCAL_STATIC_LIBRARIES`.  Dropping the sources made ndk-build abort
with

    Android NDK: Module SDL2_mixer depends on undefined modules: wavpack gme

and keeping 5 MB is cheaper than editing upstream's build to turn two unused
codecs off.  `verify-packaging.py` now fails if any `Android.mk` includes a
pruned codec directory that is still enabled by default, so the same mistake
cannot reach CI again.

The archives still contain a handful of dangling symlinks of upstream's own
(Xcode frameworks' `Versions/Current`, `app-release.apk`, the `vncserver`
headers, `translations/`, the asset-pack module).  Nothing in the build
dereferences them; `verify-packaging.py` lists them so they stay accounted for.

Windows-only workarounds used for local builds (`cygpath` in `AndroidBuild.sh`,
the `APPDIR`/`Makefile.prebuilt` hacks, `minifyEnabled false`) are deliberately
**not** in the archives: the CI builds on Linux and must build the way upstream
does.

## Licensing

The archives contain third-party sources (SDL, SDL_image/mixer/ttf and their
nested libraries, libiconv, ICU, zlib, lzma, lzo, expat, fontconfig, timidity,
freetype, harfbuzz) that keep their own licences, and every one of them still
ships its licence files inside the archive.  Redistribution has to honour those
terms; the jgrpp Android build this repository produces is GPLv2 like upstream
`jgrpp`.
