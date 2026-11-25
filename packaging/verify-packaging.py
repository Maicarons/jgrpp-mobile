#!/usr/bin/env python3
"""Verify packaging/tree/*.tar.xz without extracting anything.

The vendored packaging tree carries ~94 symlinks and executable bits, so a
Windows checkout can never materialise it (git for Windows turns the symlinks
into plain files).  This script reads the archives directly and asserts the
invariants the Android build depends on:

  * every archive opens and lists cleanly
  * the local build patches are baked in (so the CI needs no sed/awk)
  * the sample apps, project/jni/python and the unused nested submodules are gone
  * the paths the build reads are present, and the ones that must resolve
    through a symlink really do
  * the scripts that must be executable are executable
  * every archive stays well under GitHub's 100 MB per-file limit

Usage:
    python packaging/verify-packaging.py [tree-dir]

Exits non-zero and prints FAILURES when anything regressed.
"""

import glob
import os
import posixpath
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TREE = os.path.join(HERE, "tree")

# The app config, the gradle template and AndroidBuild.sh are patched by
# make-packaging-tarball.py, so the CI does not have to rewrite them.
APP_CFG = "project/jni/application/openttd-jgrpp/AndroidAppSettings.cfg"
GRADLE = "project/app/build-template.gradle"
BUILD_SH = "project/jni/application/openttd-jgrpp/AndroidBuild.sh"
ROOT_BUILD_SH = "build.sh"
PNG_CONF = "project/jni/sdl2_image/external/libpng/pnglibconf.h"
PNG_CONF_PREBUILT = "project/jni/sdl2_image/external/libpng/scripts/pnglibconf.h.prebuilt"

INSPECT = {APP_CFG, GRADLE, BUILD_SH, ROOT_BUILD_SH, PNG_CONF, PNG_CONF_PREBUILT}

# Scripts and build files the Linux build feeds straight to sh/make/gradle.  A
# CRLF in any of them is fatal ("bad interpreter", broken `\` continuations), so
# every one of them is read and checked.  `git archive` only writes LF when the
# checkout has autocrlf off, which is why this is checked rather than assumed.
TEXT_SUFFIXES = (".sh", ".mk", ".cfg", ".gradle", ".cmake")

# Stored with CRLF upstream, byte for byte, and none of them is reachable from
# the Android build: SDL's MSVC cpu-architecture probe and its desktop
# visualtest harness, harfbuzz's own enum-codegen helper.
CRLF_UPSTREAM = {
    "project/jni/sdl2/cmake/CheckCPUArchitecture.cmake",
    "project/jni/sdl2/visualtest/launch_harness.sh",
    "project/jni/sdl2_ttf/external/harfbuzz/replace-enum-strings.cmake",
}

# Paths the build reads.  Every one of these is either a file, a directory
# entry or a symlink that has to resolve, and none of them may disappear.
REQUIRED_FILES = [
    "build.sh",
    "copyAssets.sh",
    "changeAppSettings.sh",
    "sign.sh",
    "project/jni/Application.mk",
    # changeAppSettings.sh includes this and writes Settings.mk from it
    "project/jni/SettingsTemplate.mk",
    "project/jni/application/Android.mk",
    "project/jni/application/CustomBuildScript.mk",
    "project/jni/application/setEnvironment-arm64-v8a.sh",
    "project/jni/application/openttd-jgrpp/AndroidAppSettings.cfg",
    "project/jni/application/openttd-jgrpp/AndroidBuild.sh",
    "project/jni/application/openttd-jgrpp/AndroidPreBuild.sh",
    "project/jni/application/openttd-jgrpp/pack-data.sh",
    "project/jni/application/openttd-jgrpp/AndroidData",
    # sources behind the jni/*/include symlinks and the APP_MODULES list
    "project/jni/sdl-1.2/include/SDL.h",
    "project/jni/iconv/src/icu4c-62_1-src.tgz",
    "project/jni/sdl2_image/external/libpng/png.h",
    "project/jni/sdl2_image/external/jpeg/jpeglib.h",
    "project/jni/sdl2_ttf/external/freetype/include/freetype/freetype.h",
    "project/jni/sdl2_ttf/external/harfbuzz/src/hb.h",
    "project/jni/sdl2_mixer/external/ogg/include/ogg/ogg.h",
    "project/jni/sdl2_mixer/external/vorbis/include/vorbis/codec.h",
    "project/jni/sdl2_mixer/external/flac/include/FLAC/format.h",
    "project/jni/timidity/Android.mk",
]

