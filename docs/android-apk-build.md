# jgrpp-mobile Android APK 完整编译发布指南

从 JGRPP 上游拉取新版本，应用移动端补丁，编译 arm64-v8a APK 并发布到 GitHub Release。

## 1. 环境要求

| 工具 | 路径 / 版本 | 说明 |
|------|------------|------|
| Git Bash | MSYS2/MinGW64 | `D:\DevEnv\mingw64\bin` 必须在 PATH 最前 |
| Android SDK | `D:\AndroidSDK` | 含 build-tools/35.0.0 |
| Android NDK | `D:\AndroidSDK\ndk\28.2.13676358` | NDK r28 |
| JDK | 17+ | gradle 需要 |
| CMake | >= 3.17 | `G:\Program Files\CMake\bin\cmake.exe` |
| Gradle | SDK 自带 wrapper | 无需单独安装 |
| zip / unzip | Git Bash 内置 | 用于注入 APK |
| gh CLI | >= 2.x | GitHub Release 上传 |

### 环境变量（每次编译前设置）

```bash
export ANDROID_NDK_HOME="D:/AndroidSDK/ndk/28.2.13676358"
export ANDROID_HOME="D:/AndroidSDK"
export PATH="D:/DevEnv/mingw64/bin:$ANDROID_NDK_HOME:$PATH"
export MSYS2_ARG_CONV_EXCL='-D*'
export CMAKE_GENERATOR="MinGW Makefiles"
set -a   # 自动 export 后续变量
```

---

## 2. 拉取上游新版本并创建 mobile 分支

### 2.1 获取上游标签

```bash
cd /g/GitHub/jgrpp-mobile

# 拉取指定版本标签
git fetch upstream tag jgrpp-<NEWVER> --no-tags
```

上游 remote 已配置为 `https://github.com/JGRennison/OpenTTD-patches.git`。

### 2.2 创建 mobile 分支

```bash
# 删除旧分支（如存在）
git branch -D jgrpp-<NEWVER>-mobile 2>/dev/null

# 从上游标签创建新分支
git checkout -b jgrpp-<NEWVER>-mobile jgrpp-<NEWVER>
```

---

## 3. 应用移动端补丁

### 3.1 核心源码修改（5 个文件）

| 文件 | 修改内容 |
|------|---------|
| `src/table/settings/misc_settings.ini` | `gui_scale` 的 `def = 200`（原 `-1`） |
| `src/video/video_driver.cpp` | `bool _video_hw_accel = true;`（加 `= true` 初始化） |
| `src/video/sdl2_v.cpp` | 在 `SDL_StopTextInput()` 前后加 `#if !defined(__OHOS__)` / `#endif` |
| `src/video/sdl2_default_v.h` | 添加 `bool CreateMainWindow(uint w, uint h, uint flags = 0) override;` 声明 |
| `src/video/sdl2_default_v.cpp` | 添加 `CreateMainWindow` 实现，添加 `SDL_WINDOW_OPENGL` 标志后调用基类 |

具体 diff：

```diff
--- a/src/table/settings/misc_settings.ini
+++ b/src/table/settings/misc_settings.ini
@@ -372,7 +372,7 @@
 name     = ""gui_scale""
 type     = SLE_INT32
 var      = _gui_scale_cfg
-def      = -1
+def      = 200
 min      = -1
 max      = MAX_INTERFACE_SCALE
 cat      = SC_BASIC

--- a/src/video/video_driver.cpp
+++ b/src/video/video_driver.cpp
@@ -27,7 +27,7 @@
-bool _video_hw_accel;
+bool _video_hw_accel = true;

--- a/src/video/sdl2_v.cpp
+++ b/src/video/sdl2_v.cpp
@@ -981,7 +981,9 @@
 	MarkWholeScreenDirty();
 
-	SDL_StopTextInput();
+#if !defined(__OHOS__)
+	SDL_StopTextInput();
+#endif
 	this->edit_box_focused = false;

--- a/src/video/sdl2_default_v.h
+++ b/src/video/sdl2_default_v.h
@@ -18,6 +18,7 @@
 class VideoDriver_SDL_Default : public VideoDriver_SDL_Base {
 public:
 	const char *GetName() const override { return "sdl"; }
+	bool CreateMainWindow(uint w, uint h, uint flags = 0) override;

--- a/src/video/sdl2_default_v.cpp
+++ b/src/video/sdl2_default_v.cpp
@@ -40,6 +40,12 @@
 static FVideoDriver_SDL_Default iFVideoDriver_SDL_Default;
 
+bool VideoDriver_SDL_Default::CreateMainWindow(uint w, uint h, uint flags)
+{
+	flags |= SDL_WINDOW_OPENGL;
+	return this->VideoDriver_SDL_Base::CreateMainWindow(w, h, flags);
+}
+
```

