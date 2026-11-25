# 本地 HarmonyOS/OpenHarmony 构建流程

本文档描述如何在 Windows 上构建 `jgrpp-mobile` 的 HarmonyOS（OpenHarmony）
产物：先由 `harmony/build-ohos.sh` 交叉编译原生库（`libopenttd.so` + SDL3 +
依赖），再用 DevEco Studio 的 hvigor 把 ArkTS 工程打成 HAP。
与 `.github/workflows/ohos-release.yml`（CI）保持一致。路径均为占位符。

## 占位符约定

| 占位符 | 含义 |
| --- | --- |
| `<repo>` | jgrpp-mobile 源码树目录 |
| `<DEVECO>` | DevEco Studio 安装目录（含 sdk/tools/ohpm/tools/node/tools/hvigor） |
| `<OHOS_NATIVE_SDK>` | OpenHarmony 原生 SDK：`<DEVECO>/sdk/default/openharmony/native` |
| `<OHOS_CLANG_PREFIX>` | 新版 clang 前端目录（见下） |

## 前置条件

- DevEco Studio 6.x（自带 OpenHarmony SDK、hvigor、ohpm、node）
- 交叉编译工具：cmake、ninja、git、curl/wget、tar
- **新版 clang 前端**：OpenTTD 需要 C++20 的 P0634（无 typename 的
  dependent name）与括号聚合初始化，SDK 自带的 OHOS clang 15 不支持。
  `harmony/build-ohos.sh` 里做了「新前端编译 + OHOS clang 15 驱动链接」的
  拆分封装，需要设置 `OHOS_CLANG_PREFIX`（Windows 上例如某个 mingw64/llvm
  bin 目录；CI 用 Ubuntu 的 `/usr/lib/llvm-18/bin`）。
  不设置会报 `missing 'typename' prior to dependent type` / 聚合初始化错误。

## 一、交叉编译原生库

```bash
cd <repo>
OHOS_CLANG_PREFIX=<新版 clang 所在目录，如 /d/DevEnv/mingw64/bin> \
  bash harmony/build-ohos.sh
```

脚本流程（幂等，已存在的产物跳过）：

1. zlib / freetype / lzo / liblzma → `<repo>/harmony/build/prefix/<abi>/`
2. SDL3（OpenHarmony 后端，libsdl-org/SDL 的 PR #13152 分支）
3. sdl2-compat（SDL2 → SDL3 兼容层；本地补丁把 `libSDL3.so.0` 的 dlopen
   名字改成实际产物 `libSDL3.so`）
4. host-tools（strgen/settingsgen，本机原生编译）
5. jgrpp：CMake 交叉编译 `libopenttd.so`（`cmake/OhosSDL.cmake` 是脚本生成的
   模块，指向 `build/prefix` 里的依赖；另注入 `FindOpenGL.cmake`——OHOS 侧
   GL 全走 SDL 的 `SDL_GL_GetProcAddress`，无需链接）
6. 把全部 `.so`（含 libc++_shared）装入 `harmony/app/entry/libs/<abi>/`
7. 游戏数据（baseset/lang/ai/game/media/scripts + OpenGFX 基础包 + 默认
   `openttd.cfg` 视频驱动 `sdl2-opengl`）装入
   `harmony/app/entry/src/main/resources/rawfile/openttd/`

产物：`harmony/app/entry/libs/{arm64-v8a,x86_64}/libopenttd.so` 等。

## 二、HAP 打包（hvigor）

```bash
cd <repo>/harmony/app
export DEVECO_SDK_HOME="<DEVECO>/sdk"
export PATH="<DEVECO>/tools/ohpm/bin:<DEVECO>/tools/node:$PATH"

# 首次/依赖变更时
ohpm install --all

# 构建 unsigned HAP（release）
"<DEVECO>/tools/node/node.exe" "<DEVECO>/tools/hvigor/bin/hvigorw.js" \
  --no-daemon assembleHap --mode module -p product=default -p buildMode=release
```