# The CI runs `ln -sfn openttd-jgrpp project/jni/application/src` to pick the
# app, exactly like pelya's own checkout does.  Modelling it here proves the
# symlink is load bearing: half the Java/asset tree goes through it.
VIRTUAL_LINKS = {"project/jni/application/src": "openttd-jgrpp"}

# Symlinks that must resolve, once the app is selected.
REQUIRED_LINKS = [
    "src",
    "AndroidAppSettings.cfg",
    "project/res/drawable/icon.png",
    "project/jni/png/include",
    "project/jni/jpeg/include",
    "project/jni/freetype/include",
    "project/jni/harfbuzz/include",
    "project/jni/ogg/include",
    "project/jni/vorbis/include",
    "project/jni/flac/include",
]

# Symlinks the build writes through, so they must be in the archive even though
# nothing they point at exists yet: changeAppSettings.sh creates project/src,
# copyAssets.sh creates project/assets, the native build creates project/libs.
GENERATED_LINKS = [
    "project/app/src/main/AndroidManifest.xml",
    "project/app/src/main/java",
    "project/app/src/main/assets",
    "project/app/src/main/jniLibs",
]

EXECUTABLES = [
    "build.sh",
    "copyAssets.sh",
    "changeAppSettings.sh",
    "sign.sh",
    "project/jni/application/openttd-jgrpp/AndroidBuild.sh",
    "project/jni/application/openttd-jgrpp/AndroidPreBuild.sh",
    "project/jni/application/openttd-jgrpp/pack-data.sh",
    "project/jni/application/setEnvironment-arm64-v8a.sh",
]

# Nothing this app builds needs these, and together they are about 160 MB.
# wavpack and libgme are absent from this list on purpose: SDL2_mixer's
# Android.mk defaults SUPPORT_WAVPACK/SUPPORT_GME to true and would then need
# modules that are no longer defined (see check_pruned_includes below).
PRUNED_SUBMODULES = [
    "project/jni/sdl2_image/external/dav1d",
    "project/jni/sdl2_image/external/libavif",
    "project/jni/sdl2_image/external/libjxl",
    "project/jni/sdl2_image/external/libtiff",
    "project/jni/sdl2_image/external/libwebp",
    "project/jni/sdl2_mixer/external/libxmp",
    "project/jni/sdl2_mixer/external/mpg123",
    "project/jni/sdl2_mixer/external/opus",
    "project/jni/sdl2_mixer/external/opusfile",
]

MAX_ARCHIVE = 100 * 1024 * 1024


def resolve(members, name, hops=0):
    """Resolve `name` the way the kernel would, following symlinks in any path
    component (project/jni/application/src is itself a symlink).  Returns the
    member the path lands on, or None when it does not exist."""
    if hops > 16:
        return None
    parts = name.split("/")
    for i in range(len(parts)):
        prefix = "/".join(parts[:i + 1])
        rest = parts[i + 1:]
        if prefix in VIRTUAL_LINKS:
            target = VIRTUAL_LINKS[prefix]
        elif prefix in members and members[prefix].issym():
            target = members[prefix].linkname
        else:
            continue
        landed = posixpath.normpath(
            posixpath.join(posixpath.dirname(prefix), target, *rest))
        return resolve(members, landed, hops + 1)
    return name if name in members else None