### 3.2 移动端补丁提交

从 `jgrpp` 分支 cherry-pick 以下关键提交：

| 提交 | 说明 | 影响 |
|------|------|------|
| `b0b76beabf` | Fix emulator bring-up（探针基础设施 + SDL 视频驱动修复） | openttd.cpp, unix_main.cpp, strings.cpp, sdl2_opengl_v.cpp, sdl2_v.cpp |

注意：cherry-pick 时只需要 `src/` 目录的改动，`.github/` 和 `harmony/` 的冲突用 `git checkout --ours` 解决。

```bash
# 只 cherry-pick src/ 变更
git checkout b0b76beabf -- src/openttd.cpp src/os/unix/unix_main.cpp src/strings.cpp \
    src/video/sdl2_opengl_v.cpp src/video/sdl2_v.cpp
```

### 3.3 提交所有修改

```bash
git add -A src/
git commit -m "Local fixes: gui_scale=200, hw_accel=true, CreateMainWindow+SDL_WINDOW_OPENGL, skip StopTextInput on OHOS"
```

---

## 4. 更新版本信息

### 4.1 版本标记文件

```bash
# 获取上游版本的 commit hash
NEWVER="jgrpp-<NEWVER>"
COMMIT=$(git rev-parse "$NEWVER" 2>/dev/null | head -c 40)
DATE=$(git log -1 --format=%ad --date=format:%Y%m%d "$NEWVER" 2>/dev/null)
FULLHASH=$(git rev-parse "$NEWVER^{tree}" 2>/dev/null)

# 写入 .ottdrev-vc（cmake FindVersion.cmake 使用）
cat > .ottdrev-vc << EOF
${NEWVER}	${DATE}	0	${COMMIT}	1	0
${FULLHASH}  -
EOF

# 写入 .ottdrev
cat > .ottdrev << EOF
${NEWVER}	${DATE}	0	${COMMIT}	1	0
${FULLHASH}  -
EOF
```

### 4.2 AndroidManifest.xml 版本

编辑 `pelya树/project/AndroidManifest.xml` 和 `pelya树/project/app/src/main/AndroidManifest.xml`：

```xml
android:versionCode="<MAJOR><MINOR><PATCH>1"   <!-- 如 0.73.3 → 73031 -->
android:versionName="<MAJOR>.<MINOR>.<PATCH>"  <!-- 如 "0.73.3" -->
```

---

## 5. 编译

### 5.1 复制源码到 pelya 打包树

```bash
PELYA=/g/GitHub/sdl-android
APPDIR=$PELYA/project/jni/application/openttd-jgrpp
SRCDIR=/g/GitHub/jgrpp-mobile

# 清空旧源码
rm -rf "$APPDIR/src"
mkdir -p "$APPDIR/src"

# 用 git archive 复制（保留 mtime，避免全量重编）
cd "$SRCDIR"
git archive jgrpp-<NEWVER>-mobile | tar -xf - -C "$APPDIR/src"

# 验证文件数
find "$APPDIR/src" -type f | wc -l   # 应约 2200+
```

### 5.2 版本文件复制到 pelya 树

```bash
# .ottdrev-vc 必须在 cmake source root (即 $APPDIR/src/src/)
cp "$SRCDIR/.ottdrev-vc" "$APPDIR/src/src/.ottdrev-vc"
cp "$SRCDIR/.ottdrev"    "$APPDIR/src/src/.ottdrev"
```

### 5.3 AndroidPreBuild（host 工具）

```bash
cd "$PELYA/project/jni/application/openttd-jgrpp"
bash AndroidPreBuild.sh
```

首次需要编译 strgen/settingsgen host 工具，后续增量秒过。

### 5.4 第一次 ndk-build（预编译库）

```bash
cd "$PELYA"
bash "$ANDROID_NDK_HOME/ndk-build" -C project -j8 V=1 \
    CUSTOM_BUILD_SCRIPT_FIRST_PASS=1 NDK_APP_STRIP_MODE=none
```

编译 liblzma, libsdl-1.2, libsdl_native_helpers 等预编译库。

### 5.5 CMake 交叉编译（libapplication.so）

```bash
cd "$PELYA/project/jni/application"
make -f CustomBuildScript.mk -j8
```

此步骤运行 cmake configure + 编译全部 OpenTTD 源码。首次约 20 分钟，增量约 2 分钟。

