# 本地 Android 构建流程（Windows）

本文档描述如何在 Windows 上从 `jgrpp-mobile` 源码树本地构建 Android APK，
流程与 `.github/workflows/android-release.yml`（CI）保持一致，并记录了
Windows 下必须的适配补丁。CI 在 Linux 上运行；本地（Git Bash）需要额外
几步修正，见下文「Windows 专属修正」。文中所有路径均为占位符，请替换为
本机实际路径。

## 原理：为什么不在 jgrpp-mobile 目录里直接编译

`jgrpp-mobile` 只是 OpenTTD/JGRPP 的 C++ 源码树，本身不是 Android 工程：
没有 Gradle 工程、AndroidManifest.xml、Java 壳，也没有 SDL/ICU/freetype
等需要交叉编译的第三方库。Android 打包依赖 **pelya/commandergenius**
（SDL Android 打包框架，下文称「打包树」）：

- `jgrpp-mobile/CMakeLists.txt` 在 `ANDROID` 分支下 `include(AndroidSDL)`，
  而 `AndroidSDL.cmake` 由打包树中的构建脚本生成（见源码里该处的注释）；
- CI 的工作方式：克隆 commandergenius → 把 jgrpp-mobile 源码拷进
  `project/jni/application/openttd-jgrpp/src` → 在打包树内用
  ndk-build + CMake + Gradle 产出 APK。

本地构建必须复刻同一套结构。

## 占位符约定

| 占位符 | 含义 |
| --- | --- |
| `<repo>` | jgrpp-mobile 源码树所在目录（如 `D:\dev\jgrpp-mobile`） |
| `<sdl-android>` | commandergenius 打包树目录（如 `D:\dev\sdl-android`） |
| `<ANDROID_SDK_ROOT>` | Android SDK 根目录 |
| `<NDK_DIR>` | NDK 目录（`<ANDROID_SDK_ROOT>/ndk/<version>`，需自带 `ndk-build`） |
| `<JAVA_HOME>` | JDK 17 安装目录 |
| `<BUILD_TOOLS>` | build-tools 版本目录（如 `<ANDROID_SDK_ROOT>/build-tools/35.0.0`） |
| `<MINGW_BIN>` | GNU make 所在目录（MSYS2 mingw64 的 `bin`） |

## 前置条件

| 组件 | 说明 |
| --- | --- |
| Android SDK | 含 build-tools（35.0.0）、platforms（android-24+）、cmdline-tools |
| Android NDK | r28 左右即可，需自带 `ndk-build`（r28 仍带） |
| Java | JDK 17 |
| CMake | 3.2x+（4.x 亦可用） |
| GNU make | 4.x，来自 MSYS2/mingw64 |
| 其他 | Git Bash（自带 perl/unzip/xz/curl）、`zip`、调试用 `keytool` |

## 一、准备打包树

```bash
# 1. 克隆 commandergenius（sdl_android 分支），与 CI 相同
git clone --depth 1 -b sdl_android https://github.com/pelya/commandergenius.git <sdl-android>
cd <sdl-android>

# 2. 初始化 SDL2 相关子模块（png/jpeg 头文件在 sdl2_image 的嵌套子模块里，
#    不 init 会导致 jni/png/include 指向空目录）
git submodule update --init --recursive --depth=1 project/jni/sdl2_image \
  project/jni/sdl2_mixer project/jni/sdl2_ttf project/jni/sdl2

# 3. 生成 libpng 的 pnglibconf.h（仓库不携带，用自带模板）
PNG=project/jni/SDL2_image/external/libpng
[ -f "$PNG/pnglibconf.h" ] || cp "$PNG/scripts/pnglibconf.h.prebuilt" "$PNG/pnglibconf.h"
```

## 二、放入 jgrpp-mobile 源码

```bash
APP=project/jni/application/openttd-jgrpp
rm -rf $APP/src && mkdir -p $APP/src
cp -r <repo>/. $APP/src/ && rm -rf $APP/src/.git
# Git for Windows 默认 autocrlf=true，拷进来的 .sh 全是 CRLF，必须先转 LF
find $APP/src -name "*.sh" -exec sed -i 's/\r$//' {} +
```

## 三、与 CI 对齐的配置补丁