SUPPORT_GUARD = re.compile(r"^(ifeq|ifneq)\s*\(\s*\$\((\w+)\)\s*,\s*([^)]+?)\s*\)")
DEFINITION = re.compile(r"^\s*([A-Za-z_]\w*)\s*[:?]=\s*(.+?)\s*$", re.M)


def check_pruned_includes(members, contents, check):
    """No Android.mk may include a pruned codec directory unless it is off by
    default.  ndk-build refuses to build otherwise:

        Android NDK: Module SDL2_mixer depends on undefined modules: wavpack gme

    That is exactly what dropping sdl2_mixer/external/wavpack caused, because
    SDL2_mixer's own Android.mk has `SUPPORT_WAVPACK ?= true` and includes the
    codec behind it."""
    resolved = 0
    for name, data in sorted(contents.items()):
        if not name.endswith("Android.mk"):
            continue
        text = data.decode("utf-8", "replace")
        variables = dict(DEFINITION.findall(text))
        guard = []
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("ifeq", "ifneq", "ifdef", "ifndef")):
                match = SUPPORT_GUARD.match(stripped)
                guard.append((match.group(2), match.group(3).strip(),
                              match.group(1) == "ifeq") if match else None)
                continue
            if stripped.startswith("endif"):
                if guard:
                    guard.pop()
                continue
            if not stripped.startswith("include "):
                continue
            target = stripped[len("include "):].strip()
            while True:
                expanded = re.sub(r"\$\((\w+)\)",
                                  lambda m: variables.get(m.group(1), m.group(0)),
                                  target)
                if expanded == target:
                    break
                target = expanded
            # LOCAL_PATH is `$(call my-dir)` in every one of these files.
            target = re.sub(r"\$\(call\s+my-dir\)", ".", target)
            if "$(" in target:
                continue
            path = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            resolved += 1
            pruned = next((p for p in PRUNED_SUBMODULES
                           if path == p or path.startswith(p + "/")), None)
            if pruned is None or path in members:
                continue
            disabled = False
            for item in guard:
                if item and item[0].startswith("SUPPORT_"):
                    default = variables.get(item[0])
                    if default is None:
                        continue
                    on = (default == item[1]) if item[2] else (default != item[1])
                    disabled = disabled or not on
            check(disabled,
                  "%s:%d includes %s, which is pruned and enabled by default"
                  % (name, lineno, target))
    return resolved


