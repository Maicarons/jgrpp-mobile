#!/usr/bin/env python3
"""Rebuild packaging/tree/*.tar.xz, the vendored packaging tree.

The Android build needs pelya/commandergenius, the "packaging tree" that
provides the SDL/ndk-build/Gradle scaffolding and every third-party native
library jgrpp links against.  That repository is frozen upstream, so instead of
cloning it the release workflow unpacks these archives, and this project is the
authoritative copy: the patches the workflow used to apply with sed/awk are
baked in (each with the comment explaining why it is there), build.sh is given
the ./stage-data.sh hook that ships the APK's game data, and the parts this app
never builds are dropped.

One patch is not from the workflow but belongs here the same way: the Android
touch adaptation, which pelya's framework does not provide on its own.  See
patch_androidinput for the long-press right click.

Everything is built straight out of git (git archive), never from a checkout:
the tree relies on about 110 symlinks (jni/png/include -> sdl2_image's nested
libpng, project/app/src/main/assets -> project/assets, ...) plus executable
bits, and a Windows checkout cannot represent those.  git archive emits them
exactly as upstream stores them.

One archive is written per component and every path inside them is already
relative to the packaging tree root, so unpacking is

    for a in packaging/tree/*.tar.xz; do tar -xJf "$a" -C <build-dir>; done

Usage:
    python make-packaging-tarball.py <pelya-checkout> [output-dir]

The checkout must have the submodules initialised:
    git clone -b sdl_android https://github.com/pelya/commandergenius.git
    cd commandergenius
    git submodule update --init --recursive --depth=1 \
        project/jni/iconv/src project/jni/sdl2 project/jni/sdl2_image \
        project/jni/sdl2_mixer project/jni/sdl2_ttf
"""

import argparse
import datetime
import hashlib
import os
import re
import subprocess
import sys
import tarfile
import tempfile

PELYA_URL = "https://github.com/pelya/commandergenius.git"
PELYA_BRANCH = "sdl_android"

# Submodules the build needs, one archive each.  project/jni/Settings.mk
# (generated from SettingsTemplate.mk plus the app config) resolves APP_MODULES
# to
#   sdl-1.2 (pelya's own copy) jpeg png ogg flac vorbis freetype timidity expat
#   fontconfig lzma lzo2 icui18n iculx icu-le-hb harfbuzz icudata icuuc
# The jpeg/png sources are reached through symlinks into sdl2_image's nested
# submodules (jni/png/include -> sdl2_image/external/libpng, jni/jpeg/include ->
# .../external/jpeg), ogg/flac/vorbis into sdl2_mixer's, and freetype/harfbuzz
# into sdl2_ttf's.  iconv/src ships the icu4c, harfbuzz and libiconv tarballs
# the ICU build unpacks, so that build needs no network.
SEEDS = (
    ("02-iconv-src", "project/jni/iconv/src"),
    ("03-sdl2", "project/jni/sdl2"),
    ("04-sdl2_image", "project/jni/sdl2_image"),
    ("05-sdl2_mixer", "project/jni/sdl2_mixer"),
    ("06-sdl2_ttf", "project/jni/sdl2_ttf"),
)

# Only pelya's python sample apps use this, and it is 57 MB of the tree;
# APP_MODULES does not list python.
DROP_PREFIXES = ("project/jni/python/",)