```bash
# 3.1 根目录与 app 目录两份 AndroidAppSettings.cfg 保持同步修改
CFG=AndroidAppSettings.cfg
sed -i 's/^APP_PLATFORM=.*/APP_PLATFORM=android-24/' $CFG          # getifaddrs() 需 API 24
sed -i "s/^MultiABI=.*/MultiABI='arm64-v8a'/" $CFG                  # 本地调试只编一个 ABI
cp $CFG $APP/AndroidAppSettings.cfg

# 3.2 Gradle minSdk 同步到 24
sed -i 's/minSdk 21/minSdk 24/' project/app/build-template.gradle

# 3.3 给 AndroidBuild.sh 的 cmake 命令行注入 ANDROID_PLATFORM=android-24
#     （否则 CMake 用 setEnvironment 里的 APILEVEL=21，编译 host.cpp 会报
#       getifaddrs undeclared）
awk '1; /^[[:space:]]*cmake[[:space:]]/{print "\t-DANDROID_PLATFORM=android-24 \\"}' \
  $APP/AndroidBuild.sh > /tmp/ab.tmp && mv /tmp/ab.tmp $APP/AndroidBuild.sh && chmod +x $APP/AndroidBuild.sh
```

## 四、Windows 专属修正（CI 不需要，本地必须）

### 4.1 NDK 二进制缺执行位

Windows 下 NDK 解压后 `ndk-build` 及 llvm 工具链丢失 `+x`，Git Bash 的
`which` 找不到 `ndk-build`，`setEnvironment-*.sh` 里的
`NDK=\`which ndk-build\`` 会拿到空值，工具链路径变成 `/toolchains/llvm/prebuilt//bin/...`：

```bash
chmod -R +x <NDK_DIR>/toolchains/llvm/prebuilt/windows-x86_64/bin
chmod +x <NDK_DIR>/ndk-build
```

### 4.2 setEnvironment 识别不了 Git Bash 的 uname

Git Bash 的 `uname -s` 返回 `MINGW64_NT-10.0-*`，匹配不到
`grep -i "windows"`，`MYARCH` 为空。在四个
`project/jni/iconv/src/setEnvironment-{arm64-v8a,armeabi-v7a,x86,x86_64}.sh`
的 if/elif 链 `fi` 之后追加兜底：

```sh
[ -z "$MYARCH" ] && MYARCH=windows-x86_64
```

### 4.3 Makefile.prebuilt 的 recipe 里 PATH 被 msys 转成 Windows 格式

`project/jni/Makefile.prebuilt` 的 iconv/icu 目标用
`env ARCHS=$$ARCH PATH=$(PATH):${ANDROID_NDK_HOME} ./build.sh` 起 make 子进程。
从 Git Bash 启动的 make 是 native 进程，环境里的 PATH 已被 msys 转成
`;` 分隔的 Windows 格式，嵌进 `sh -c` recipe 后直接语法错误。
（给 make 传命令行变量 `PATH=...` 不可靠，msys 会对环境变量做双向转换。）
把 recipe 里的 PATH 换成固定的 POSIX 列表：

```bash
NDK_POSIX=<NDK_DIR 的 /d/... 形式，例如 /d/AndroidSDK/ndk/28.2.13676358>
sed -i "s|env ARCHS=\$\$ARCH PATH=\$(PATH):\${ANDROID_NDK_HOME} ./build.sh|env ARCHS=\$\$ARCH PATH=/usr/bin:/bin:/usr/local/bin:<MINGW_BIN>:$NDK_POSIX ./build.sh|" \
  project/jni/Makefile.prebuilt
```

（`<MINGW_BIN>` 提供 GNU make；`/usr/bin` 提供 sh/cp/sed/perl 等。
`/mingw64/bin` 提供 `xz`，否则 harfbuzz 的 `.tar.xz` 解不开。）

### 4.4 mingw make 找到的 `sh.exe` 带空格

mingw GNU make 忽略环境变量 `SHELL`，自己在 PATH 里找 `sh.exe` 并写进
Makefile（`$(SHELL)`）。Git Bash 的 `sh.exe` 位于
`D:\Program Files\Git\usr\bin`（带空格），运行的 recipe 直接报
`D:/Program: No such file or directory`。把 Git 的 sh 复制到无空格目录，
并让该目录在（msys 转换后的 Windows）PATH 中最先出现：

```bash
# sh.exe 放入无空格目录（不存在才复制）
[ -e <MINGW_BIN>/sh.exe ] || cp /usr/bin/sh.exe <MINGW_BIN>/sh.exe
```

`Makefile.prebuilt` 的 recipe PATH 也按此顺序组织（4.3 的 sed 里应写成）：

```bash
PATH=/d/DevEnv/mingw64/bin:/mingw64/bin:/usr/bin:/bin:/usr/local/bin:<NDK_DIR 的 /d/... 形式>
```