def main():
    tree = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TREE
    archives = sorted(glob.glob(os.path.join(tree, "*.tar.xz")))
    if not archives:
        print("no archives in %s" % tree)
        return 1

    members, contents, total = {}, {}, 0
    for path in archives:
        size = os.path.getsize(path)
        total += size
        with tarfile.open(path) as tf:
            for member in tf:
                name = member.name.rstrip("/")
                members[name] = member
                if name in INSPECT or (member.isfile()
                                       and name.endswith(TEXT_SUFFIXES)
                                       and member.size < 2_000_000):
                    contents[name] = tf.extractfile(member).read()
        print("%-34s %6.1f MB  %s" % (os.path.basename(path), size / 1e6,
                                      "ok" if size < MAX_ARCHIVE else "TOO BIG"))

    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    for path in archives:
        check(os.path.getsize(path) < MAX_ARCHIVE,
              "%s exceeds GitHub's 100 MB file limit" % os.path.basename(path))

    # Baked-in patches: the CI must not need sed/awk for any of these.
    cfg = contents[APP_CFG].decode()
    check("APP_PLATFORM=android-24" in cfg, "app cfg: APP_PLATFORM=android-24 missing")
    gradle = contents[GRADLE].decode()
    check("minSdk 24" in gradle, "gradle template: minSdk 24 missing")
    check("minSdk 21" not in gradle, "gradle template: minSdk 21 still there")
    check("minifyEnabled true" in gradle and "shrinkResources true" in gradle,
          "gradle template: minify/shrink no longer enabled")
    build_sh = contents[BUILD_SH].decode()
    check("-DANDROID_PLATFORM=android-24 \\" in build_sh,
          "AndroidBuild.sh: -DANDROID_PLATFORM=android-24 missing")
    check(build_sh.count("-DANDROID_PLATFORM") == 1,
          "AndroidBuild.sh: platform injected more than once")
    check("cygpath -m" not in build_sh, "AndroidBuild.sh: Windows-only hack leaked in")
    check(contents[PNG_CONF] == contents[PNG_CONF_PREBUILT],
          "pnglibconf.h is not libpng's prebuilt template")

    # build.sh has to run stage-data.sh, which packs this build's own lang/ and
    # baseset/ into AndroidData just before copyAssets.sh copies it into the APK.
    # Without the hook the APK ships no game data and the launcher has nothing to
    # unpack on first run.
    root_build = contents[ROOT_BUILD_SH].decode()
    hook_at = root_build.find("stage-data.sh")
    copy_at = root_build.find("\n./copyAssets.sh")
    check(hook_at != -1, "build.sh: no stage-data.sh hook")
    check(copy_at != -1, "build.sh: no ./copyAssets.sh call")
    check(-1 < hook_at < copy_at, "build.sh: stage-data.sh must run before copyAssets.sh")

    # CRLF would break every script the build runs.
    scripts = [n for n in contents if n.endswith(TEXT_SUFFIXES)]
    crlf = sorted(n for n in scripts if b"\r\n" in contents[n] and n not in CRLF_UPSTREAM)
    check(not crlf, "CRLF line endings in %d script(s): %s"
          % (len(crlf), ", ".join(crlf[:5])))

    # Pruned paths.
    check(not [n for n in members if n.startswith("project/jni/python/")],
          "project/jni/python is still in the tree")
    check(not [n for n in members if n.rsplit("/", 1)[-1] == ".gitmodules"],
          ".gitmodules should be pruned")
    apps = {n.split("/")[3] for n in members if n.startswith("project/jni/application/")
            and n.count("/") > 3}
    check(apps == {"openttd-jgrpp"},
          "unexpected sample apps: %s" % sorted(apps - {"openttd-jgrpp"}))
    for sub in PRUNED_SUBMODULES:
        check(not [n for n in members if n.startswith(sub + "/")], "%s not pruned" % sub)

    # A pruned codec must not be required by an enabled SUPPORT_* include.
    resolved_includes = check_pruned_includes(members, contents, check)

    # The tree the build reads.
    for name in REQUIRED_FILES:
        check(name in members, "missing %s" % name)
    for name in REQUIRED_LINKS:
        check(name in members, "missing symlink %s" % name)
        check(resolve(members, name) is not None, "symlink does not resolve: %s" % name)
    for name in GENERATED_LINKS:
        check(name in members, "missing build-generated symlink %s" % name)
        check(name in members and members[name].issym(),
              "%s is not a symlink any more" % name)
    for name in EXECUTABLES:
        check(name in members and members[name].mode & 0o111,
              "%s is not executable" % name)

    # Symlinks that dangle are upstream's own (Xcode frameworks, build outputs,
    # the vncserver indirection and the unpopulated translations repo) and the
    # build never dereferences them.  Report them, do not fail.
    dangling = [n for n, m in sorted(members.items())
                if m.issym() and n not in GENERATED_LINKS and resolve(members, n) is None]

    links = sum(1 for m in members.values() if m.issym())
    print("\n%d archives, %.1f MB, %d members, %d symlinks, %d scripts checked for CRLF,"
          " %d Android.mk includes resolved"
          % (len(archives), total / 1e6, len(members), links, len(scripts),
             resolved_includes))
    if dangling:
        print("%d dangling symlinks (upstream's own, unused by the build):" % len(dangling))
        for name in dangling:
            print("  %s" % name)

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("all invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