# Optional codec sources of SDL_image/SDL_mixer.  png and jpeg are the only
# image modules this app builds and MIDI comes from timidity, so none of these
# is built; together they are about 160 MB of the tree.
#
# wavpack (4 MB) and libgme (1 MB) stay in even though nothing builds them
# either: SDL2_mixer's own Android.mk defaults SUPPORT_WAVPACK and SUPPORT_GME
# to true and adds the `wavpack` and `gme` modules to LOCAL_STATIC_LIBRARIES, so
# ndk-build aborts with "Module SDL2_mixer depends on undefined modules" unless
# their Android.mk files are present.  Keeping 5 MB is cheaper than editing
# upstream's build to disable two codecs this app never asks for.
DROP_SUBMODULES = (
    "project/jni/sdl2_image/external/libjxl",
    "project/jni/sdl2_image/external/libavif",
    "project/jni/sdl2_image/external/dav1d",
    "project/jni/sdl2_image/external/libwebp",
    "project/jni/sdl2_image/external/libtiff",
    "project/jni/sdl2_mixer/external/libxmp",
    "project/jni/sdl2_mixer/external/mpg123",
    "project/jni/sdl2_mixer/external/opus",
    "project/jni/sdl2_mixer/external/opusfile",
)

# Under project/jni/application/ only openttd-jgrpp's own glue is kept.  The
# files that sit directly in that directory (Android.mk, CustomBuildScript.mk,
# SettingsTemplate.mk, dummy.c, ...) are the framework and stay; the other
# sample applications (54 MB, plus the sources of their own submodules) go.
APPLICATION_DIR = "project/jni/application/"
KEEP_APPS = ("openttd-jgrpp/",)

# Patches the release workflow used to apply with sed/awk, baked in here.
APPCFG = "project/jni/application/openttd-jgrpp/AndroidAppSettings.cfg"
GRADLE_TEMPLATE = "project/app/build-template.gradle"
ANDROID_BUILD_SH = "project/jni/application/openttd-jgrpp/AndroidBuild.sh"
BUILD_SH = "build.sh"
SDL_ANDROID_INPUT = "project/jni/sdl-1.2/src/video/android/SDL_androidinput.c"
PNG_DIR = "project/jni/sdl2_image/external/libpng"
PNG_CONF = PNG_DIR + "/pnglibconf.h"
PNG_PREBUILT = PNG_DIR + "/scripts/pnglibconf.h.prebuilt"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), text=True,
                          capture_output=True, check=True).stdout


def archive(repo, dest):
    # -c core.autocrlf=false: a Windows clone of these repositories usually has
    # autocrlf on, and `git archive` converts like a checkout does, so without
    # this every script and every .mk/.cfg would land in the archive with CRLF
    # and the Linux build would die on "bad interpreter" and broken `\`
    # continuations.  The archives must carry the bytes upstream stores.
    with open(dest, "wb") as fh:
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                        "-C", repo, "archive", "--format=tar", "HEAD"],
                       stdout=fh, check=True)


def submodule_paths(repo):
    """Submodule paths recorded in a repository's .gitmodules."""
    try:
        out = git(repo, "config", "-f", ".gitmodules", "--get-regexp",
                  r"^submodule\..*\.path$")
    except subprocess.CalledProcessError:
        return []
    return [line.split()[1] for line in out.splitlines() if line.strip()]


def initialised(path):
    return os.path.isdir(os.path.join(path, ".git")) or \
        os.path.isfile(os.path.join(path, ".git"))


class Part:
    """One git repository of the packaging tree."""

    def __init__(self, repo, rel, tar):
        self.repo = repo            # absolute path of the checkout
        self.rel = rel              # path inside the packaging tree ("" = root)
        self.tar = tar              # archive of its HEAD
        self.commit = git(repo, "rev-parse", "HEAD").strip()
        self.url = (git(repo, "config", "--get", "remote.origin.url").strip()
                    or PELYA_URL)


def collect(src, rel, parts, tmp, dropped):
    """Archive `rel` and, recursively, the initialised submodules it needs."""
    path = os.path.join(src, rel)
    if not initialised(path):
        print("  !! %s is not initialised - the tree would be incomplete" % rel)
        return
    dest = os.path.join(tmp, rel.replace("/", "__") + ".tar")
    archive(path, dest)
    parts.append(Part(path, rel, dest))
    for sub in submodule_paths(path):
        child = rel + "/" + sub
        if child in DROP_SUBMODULES:
            dropped.append(child)
            continue
        collect(src, child, parts, tmp, dropped)