（本地构建时外层也要 `export PATH="/d/DevEnv/mingw64/bin:$PATH"`。）

### 4.4 libiconv 的 `-DLIBDIR`/`-DINSTALLDIR` 宏在 Git Bash 下编译失败

libiconv configure 生成的编译参数形如 `-DLIBDIR=\"/g/GitHub/.../lib\"`。
mingw make 执行 recipe 时会丢掉引号、msys 再把这个 `-D` 值里的 POSIX 路径
转成 `G:/...`（手工执行同一条 recipe 却正常——破坏发生在 make 执行层，
与 MSYS2_ARG_CONV_EXCL 关系不大）。clang 报
`error: use of undeclared identifier 'G'`（宏变成裸标识符）。

处理方式：在 `project/jni/iconv/src/build.sh` 解包 libiconv 之后打两个补丁
（重定位机制对 Android 毫无意义，且原路径在设备上不存在，运行时行为不变）：

```bash
# 1) 关闭 ENABLE_RELOCATABLE（连带 INSTALLDIR 等带引号宏失去引用点）
find . -name '*.c' -exec sed -i 's/#if ENABLE_RELOCATABLE/#if 0/g' {} +
# 2) localcharset.c 在守卫之外还引用 LIBDIR，换成常量兜底
find libiconv-1.15 -name 'localcharset.c' -exec sed -i 's|dir = relocate (LIBDIR);|dir = "/lib";|' {} +
```

另外建议导出（防御其他带路径的 `-D` 参数）：

```bash
export MSYS2_ARG_CONV_EXCL='-D*'
```

（`-I`/`-L` 保持默认转换，交叉编译器需要 Windows 路径。）

### 4.5 ICU 62 交叉构建的两个 Windows 专属 bug

（都在 `project/jni/iconv/src/build.sh` 的 ICU 段内修复，两段 ICU configure 都要照顾。）

**icucross.inc 找不到**：`icudefs.mk` 里 `include $(cross_buildroot)/config/icucross.inc`。
`--with-cross-build=` 传 POSIX 绝对路径（`/g/...`）时，native make stat 不了
（按当前盘符的相对路径解析）；传相对路径 `cross` 又会在子目录 make 里错位。
正确做法：Windows 上转成盘符绝对路径 `G:/...`：

```bash
CROSSB=`pwd`/cross
if uname -s | grep -qiE 'NT|MINGW|MSYS'; then
    CROSSB=`cygpath -m "$CROSSB"`
fi
# ... --with-cross-build=$CROSSB \ ...
```

**pkgdata 编译报 `member reference base type 'const char[40]'`**：
`tools/pkgdata/Makefile.in` 定义 `DEFS += -DUDATA_SO_SUFFIX=\".$(SO)\"`，
引号在 make/sh 链上丢失后宏变成裸 `.so`。configure 之后把宏中和为空
（`#ifdef UDATA_SO_SUFFIX` 仍成立，相邻字符串拼接也合法）：

```bash
sed -i 's/-DUDATA_SO_SUFFIX=[^ ]*/-DUDATA_SO_SUFFIX=/' tools/pkgdata/Makefile
```

**数据打包 icupkg 静默失败（rc 127，无任何输出）**：
`data/Makefile` 的工具调用经 `$(INVOKE)`（来自 host 构建生成的
`cross/config/icucross.mk`）带上运行期 PATH。make 导出的 PATH 是分号+空格
形式，直接写进 recipe 会被 sh 拆词（`Files\...` 127）；就算展开正常，
`G:/...` 正斜杠盘符条目也不能被 Windows DLL 加载器使用（icutu62.dll 在
cross/lib 里找不到就 127）。host 构建完成后（Windows 下）把 icucross.mk 里
两条 INVOKE/PKGDATA_INVOKE 的 PATH 整个钉成 MSYS 形式（msys 会为子进程
自动转成反斜杠路径）：

```bash
CROSSABS="$BUILDDIR/$ARCH/icu/source/cross"
sed -i "s@^INVOKE=PATH=.*@INVOKE=PATH=$CROSSABS/lib:$CROSSABS/stubdata:$CROSSABS/tools/ctestfw:/usr/bin:/bin:/d/DevEnv/mingw64/bin @" cross/config/icucross.mk
sed -i "s@^PKGDATA_INVOKE=PATH=.*@PKGDATA_INVOKE=PATH=$CROSSABS/stubdata:$CROSSABS/tools/ctestfw:$CROSSABS/lib:/usr/bin:/bin:/d/DevEnv/mingw64/bin @" cross/config/icucross.mk
```