产物：`src/libapplication-arm64-v8a.so`（SONAME = libapplication.so）

### 5.6 第二次 ndk-build

```bash
cd "$PELYA"
bash "$ANDROID_NDK_HOME/ndk-build" -C project -j8 V=1 NDK_APP_STRIP_MODE=none
```

将 libapplication.so 打包成 libsdl_main.so 等最终 so 文件。

### 5.7 数据文件准备

```bash
cd "$PELYA"

# 下载/验证数据包（首次）
bash stage-data.sh

# 复制到 assets 目录
bash copyAssets.sh
```

### 5.8 Gradle 打包

```bash
cd "$PELYA/project"
./gradlew assembleRelease
```

产物：`app/build/outputs/apk/release/app-release-unsigned.apk`

---

## 6. APK 注入 + 对齐 + 签名

### 6.1 注入 libs 和 assets

```bash
BUILD_TOOLS="$ANDROID_HOME/build-tools/35.0.0"
cd "$PELYA/project"

APK="app/build/outputs/apk/release/app-release-unsigned.apk"
ALIGNED="app/build/outputs/apk/release/app-release-aligned.apk"
SIGNED="app/build/outputs/apk/release/jgrpp-<NEWVER>-mobile.apk"

# 清理旧文件（如有）
zip -d "$APK" 'lib/*' 'assets/*' 2>/dev/null

# 注入（注意：必须在 project/ 目录下运行，保证相对路径正确）
zip -0 -rD "$APK" lib/arm64-v8a
zip -rD "$APK" assets
```

**关键**：`zip -0 -rD` 必须在 `project/` 目录下执行，使 APK 内路径为 `lib/arm64-v8a/*.so`。如果在其他目录执行，会生成 `GitHub/sdl-android/...` 前缀的路径导致安装失败。

### 6.2 Zipalign

```bash
"$BUILD_TOOLS/zipalign" -p -f 4 "$APK" "$ALIGNED"
```

### 6.3 签名

```bash
"$BUILD_TOOLS/apksigner.bat" sign \
    --ks "$HOME/.android/debug.keystore" \
    --ks-pass pass:android \
    --ks-key-alias androiddebugkey \
    --out "$SIGNED" "$ALIGNED"
```

### 6.4 验证

```bash
# 验证签名
"$BUILD_TOOLS/apksigner.bat" verify --print-certs "$SIGNED"

# 验证版本
"$BUILD_TOOLS/aapt2" dump badging "$SIGNED" | grep versionName

# 验证 so 路径
unzip -l "$SIGNED" | grep "lib/arm64-v8a/libapplication.so"
```

---

## 7. 发布到 GitHub Release

### 7.1 创建 Release

```bash
cd /g/GitHub/jgrpp-mobile

GH_REPO=Maicarons/jgrpp-mobile gh release create jgrpp-mobile-<NEWVER> \
  --title "jgrpp-mobile-<NEWVER>" \
  --notes "JGRPP <NEWVER> mobile port (Android arm64-v8a)

Based on upstream JGRPP jgrpp-<NEWVER>.

Changes:
- Default GUI scale set to 200% for mobile screens
- Hardware acceleration enabled by default
- SDL window created with OpenGL flag for mobile drivers
- Skip SDL_StopTextInput on mobile (prevents deadlock)
- Probe infrastructure for startup debugging (logcat)
- AllocateBackingStore defers allocation until GL context is ready" \
  "$SIGNED"
```

### 7.2 更新已有 Release（覆盖附件）

```bash
# 删除旧附件
GH_REPO=Maicarons/jgrpp-mobile gh release delete-asset jgrpp-mobile-<NEWVER> "jgrpp-<NEWVER>-mobile.apk" --yes

# 上传新附件
GH_REPO=Maicarons/jgrpp-mobile gh release upload jgrpp-mobile-<NEWVER> "$SIGNED"
```

---

## 8. 常见问题

### Q: cmake 使用了 Visual Studio 生成器而非 MinGW

**A:** 确保在运行 `AndroidBuild.sh` 时 `CMAKE_GENERATOR="MinGW Makefiles"` 已正确 export。或在命令行直接指定：

```bash
CMAKE_GENERATOR="MinGW Makefiles" bash AndroidBuild.sh arm64-v8a aarch64-linux-android
```

### Q: 全量重编耗时长

**A:** 不要用 `build.sh openttd-jgrpp`（它 `cp -rL` 重置全部 mtime）。用 `git archive` 或 `tar -C openttd-jgrpp -cf - . | tar -xf - -C src` 保留 mtime，实现增量编译。