def read_members(tarpath, wanted):
    """Contents and TarInfo of the named regular-file members of a tar file."""
    found = {}
    with tarfile.open(tarpath) as tf:
        for member in tf:
            name = member.name.rstrip("/")
            if name in wanted and member.isfile():
                found[name] = (tf.extractfile(member).read(), member)
    return found


def patch_appcfg(data, name):
    """APP_PLATFORM=android-24.

    getifaddrs()/freeifaddrs() (src/network/core/host.cpp) exist from API 24;
    pelya's template leaves APP_PLATFORM empty, so ndk-build used android-21.
    """
    text = data.decode("utf-8")
    if re.search(r"(?m)^APP_PLATFORM=", text):
        text = re.sub(r"(?m)^APP_PLATFORM=.*$", "APP_PLATFORM=android-24", text)
    else:
        text = text.rstrip("\r\n") + "\nAPP_PLATFORM=android-24\n"
    return text.encode("utf-8")


def patch_gradle(data, name):
    """minSdk 21 -> 24, for the same getifaddrs() reason as APP_PLATFORM.

    Deliberately not anchored to the line, exactly like the sed it replaces.
    """
    text, count = re.subn(r"minSdk 21\b", "minSdk 24", data.decode("utf-8"))
    if not count:
        raise SystemExit("%s: no 'minSdk 21' found" % name)
    return text.encode("utf-8")


def patch_androidbuild(data, name):
    """Inject -DANDROID_PLATFORM=android-24 into pelya's CMake command.

    The openttd native library is built by CMake, not by pelya's ndk-build, and
    AndroidBuild.sh never sets ANDROID_PLATFORM, so CMake defaulted to
    android-21 and failed on getifaddrs().  The injected line ends with a
    backslash, i.e. it extends the command it follows.
    """
    out, done = [], False
    for line in data.decode("utf-8").splitlines(True):
        out.append(line)
        if not done and re.match(r"^\s*cmake\s", line):
            out.append("\t-DANDROID_PLATFORM=android-24 \\\n")
            done = True
    if not done:
        raise SystemExit("%s: no cmake command found" % name)
    return "".join(out).encode("utf-8")


def patch_buildsh(data, name):
    """Run ./stage-data.sh between the native build and copyAssets.sh.

    The game data that ships inside the APK (AndroidData/*.zip.xz) has to be
    packed from THIS build's own lang/ and baseset/ output: the .lng files of an
    official OpenTTD package carry a different LANGUAGE_PACK_VERSION and every
    language would be rejected at startup, and the official package lacks the
    JGRPP base GRFs.  The native build is what produces lang/ and baseset(), and
    copyAssets.sh is the last moment anybody reads AndroidData, so the hook has
    to sit exactly between them.  stage-data.sh itself lives in the jgrpp-mobile
    repository (the release workflow copies it into the tree root), which is why
    the hook is a no-op when the file is absent.  Insists on LF endings, like
    the rest of the tree.
    """
    text = data.decode("utf-8")
    if "stage-data.sh" in text:
        return data
    hook = ("# jgrpp-mobile: pack this build's own lang/ and baseset/ into\n"
            "# AndroidData before copyAssets.sh copies it into the APK assets.\n"
            "[ -x ./stage-data.sh ] && ./stage-data.sh\n")
    out, done = [], False
    for line in text.splitlines(True):
        if not done and re.match(r"^\./copyAssets\.sh[ \t]*$", line):
            out.append(hook)
            done = True
        out.append(line)
    if not done:
        raise SystemExit("%s: no ./copyAssets.sh call found" % name)
    return "".join(out).encode("utf-8")