（上一节把 `cross_buildroot` 改成盘符绝对路径是为了让 `icudefs.mk` 的
`include $(cross_buildroot)/config/icucross.inc` 在 native make 里解析成功，
两处互不冲突。）

### 4.7 zipalign/apksigner

`build.sh` 结尾要跑 `apksigner`，但 SDK 里只有 `apksigner.bat`，Git Bash 调不起来。
建一个 bash 封装并放进 PATH：

```bash
mkdir -p local-bin
cat > local-bin/apksigner <<EOF
#!/bin/sh
exec java -jar "<BUILD_TOOLS>/apksigner.jar" "\$@"
EOF
chmod +x local-bin/apksigner
```

## 五、游戏数据打包（AndroidData → APK assets）

APK 首次启动时按 `AndroidAppSettings.cfg` 的 `AppDataDownloadUrl` 从 assets
读取三个数据文件（都在 `/AndroidData/*.xz`，仓库不携带，每次现做）：

- `openttd-data-0.40.4-0.zip.xz`：**本版构建产物**的 `lang/` + `baseset/` +
  `ai/` + `game/`，再叠加 OpenGFX 8.0（基础图形）+ OpenSFX 1.0.3（音效）
- `timidity.zip.xz`：MIDI 音色（打包树自带 `project/jni/timidity/samples/timidity.zip`）
- `icudt62l.zip.xz`：ICU 数据（由 ICU 预编译产出 `icudt*.dat`）

> **数据必须取自本版构建产物，不能用官方包。** 官方 OpenTTD 包的
> `lang/*.lng` 带的是**别的** `LANGUAGE_PACK_VERSION` 哈希，游戏启动时会被
> 全部拒绝（语言列表为空 → 静默退出）；官方包的 `baseset/` 也缺 OpenTTD
> 字体（`OpenTTD-*.ttf`）和 JGRPP 自带的基础 GRF（`extra_signals.grf`、
> `progsignals.grf`、`route_step.grf`、`tracerestrict.grf` 等）。这些都只有
> `openttd-build-<abi>/` 里有。

仓库根目录提供 `stage-data.sh`（幂等：已存在则跳过），下载缓存放
`.stage-cache/`；脚本自己定位 `project/jni/application/*/openttd-build-*/`
（要求其中已有 `lang/` 与 `baseset/`，否则直接报错退出）。它必须在**原生构建
完成之后、copyAssets 之前**运行，所以 `build.sh` 已在 `./copyAssets.sh` 之前
调用它：

```bash
grep -n "copyAssets.sh" build.sh   # 期望：
# ${ANDROID_NDK_HOME}/ndk-build -C project ...   （NDK 依赖全量编译）
# [ -x ./stage-data.sh ] && ./stage-data.sh
# ./copyAssets.sh
```

本地构建前先把仓库里的脚本同步到打包树根目录（CI 由
**Install data staging script** 步骤自动完成）：

```bash
cp <repo>/stage-data.sh <sdl-android>/stage-data.sh
chmod +x <sdl-android>/stage-data.sh
```

本地与 CI 的一个差别：CI 里 `project/jni/application/src` 是指向
`openttd-jgrpp` 的符号链接，而本地 `run-arm64.sh` step1 会把
`openttd-jgrpp` **整体复制**成 `src`。`copyAssets.sh` 读的是
`src/AndroidData`，所以脚本在本地会把数据包写进 `src/AndroidData`，同时镜像一份
回 `openttd-jgrpp/AndroidData`（否则下次 step1 的复制会用旧包覆盖新包）。

> **Windows 必读：`app/src/main/assets` 必须是真实目录或目录 junction。**
>
> CI（Linux）中 `project/app/src/main/assets` 是指向 `project/assets` 的符号链接，
> Gradle/AGP 会正常跟随。但在 Windows 上它被检出为**文件型 reparse point**
> （`dir` 显示为 `<SYMLINK>` 且计入“文件”），AGP **不把它当目录遍历**：
> `generateReleaseAssets` 报 `UP-TO-DATE`、`build/intermediates/assets` 为空，
> 最终 APK 里**没有任何 `assets/openttd-data-*`**（体积少约 26 MB），
> 首次启动转去联网下载，离线打包即失效。
> `copyAssets.sh` 本身正常写入了 `project/assets`，只是 Gradle 看不到。
>
> 处理：用**目录 junction**替换该符号链接（junction 是目录型 reparse point，
> AGP 能遍历；`copyAssets.sh` 仍会同步写入 `project/assets`，无需每次重建链接）：
>
> ```bat
> rmdir "project\app\src\main\assets"
> mklink /J "project\app\src\main\assets" "project\assets"
> ```
>
> 或者改用真实目录，并在每次 `assembleRelease` 之前把 `project/assets/*`
> 拷进去（需重复执行，否则数据会过期）。
> 校验：`unzip -l app-release-unsigned.apk | findstr assets/openttd-data` 必须有输出。

