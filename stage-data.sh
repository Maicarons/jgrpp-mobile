#!/usr/bin/env bash
# Stage the game data that ships inside the APK (AndroidData/*.zip.xz).
#
# Where it runs: build.sh calls ./stage-data.sh right AFTER the native build
# (ndk-build + CMake for the app) and BEFORE copyAssets.sh, i.e. before
# AndroidData/ is copied into the APK assets. That placement matters: the pack
# must be built from THIS build's own output.
#
# Why not the official OpenTTD package (which is what this used to do):
#   * lang/*.lng carry a LANGUAGE_PACK_VERSION hash that must equal the one
#     strgen generated for this build. The .lng files of an official package
#     hash differently, so every language is rejected and the game exits at
#     startup with "No available language packs (invalid versions?)".
#   * baseset/ must come from this build: it carries the OpenTTD fonts
#     (OpenTTD-*.ttf) and the JGRPP base GRFs (extra_signals, progsignals,
#     route_step, tracerestrict, ...) that the official package lacks.
# Only the base graphics/sound sets (OpenGFX/OpenSFX), which the GPL game
# cannot ship itself, are downloaded.
#
# Idempotent: an archive that already exists is left alone. Delete the one you
# want to regenerate (or all of .stage-cache) after changing versions.
set -euo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
CACHE="$THIS_DIR/.stage-cache"

# copyAssets.sh reads project/jni/application/src/AndroidData. In CI that path
# is a symlink to openttd-jgrpp, but a local run (run-arm64.sh step 1) makes
# `src` a real copy, so stage there *and* mirror into openttd-jgrpp/ so the next
# run's copy carries the packs too.
APP_DIR="$THIS_DIR/project/jni/application"
if [ -L "$APP_DIR/src" ]; then
  AD="$APP_DIR/openttd-jgrpp/AndroidData"
  AD_MIRROR=""
else
  AD="$APP_DIR/src/AndroidData"
  AD_MIRROR="$APP_DIR/openttd-jgrpp/AndroidData"
fi
mkdir -p "$AD" "$CACHE"
if [ -n "$AD_MIRROR" ]; then mkdir -p "$AD_MIRROR"; fi
echo "stage-data: staging into $AD"

# Free base graphics and sound sets (override to try another release).
OGFX_VER="${OGFX_VER:-8.0}"
OSFX_VER="${OSFX_VER:-1.0.3}"

# 1) openttd-data-<name>.zip.xz — the game data pack.
#    The name is pinned by AppDataDownloadUrl in AndroidAppSettings.cfg; it is
#    a fixed lookup key, not a version, so it stays put while the content
#    changes.
DATA_PACK="openttd-data-0.40.4-0"
OUT1="$AD/$DATA_PACK.zip.xz"
if [ ! -f "$OUT1" ]; then
  BUILD=""
  for d in "$THIS_DIR"/project/jni/application/*/openttd-build-*/; do
    if [ -d "${d}lang" ] && [ -d "${d}baseset" ]; then BUILD="${d%/}"; break; fi
  done
  test -n "$BUILD" || {
    echo "stage-data: no openttd-build-*/{lang,baseset} under project/jni/application/" >&2
    echo "stage-data: run this AFTER the native build (ndk-build + CMake)" >&2
    exit 1
  }
  echo "stage-data: staging from build output $BUILD"

  DATA_DIR="$CACHE/openttd-data"
  rm -rf "$DATA_DIR" && mkdir -p "$DATA_DIR"
  for d in lang baseset ai game; do
    if [ -d "$BUILD/$d" ]; then cp -r "$BUILD/$d" "$DATA_DIR/"; fi
  done
  test -f "$DATA_DIR/lang/english.lng" || {
    echo "stage-data: $BUILD/lang has no english.lng" >&2; exit 1; }
  ls "$DATA_DIR/baseset"/OpenTTD-*.ttf > /dev/null || {
    echo "stage-data: $BUILD/baseset has no OpenTTD fonts" >&2; exit 1; }

  for SET in ogfx osfx; do
    case "$SET" in
      ogfx) VER="$OGFX_VER"; U="https://cdn.openttd.org/opengfx-releases/$VER/opengfx-$VER-all.zip" ;;
      osfx) VER="$OSFX_VER"; U="https://cdn.openttd.org/opensfx-releases/$VER/opensfx-$VER-all.zip" ;;
    esac
    Z="$CACHE/$SET-$VER.zip"
    [ -f "$Z" ] || curl -fsSL --retry 3 -o "$Z" "$U"
    SET_DIR=$(unzip -Z1 "$Z" | head -1)
    SET_DIR=${SET_DIR%%/*}
    SET_DIR=${SET_DIR%.tar}
    rm -rf "$CACHE/$SET-$VER" && mkdir -p "$CACHE/$SET-$VER"
    unzip -q "$Z" -d "$CACHE/$SET-$VER"
    tar -xf "$CACHE/$SET-$VER/$SET_DIR.tar" -C "$DATA_DIR/baseset"
  done

  ( cd "$DATA_DIR" && zip -0 -r "$AD/$DATA_PACK.zip" baseset lang ai game )
  # Refuse to publish an incomplete pack (check before xz removes the .zip).
  unzip -l "$AD/$DATA_PACK.zip" 'lang/english.lng' 'baseset/OpenTTD-Sans.ttf' > /dev/null
  xz -8 -f "$AD/$DATA_PACK.zip"
else
  echo "stage-data: $OUT1 already present, skipping"
fi

# 2) MIDI instruments (timidity.zip lives inside the packaging template)
OUT2="$AD/timidity.zip.xz"
if [ ! -f "$OUT2" ]; then
  cp "$THIS_DIR/project/jni/timidity/samples/timidity.zip" "$AD/timidity.zip"
  xz -8 -f "$AD/timidity.zip"
else
  echo "stage-data: $OUT2 already present, skipping"
fi

# 3) ICU data built by the ndk-build pass
OUT3="$AD/icudt62l.zip.xz"
if [ ! -f "$OUT3" ]; then
  ICU_DAT=$(find "$THIS_DIR/project/jni/icuuc/share/icu" -name 'icudt*.dat' 2>/dev/null | head -1)
  test -n "$ICU_DAT" || { echo "stage-data: icudt*.dat not found under project/jni/icuuc/share/icu" >&2; exit 1; }
  ( cd "$(dirname "$ICU_DAT")" && zip -0 "$AD/icudt62l.zip" "$(basename "$ICU_DAT")" && xz -8 "$AD/icudt62l.zip" )
else
  echo "stage-data: $OUT3 already present, skipping"
fi

# Keep the openttd-jgrpp/ copy in sync so a later run-arm64.sh step 1 does not
# copy a stale pack back over this one.
if [ -n "$AD_MIRROR" ]; then
  cp -f "$AD"/*.xz "$AD_MIRROR"/
fi

ls -la "$AD"