def patch_androidinput(data, name):
    """Long-pressing with one finger sends a right click.

    AndroidAppSettings.cfg sets AppNeedsTwoButtonMouse=y, which makes pelya's
    framework pick RIGHT_CLICK_WITH_MULTITOUCH: the *second* finger presses the
    right mouse button, so a two-finger drag pans the map and a two-finger tap
    is a right click.  A long press with one finger - the gesture phone users
    reach for first - does nothing: the timer in ProcessMouseMove_Timeouts only
    runs for RIGHT_CLICK_WITH_TIMEOUT, and choosing that method would stop the
    second finger from pressing the right button, costing us the pan.

    This keeps the multitouch method and adds the long press to it: a single
    finger that stays inside a 15th of the screen height for rightClickTimeout
    (1 s at the default RightClickTimeout=4, adjustable in the settings menu)
    releases the left button and sends a right click, exactly like the second
    finger does.  Movement, lifting the finger and a second finger going down
    all cancel it, so drag-building and two-finger panning are unaffected.

    The timeout thread has to be started for this combination too - it is what
    makes the long press fire while the finger stands still, and it is only
    created for the click-with-timeout methods upstream.
    """
    text = data.decode("utf-8")

    def sub(old, new):
        if text.count(old) != 1:
            raise SystemExit("%s: anchor not found exactly once:\n%s" % (name, old))
        return text.replace(old, new)

    # 1. Arm the timer when a single finger goes down, and wake the timeout
    #    thread the same way the click-with-timeout methods do.
    text = sub(
        "\t\tSDL_ANDROID_MainThreadPushMouseMotion(x, y);\n"
        "\t\tif( !hardwareMouseDetected || SDL_ANDROID_currentMouseButtons == 0 )\n"
        "\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_PRESSED, SDL_BUTTON_LEFT );\n"
        "\t}\n",
        "\t\tSDL_ANDROID_MainThreadPushMouseMotion(x, y);\n"
        "\t\tif( !hardwareMouseDetected || SDL_ANDROID_currentMouseButtons == 0 )\n"
        "\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_PRESSED, SDL_BUTTON_LEFT );\n"
        "\t\t// jgrpp-mobile: a long press with one finger is a right click too\n"
        "\t\tif( rightClickMethod == RIGHT_CLICK_WITH_MULTITOUCH && rightMouseButtonLongPress )\n"
        "\t\t{\n"
        "\t\t\tmouseInitialX = x;\n"
        "\t\t\tmouseInitialY = y;\n"
        "\t\t\tmouseInitialTime = SDL_GetTicks();\n"
        "\t\t\tmouseClickTimeout = rightClickTimeout + 10;\n"
        "\t\t\tif( mouseClickTimeoutInitialized )\n"
        "\t\t\t\tsem_post(&mouseClickTimeoutSemaphore);\n"
        "\t\t}\n"
        "\t}\n",
    )

    # 2. Run the timeout check for the multitouch method as well.
    text = sub(
        "\t\tleftClickMethod == LEFT_CLICK_WITH_TAP_OR_TIMEOUT || rightClickMethod == RIGHT_CLICK_WITH_TIMEOUT ) )\n",
        "\t\tleftClickMethod == LEFT_CLICK_WITH_TAP_OR_TIMEOUT || rightClickMethod == RIGHT_CLICK_WITH_TIMEOUT ||\n"
        "\t\t( rightClickMethod == RIGHT_CLICK_WITH_MULTITOUCH && rightMouseButtonLongPress ) ) )\n",
    )

    # 3. Fire it: let the left button go first, so a build drag that the down
    #    event started is not dragged on, then click the right button.
    text = sub(
        "\t\t\tif( rightClickMethod == RIGHT_CLICK_WITH_TIMEOUT )\n"
        "\t\t\t{\n"
        "\t\t\t\tif( SDL_GetTicks() - mouseInitialTime > rightClickTimeout )\n"
        "\t\t\t\t{\n"
        "\t\t\t\t\t//SDL_ANDROID_MainThreadPushMouseMotion(mouseInitialX, mouseInitialY);\n"
        "\t\t\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_PRESSED, SDL_BUTTON_RIGHT );\n"
        "\t\t\t\t\tmouseInitialX = -1;\n"
        "\t\t\t\t\tmouseInitialY = -1;\n"
        "\t\t\t\t}\n"
        "\t\t\t}\n",
        "\t\t\tif( rightClickMethod == RIGHT_CLICK_WITH_TIMEOUT ||\n"
        "\t\t\t\t( rightClickMethod == RIGHT_CLICK_WITH_MULTITOUCH && rightMouseButtonLongPress ) )\n"
        "\t\t\t{\n"
        "\t\t\t\tif( SDL_GetTicks() - mouseInitialTime > rightClickTimeout )\n"
        "\t\t\t\t{\n"
        "\t\t\t\t\t//SDL_ANDROID_MainThreadPushMouseMotion(mouseInitialX, mouseInitialY);\n"
        "\t\t\t\t\tif( rightClickMethod == RIGHT_CLICK_WITH_MULTITOUCH )\n"
        "\t\t\t\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_RELEASED, SDL_BUTTON_LEFT );\n"
        "\t\t\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_PRESSED, SDL_BUTTON_RIGHT );\n"
        "\t\t\t\t\tmouseInitialX = -1;\n"
        "\t\t\t\t\tmouseInitialY = -1;\n"
        "\t\t\t\t}\n"
        "\t\t\t}\n",
    )

    # 4. Lifting the finger ends a pending long press.
    text = sub(
        "\t\tif( leftClickMethod != LEFT_CLICK_WITH_KEY )\n"
        "\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_RELEASED, SDL_BUTTON_LEFT );\n"
        "\t}\n"
        "\n"
        "\tSDL_ANDROID_ShowScreenUnderFingerRect.w = SDL_ANDROID_ShowScreenUnderFingerRect.h = 0;\n",
        "\t\tif( leftClickMethod != LEFT_CLICK_WITH_KEY )\n"
        "\t\t\tSDL_ANDROID_MainThreadPushMouseButton( SDL_RELEASED, SDL_BUTTON_LEFT );\n"
        "\t}\n"
        "\tmouseInitialX = -1;\n"
        "\tmouseInitialY = -1;\n"
        "\n"
        "\tSDL_ANDROID_ShowScreenUnderFingerRect.w = SDL_ANDROID_ShowScreenUnderFingerRect.h = 0;\n",
    )

    # 5. A second finger is a gesture, so it cancels the long press.
    text = sub(
        "\tif( pointerId == secondMousePointerId && (action == MOUSE_DOWN || action == MOUSE_UP) )\n"
        "\t{\n",
        "\tif( pointerId == secondMousePointerId && (action == MOUSE_DOWN || action == MOUSE_UP) )\n"
        "\t{\n"
        "\t\t// jgrpp-mobile: a second finger is a gesture, not a long press\n"
        "\t\tmouseInitialX = -1;\n"
        "\t\tmouseInitialY = -1;\n",
    )

    # 6. Start the timeout thread for this combination too.
    text = sub(
        "\t\tleftClickMethod == LEFT_CLICK_WITH_TAP_OR_TIMEOUT ||\n"
        "\t\trightClickMethod == RIGHT_CLICK_WITH_TIMEOUT ) )\n",
        "\t\tleftClickMethod == LEFT_CLICK_WITH_TAP_OR_TIMEOUT ||\n"
        "\t\trightClickMethod == RIGHT_CLICK_WITH_TIMEOUT ||\n"
        "\t\t( rightClickMethod == RIGHT_CLICK_WITH_MULTITOUCH && rightMouseButtonLongPress ) ) )\n",
    )

    return text.encode("utf-8")


