# JGRPP Mobile

[JGRPP](https://github.com/JGRennison/OpenTTD-patches)（OpenTTD 的大型补丁包）的
**Android 移植与发布仓库**。上游游戏源码、构建脚手架、发布产物按分支分层存放，
不挤在同一个分支里。

## 分支与发布模型

| ref | 放什么 |
| --- | --- |
| `main`（默认分支） | 只有构建脚手架：`packaging/`（打包树归档）、`.github/workflows/`、`docs/`、`stage-data.sh`、`harmony/`。**没有游戏源码。** |
| `jgrpp-<版本>-mobile` | 该版本**可编译的 JGRPP 源码**（含 Android 移植补丁）+ 脚手架副本。归档必须跟着分支走：tag 构建只用被 tag 的那一个 ref。 |
| tag `jgrpp-mobile-<版本>` | 一次发布，产物 `OpenTTD-JGR-<版本>.apk`。 |

仓库只保留最近几个版本分支。

发布是人工触发的三步，完整步骤见 `docs/release.md`：

1. 在版本分支上更新上游源码、重放移植补丁，本地构建 APK 并真机确认
   （能启动、有图形与声音、能进游戏）；
2. `git tag jgrpp-mobile-<版本> && git push origin jgrpp-<版本>-mobile --tags`；
3. tag 触发 **Android APK Release**：云端从同一个 ref 重建 APK 并挂到同名
   Release；失败会自动开 issue。

`Upstream Release Watcher` 只做一件事：发现上游有新版本、而本仓库还没有对应
Release 时开提醒 issue。它**不会**自动合并、推送、打 tag 或触发构建。

## 打包树随仓库携带

Android 打包依赖 pelya 的 commandergenius 框架（Gradle 工程、Java 壳、
SDL/ICU/freetype 等交叉编译依赖）。上游已停止更新，所以整棵树以 `git archive`
的形式搬进本仓库：`packaging/tree/*.tar.xz`，6 个归档、133.4 MB、约 1.66 万个
文件（含 94 个软链与可执行位）。本地与 CI 都从这里解包，**不再 clone 任何外部
仓库**，构建可只凭一个 ref 复现。

* 来源、裁剪范围、已烘焙的补丁、重建步骤：`packaging/README.md`；
* 归档不变量检查：`python packaging/verify-packaging.py`
  （必需路径、软链、可执行位、CRLF、以及「被裁剪的编解码目录却被默认开启的
  `Android.mk` 引用」这类会直接把 ndk-build 打挂的错误）。

## 资源必须打进 APK

首次启动从 APK 的 `assets/` 读数据。除原版图形音效（GPL 不允许随仓库分发，
由 `stage-data.sh` 在构建期下载）外，**语言包 / baseset / AI / game 数据
（`openttd-data-*.zip.xz`）、Timidity MIDI 音源、ICU 数据**都打进 `assets/*.xz`，
启动时解包。数据包必须取自本次构建自己的 `lang/`、`baseset/`，否则语言包版本
哈希不匹配，启动即报 `No available language packs (invalid versions?)`。

## 产物

* 两个 ABI：`armeabi-v7a` + `arm64-v8a`；`minSdk 24`（Android 7.0 起）；
* `versionCode` 由 tag 推出：`<minor><patch>1`（0.73.4 → `73041`）；
* 用调试密钥签名，仅用于自测分发。

## 文档

| 文件 | 内容 |
| --- | --- |
| `docs/android-build.md` | 本地（Windows）构建流程，与 CI 一致，含 Windows 专属修正 |
| `docs/release.md` | 发布流程、资源打包、上游监听与失败处理 |
| `docs/touch.md` | 触控手势表、触屏相关设置、手机端补丁落点 |
| `packaging/README.md` | 打包树来源、裁剪、烘焙补丁、重建与校验 |
| `docs/android-apk-build.md` | 早期单 ABI 本地打包记录（历史参考） |
| `docs/ohos-build.md`、`harmony/` | HarmonyOS 移植（暂停） |

## 上游与许可

游戏本体与补丁来自
[JGRennison/OpenTTD-patches](https://github.com/JGRennison/OpenTTD-patches)。
OpenTTD 依 **GPL v2** 授权，见 `COPYING.md`；上游版权与致谢见 `CREDITS.md`；
打包树内各第三方组件的版本与许可见 `packaging/README.md`。上游 changelog 在
版本分支的 `jgrpp-changelog.md`。