### Q: 游戏内版本号不对

**A:** 检查 `.ottdrev-vc` 文件。cmake 的 `FindVersion.cmake` 优先读取此文件确定版本。清除 cmake 缓存（`rm -rf openttd-build-*/CMakeCache.txt openttd-build-*/generated/rev.cpp`）后重新编译。

### Q: APK 安装失败 INSTALL_FAILED_INVALID_APK

**A:** zip 注入时必须使用 `zip -0`（不压缩存储 .so 文件），且必须在 `project/` 目录下执行以保证相对路径正确。

### Q: 游戏黑屏

**A:** 确认 `gui_scale = 200`、`_video_hw_accel = true`、`CreateMainWindow` 覆盖均已在源码中正确应用。可在 logcat 中查看 `[ottd probe]` 探针输出来定位启动阶段。

---

## 9. 一键快速命令（已验证环境）

```bash
# ============ 环境变量 ============
export ANDROID_NDK_HOME="D:/AndroidSDK/ndk/28.2.13676358"
export ANDROID_HOME="D:/AndroidSDK"
export PATH="D:/DevEnv/mingw64/bin:$ANDROID_NDK_HOME:$PATH"
export MSYS2_ARG_CONV_EXCL='-D*'
export CMAKE_GENERATOR="MinGW Makefiles"
set -a

NEWVER="0.73.3"  # 修改为实际版本号
PELYA=/g/GitHub/sdl-android
SRCDIR=/g/GitHub/jgrpp-mobile
BUILD_TOOLS="$ANDROID_HOME/build-tools/35.0.0"

# ============ 1. 源码复制 ============
cd "$SRCDIR" && git checkout "jgrpp-$NEWVER-mobile" 2>/dev/null
rm -rf "$PELYA/project/jni/application/openttd-jgrpp/src"
mkdir -p "$PELYA/project/jni/application/openttd-jgrpp/src"
git archive "jgrpp-$NEWVER-mobile" | tar -xf - -C "$PELYA/project/jni/application/openttd-jgrpp/src"
cp .ottdrev-vc "$PELYA/project/jni/application/openttd-jgrpp/src/src/.ottdrev-vc"
cp .ottdrev    "$PELYA/project/jni/application/openttd-jgrpp/src/src/.ottdrev"

# ============ 2. 清除 cmake 缓存（确保版本正确） ============
rm -rf "$PELYA/project/jni/application/openttd-jgrpp/src/openttd-build-arm64-v8a"

# ============ 3. 编译 ============
cd "$PELYA/project/jni/application/openttd-jgrpp" && bash AndroidPreBuild.sh
cd "$PELYA" && bash "$ANDROID_NDK_HOME/ndk-build" -C project -j8 CUSTOM_BUILD_SCRIPT_FIRST_PASS=1 NDK_APP_STRIP_MODE=none
cd "$PELYA/project/jni/application" && make -f CustomBuildScript.mk -j8
cd "$PELYA" && bash "$ANDROID_NDK_HOME/ndk-build" -C project -j8 NDK_APP_STRIP_MODE=none
cd "$PELYA" && bash stage-data.sh && bash copyAssets.sh
cd "$PELYA/project" && ./gradlew assembleRelease

# ============ 4. 注入 + 对齐 + 签名 ============
APK="app/build/outputs/apk/release/app-release-unsigned.apk"
ALIGNED="app/build/outputs/apk/release/app-release-aligned.apk"
SIGNED="app/build/outputs/apk/release/jgrpp-$NEWVER-mobile.apk"
zip -d "$APK" 'lib/*' 'assets/*' 2>/dev/null
zip -0 -rD "$APK" lib/arm64-v8a
zip -rD "$APK" assets
"$BUILD_TOOLS/zipalign" -p -f 4 "$APK" "$ALIGNED"
"$BUILD_TOOLS/apksigner.bat" sign --ks "$HOME/.android/debug.keystore" --ks-pass pass:android --ks-key-alias androiddebugkey --out "$SIGNED" "$ALIGNED"

echo "=== APK: $PELYA/project/$SIGNED ==="
ls -lh "$SIGNED"

# ============ 5. 发布 ============
cd "$SRCDIR"
GH_REPO=Maicarons/jgrpp-mobile gh release create "jgrpp-mobile-$NEWVER" \
  --title "jgrpp-mobile-$NEWVER" \
  --notes "JGRPP $NEWVER mobile port (Android arm64-v8a)" \
  "$PELYA/project/$SIGNED"
```