PATCHES = {
    APPCFG: patch_appcfg,
    GRADLE_TEMPLATE: patch_gradle,
    ANDROID_BUILD_SH: patch_androidbuild,
    BUILD_SH: patch_buildsh,
    SDL_ANDROID_INPUT: patch_androidinput,
}


def keep(name, isdir):
    """Filter for the packaging tree members, on tree-relative names."""
    if name.rsplit("/", 1)[-1] == ".gitmodules":
        return False
    for prefix in DROP_PREFIXES:
        if name.startswith(prefix):
            return False
    for prefix in DROP_SUBMODULES:
        if name == prefix or name.startswith(prefix + "/"):
            return False
    if name.startswith(APPLICATION_DIR):
        rest = name[len(APPLICATION_DIR):]
        if "/" in rest:
            return rest.split("/")[0] + "/" in KEEP_APPS
        # a file of the framework, or one of the app directories
        return not (isdir and rest and rest + "/" not in KEEP_APPS)
    return True


class _BytesReader:
    """File-like wrapper so tarfile.addfile() can take a bytes blob."""

    def __init__(self, data):
        self._data = data

    def read(self, size=-1):
        if size is None or size < 0:
            data, self._data = self._data, b""
            return data
        data, self._data = self._data[:size], self._data[size:]
        return data