注意：Git Bash 下不要用 `cmd //c ...hvigorw.bat`（参数引号会被 cmd 吞掉），
直接用 node 跑 `hvigorw.js`。

产物：`harmony/app/entry/build/default/outputs/default/entry-default-unsigned.hap`
（约 74 MB，含双 ABI 原生库与 rawfile 游戏数据；签名配置为空，产物为
unsigned）。签名需要 DevEco Studio 的签名配置（自动签名/证书），与 CI 一致。

## 三、调试辅助

`src/openttd.cpp` / `src/os/unix/unix_main.cpp` 里有 `__OHOS__` 宏保护的
启动探针 `ohos_probe()`：里程碑通过 SDL_Log 打到 hilog（`hdc shell hilog -x`
可见），同时追加写入 `/data/local/tmp/ottd.probe`，用于模拟器上定位启动
卡点。手柄/触屏排查参考 `harmony/*.jpg/png` 截图与 `hl*.txt` 日志。

## 四、常见问题
| 视频驱动初始化失败（SDL_CreateWindow 报 "Could not initialize OpenGL / GLES library"） | SDL3 的 EGL 分支按 `libGLESv2.so` 找库，OpenHarmony 只提供 `libGLESv3.so` | 给 `SDL_ohos` 的 `src/video/SDL_egl.c` 加 `#elif defined(SDL_VIDEO_DRIVER_OHOS)` 分支，GLES 库名全部用 `libGLESv3.so` |
| 配置里的视频驱动不生效 | 正确配置键是 `[misc] videodriver = sdl-opengl`（不是 `[video] driver`；驱动注册名是 `sdl-opengl` 而非 sdl2-opengl） | build-ohos.sh 生成的 openttd.cfg 用 `[misc] videodriver = sdl-opengl` |
| 模拟器上视频 GL 上下文创建后进程仍在但无画面 | 模拟器软件 EGL 建 GL 上下文疑似挂起（渲染器层，待查） | 排查模拟器 GPU/EGL 渲染后端配置 |

| 模拟器上数据拷贝后游戏仍找不到 lang（启动即崩在语言/配置阶段） | Index.ets 的 `ctx.filesDir` 是 el2 模块路径，而游戏（`SDL_GetPrefPath`→`getInternalPath`→`getHostContext().filesDir`）搜索 `$HOME/openttd/lang`（本模拟器 HOME=`/storage/Users/currentUser` 虚拟路径） | 拷贝目标写为 `/storage/Users/currentUser/openttd`（沙箱虚拟路径，`fs.*` 可写） |
| 模拟器是 x86_64 而 `build-ohos.sh` 默认只编 arm64-v8a | 库已存在时脚本守卫跳过重编 | `OHOS_ARCH=x86_64` + `rm harmony/build/prefix/x86_64/lib/libopenttd.so` 强制 |
| 视频驱动初始化崩溃（`AllocateBackingStore` SIGSEGV in SDL3） | SDL3-OHOS 渲染后端 surface 分配问题（端口深层 bug，待查） | 排查 SDL3 的 surface/backing-store 路径 |


| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `missing 'typename' prior to dependent type` / `no matching constructor for initialization` | 用了 OHOS clang 15 老前端 | 设置 `OHOS_CLANG_PREFIX` 重跑 |
| sdl2-compat 启动即 abort（LoadSDL3 失败） | dlopen 名 `libSDL3.so.0` vs 产物 `libSDL3.so` | 应用 build-ohos.sh 里的 SDL3_LIBNAME 补丁 |
| 首屏黑屏/无渲染 | SDL3 OHOS 无软件帧缓冲 | 确认 rawfile 里有 `openttd.cfg`（`[video] driver = sdl2-opengl`）且链的是 OpenGL renderer |
| 游戏提示缺基础包 | baseset 为空 | OpenGFX 必须作为 `.tar` 放进 `rawfile/openttd/baseset/`（放 `data/` 只会变成 NewGRF） |