> **另一个 Windows 坑：换了数据包后 Gradle 不会重新合并 assets。**
> `app/src/main/assets` 是 junction 时，AGP 的 `mergeReleaseAssets` 跑过一次就
> 一直报 `UP-TO-DATE`——即使 `project/assets/` 里同名文件的内容和体积都变了
> （实测 mtime 更新也不会触发），APK 里永远是旧数据包。改完 `AndroidData/*.xz`
> 后必须删掉该中间产物再构建：
>
> ```bash
> rm -rf project/app/build/intermediates/assets
> ```
> （`run-arm64.sh` step7 已内置这一步。）

## 六、执行构建

```bash
cd <sdl-android>

export ANDROID_NDK_HOME="$NDK_POSIX"
export ANDROID_SDK_ROOT="<ANDROID_SDK_ROOT>"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export JAVA_HOME="<JAVA_HOME>"
export MSYS2_ARG_CONV_EXCL='-D*'
export PATH="<sdl-android>/local-bin:$ANDROID_NDK_HOME:<BUILD_TOOLS>:<ANDROID_SDK_ROOT>/platform-tools:$JAVA_HOME/bin:$PATH"

# 6.1 根据 cfg 重新生成工程文件（Application.mk / gradle / JavaGlobals 等）
#     最后会编译 prebuilt 库（openssl/icu/boost，取决于 CompiledLibraries）。
./changeAppSettings.sh -a

# 6.2 若上一步的 ICU 预编译失败过，可单独重跑（约 1 小时/ABI）：
# make -C project/jni -f Makefile.prebuilt icu ARCH_LIST="$(grep -Po "MultiABI='\K[^']+" AndroidAppSettings.cfg)"

# 6.3 完整构建：ndk-build 依赖库 → stage-data → copyAssets → gradle。
#     注意 build.sh 到此为止：它不会注入原生库、也不会 strip。本地用
#     run-arm64.sh（step8/step9 会 strip + 注入 + zipalign + 签名），或按第七节
#     「APK 里没有 lib」一行手动补。
./build.sh openttd-jgrpp
```

产物：

- APK：`project/app/build/outputs/apk/release/app-release.apk`
  （build.sh 会用 `~/.android/debug.keystore` 自动签名；没有就
  `keytool -genkey ...` 生成一个）
- 原生库：`project/jni/application/openttd-jgrpp/libapplication-<abi>.so`
- 依赖库：`project/obj/local/<abi>/`