def write_archive(out_path, parts, patched, png):
    """Write one component archive; member names relative to the tree root."""
    counts = {"members": 0, "skipped": 0, "symlinks": 0, "patched": 0}
    tar_path = out_path + ".tar"
    needs_png = png is not None and any(
        p.rel == PNG_DIR or p.rel.startswith(PNG_DIR + "/") for p in parts)
    with tarfile.open(tar_path, "w", format=tarfile.GNU_FORMAT) as out:
        for part in parts:
            with tarfile.open(part.tar) as tf:
                for member in tf:
                    name = member.name.rstrip("/")
                    full = (part.rel + "/" + name).lstrip("/") if part.rel else name
                    # Filter on the tree-relative name: a submodule's own member
                    # names are relative to it, so `keep()` would never see the
                    # `project/jni/...` prefixes it drops.
                    if not keep(full, member.isdir()):
                        counts["skipped"] += 1
                        continue
                    member = member.replace(name=full)
                    if not part.rel and name in patched:
                        data = patched[name]
                        member.size = len(data)
                        out.addfile(member, _BytesReader(data))
                        counts["patched"] += 1
                        continue
                    if member.issym() or member.islnk():
                        counts["symlinks"] += 1
                    if member.isfile():
                        out.addfile(member, tf.extractfile(member))
                    else:
                        out.addfile(member)
                    counts["members"] += 1
        if needs_png:
            info, data = png
            out.addfile(info, _BytesReader(data))
            counts["members"] += 1
    return counts


def build(src, outdir):
    tmp = tempfile.mkdtemp(prefix="packaging-tarball-")
    root_tar = os.path.join(tmp, "pelya.tar")
    print("Archiving %s (%s)" % (src, PELYA_BRANCH))
    archive(src, root_tar)
    root = Part(src, "", root_tar)

    dropped = []
    groups = [("01-commandergenius", [root])]
    for name, rel in SEEDS:
        parts = []
        print("Archiving %s" % rel)
        collect(src, rel, parts, tmp, dropped)
        if parts:
            groups.append((name, parts))

    # The three patched files live in the tree root, the libpng template inside
    # the sdl2_image component.
    wanted = set(PATCHES) | {PNG_PREBUILT}
    found = read_members(root_tar, wanted)
    for path in sorted(wanted - set(found)):
        # submodule archives store repository-relative names, so strip the
        # prefix of whichever component holds the file
        for _, parts in groups[1:]:
            for part in parts:
                if path == part.rel:
                    rel_name = ""
                elif path.startswith(part.rel + "/"):
                    rel_name = path[len(part.rel) + 1:]
                else:
                    continue
                got = read_members(part.tar, {rel_name})
                if rel_name in got:
                    found[path] = got[rel_name]
                    break
            if path in found:
                break
    missing = wanted - set(found)
    if missing:
        raise SystemExit("missing members: %s" % sorted(missing))
    patched = {name: PATCHES[name](found[name][0], name) for name in PATCHES}
    png_data, png_info = found[PNG_PREBUILT]
    png_info = png_info.replace(name=PNG_CONF)
    png_info.size = len(png_data)

    os.makedirs(outdir, exist_ok=True)
    manifest, total = [], 0
    for name, parts in groups:
        out_path = os.path.join(outdir, name + ".tar.xz")
        counts = write_archive(out_path, parts,
                               patched if name == "01-commandergenius" else {},
                               png=(png_info, png_data))
        print("Compressing %s" % os.path.basename(out_path))
        with open(out_path + ".tar", "rb") as fin, open(out_path, "wb") as fh:
            subprocess.run(["xz", "-T0", "-6", "-c"], stdin=fin, stdout=fh, check=True)
        os.remove(out_path + ".tar")
        size = os.path.getsize(out_path)
        total += size
        with open(out_path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        manifest.append({"name": os.path.basename(out_path), "size": size,
                         "sha256": digest, "counts": counts,
                         "repos": [(p.rel or ".", p.url, p.commit) for p in parts]})
        print("  %.1f MB, %d members (%d symlinks), %d patched, %d pruned"
              % (size / 1e6, counts["members"], counts["symlinks"],
                 counts["patched"], counts["skipped"]))

    write_manifest(os.path.join(outdir, "MANIFEST.txt"), manifest, dropped, total)
    print("total: %.1f MB in %d archives" % (total / 1e6, len(manifest)))


def write_manifest(path, manifest, dropped, total):
    with open(path, "w", newline="\n") as fh:
        fh.write("Packaging tree for the jgrpp Android build (see\n"
                 "packaging/README.md in the repository root).\n")
        fh.write("Generated %s by make-packaging-tarball.py.\n\n"
                 % datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%d %H:%M UTC"))
        fh.write("Unpack every archive into one empty build directory:\n")
        fh.write("    for a in packaging/tree/*.tar.xz; do tar -xJf \"$a\" -C <dir>; done\n\n")
        fh.write("Total %.1f MB.\n\n" % (total / 1e6))
        for entry in manifest:
            fh.write("%s\n" % entry["name"])
            fh.write("    %.1f MB, sha256 %s\n"
                     % (entry["size"] / 1e6, entry["sha256"]))
            fh.write("    %d members, %d symlinks, %d patched, %d pruned\n"
                     % (entry["counts"]["members"], entry["counts"]["symlinks"],
                        entry["counts"]["patched"], entry["counts"]["skipped"]))
            for rel, url, commit in entry["repos"]:
                fh.write("    %s = %s @ %s\n" % (rel, url, commit))
            fh.write("\n")
        if dropped:
            fh.write("Pruned submodules (no module of this app builds them):\n")
            for rel in sorted(set(dropped)):
                fh.write("    %s\n" % rel)
            fh.write("\n")
        fh.write("Pruned paths: the other project/jni/application sample apps,\n"
                 "project/jni/python, .gitmodules.\n")
        fh.write("Patched: APP_PLATFORM=android-24 in the app config, minSdk 24 in\n"
                 "build-template.gradle, -DANDROID_PLATFORM=android-24 in\n"
                 "AndroidBuild.sh, a ./stage-data.sh hook in build.sh,\n"
                 "pnglibconf.h materialised from libpng's prebuilt, and long-press\n"
                 "right click in SDL_androidinput.c.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="pelya/commandergenius checkout with submodules")
    ap.add_argument("output", nargs="?",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tree"))
    args = ap.parse_args()
    build(os.path.abspath(args.source), args.output)


if __name__ == "__main__":
    main()