## 七、已知坑与排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `which: no ndk-build in (...)`, configure 报 `C compiler cannot create executables` | 4.1 / 4.2 | 补执行位 + MYARCH 兜底，然后 `rm -rf project/jni/iconv/src/arm64-v8a` 重跑 |
| `error: use of undeclared identifier 'G'`（-DLIBDIR 宏被拆） | 4.4 | 导出 `MSYS2_ARG_CONV_EXCL='-D*'` 后重跑 |
| 菜单：`Failed connecting to openttd-data-0.40.4-0.zip.xz` | AndroidData 没打进去 | 确认 `stage-data.sh` 在 build.sh 的 copyAssets 之前执行 |
| 本地 APK 缺 `assets/openttd-data-*`（体积少约 26 MB），但 CI 产物正常 | Windows 下 `app/src/main/assets` 是符号链接，AGP 不按目录遍历（见第五节） | `rmdir` 后 `mklink /J project\app\src\main\assets project\assets` 换成目录 junction |
| Gradle 下载发行版报 `unable to find valid certification path` | Java 证书链问题（偶发） | 重跑即可；或 curl 手动下载 gradle-8.11.1-bin.zip 放入 `~/.gradle/wrapper/dists/gradle-8.11.1-bin/<hash>/` |
| `src/` 里的 .sh 一跑就报错 | CRLF 行尾 | `sed -i 's/\r$//' *.sh` |
| CMake 找不到 AndroidSDL.cmake | 打包树结构不对 | AndroidBuild.sh 在带 `-DCMAKE_MODULE_PATH` 的 cmake 命令行里生成它，别手动删 `src` 下文件 |
| cmake 配置完 `make` 报"no makefile" | cmake 默认选了 Ninja 生成器 | 构建环境导出 `CMAKE_GENERATOR="MinGW Makefiles"` |
| fontconfig 报 `ft2build.h not found` / png 报 `pnglibconf.h` | `jni/freetype/include`、`jni/png/include` 是 git 符号链接，原生 clang 解析不了 | `rm -rf` 后用真实目录替换（`cp -r <实际源码include> <链接位>`） |
| `CustomBuildScript.mk`/`Android.mk` 报 `/libapplication-*.so` 不存在 | `APPDIR := $(shell readlink src)` 在 src 为真实目录/junction 时取空 | 两处 `APPDIR := src`（构建树内补丁；CI 的 src 是符号链接不受影响） |
| `use of undeclared identifier` | src 里的本地源码没同步（`cp` 层级） | 参照日志里 `src\src\src\...` 的实际层级复制 |
| gradle `:app:minifyReleaseWithR8`/javac `filename syntax is incorrect` | `local.properties` 的 `sdk.dir=D:\AndroidSDK` 反斜杠被 Properties 当转义 | 改为 `sdk.dir=D:/AndroidSDK` |
| gradle 要求 shrink 配合 minify | `shrinkResources true` + `minifyEnabled false` | 本地调试把两项都设 false（CI 保持 true） |
| APK 只有 4.8MB、无 .so | `copyAssets.sh pack-binaries` 依赖根目录 `base/`（Windows 下缺失） | 手动补：`cd project && zip -rD <apk> lib assets`，再 zipalign + apksigner |
| 安装报 `INSTALL_FAILED_INVALID_APK: Failed to extract native libraries` | targetSdk 36 下原生库必须**未压缩**存储 | 注入时用 `zip -0`（STORE）而非默认 deflate |
| 启动即崩（SDL_main 后 ~30ms 静默退出），探针停在 config 之后 | 语言包列表为空：数据包缺 `lang/`，或 lang 来自官方包（LANGUAGE_PACK_VERSION 哈希与本版不匹配，全被拒） | 数据包的 `lang/*.lng` 必须取自**本版 strgen 构建产物**（`openttd-build-<abi>/lang/`），baseset 同样取构建产物（含 OpenTTD 字体） |
| 语言加载后仍崩（探针停在 fonts 前） | baseset 缺 OpenTTD 字体（`OpenTTD-*.ttf`） | baseset 用构建产物而非官方包 |
| APK 里**没有** `lib/**/*.so`，装上打不开（CI 旧产物仅 ~36 MB） | pelya 模板没把 `project/lib` 接成 jniLibs，`copyAssets.sh pack-binaries` 又只打 `AndroidData/lib`（没人往那里写） | 原生构建完成后手动注入 `project/lib/<abi>/*.so`（CI：workflow 的「Inject and strip the native libraries」；本地：run-arm64.sh step8） |
| APK 265 MB（单 ABI） | 原生库带 `-g`（`-DCMAKE_BUILD_TYPE=RelWithDebInfo`），且为手动注入，AGP 不会自动 strip | 注入前对 `lib/*/*.so` 跑 `llvm-strip --strip-unneeded`；单 ABI 由 221 MB 降到 18 MB，APK 由 265 MB 降到约 61 MB |
| 换了数据包但 APK 里还是旧数据 | junction 下 AGP 的 `mergeReleaseAssets` 永远 `UP-TO-DATE`（见第五节） | `rm -rf project/app/build/intermediates/assets` 后再构建 |

## 八、时间参考（本机实测）

- ICU/iconv 预编译（单 ABI，含全部 Windows 兼容补丁）：约 1.5 小时
  （host ICU 约 15 分钟 + 交叉 ICU 约 40 分钟 + icu-le-hb/iculx 约 20 分钟）
- ICU 后增量重跑（守卫跳过，仅补产）：约 1 分钟
- ndk-build 依赖库（SDL/freetype/fontconfig/png/lzma 等）：约 15 分钟
- openttd CMake 交叉编译：约 15 分钟
- stage-data + copyAssets：约 2 分钟
- gradle assembleRelease（含依赖下载）：约 1~4 分钟
- 产物：`project/app/build/outputs/apk/release/app-release.apk`
  （剥离符号后单 ABI 约 61 MB；不剥离约 265 MB。debug key 签名）