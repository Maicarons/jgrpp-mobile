# 发布流程（jgrpp-mobile）

本文档描述 `jgrpp-mobile` 的分支模型与发布流程。核心原则：

- **默认分支 `main` = 只放脚手架**：Android/鸿蒙编译必备文件、CI、所有编译/发布文档。
  不含游戏源码。
- **版本分支 `jgrpp-<ver>-mobile` = 可编译的源码 + 一份随行脚手架**，自包含，
  CI 单次 checkout 即可构建。
- **发布由人工触发**：本地构建通过后打 tag，tag 触发云端 CI 重新构建，
  产物自动挂到 GitHub Release。
- **目前只发布 Android（APK）**；鸿蒙编译/发布暂停（见文末）。
- **游戏资源必须打包进 APK**，首次启动不依赖联网下载。

## 1. 分支模型

| 分支 | 内容 | 用途 |
| --- | --- | --- |
| `main` | 仅脚手架（`harmony/`、`.github/`、构建文档、工程配置） | 落地页 / 模板；新的版本分支从这里取脚手架 |
| `jgrpp-<ver>-mobile` | 上游 jgrpp 源码（含手机端改动，直接改源码）+ 同一份脚手架 | 实际构建与发布 |

> `main` 采用**孤立历史**（root commit），与版本分支没有共同祖先，
> 因此二者之间不会因为 merge 而误删对方文件。脚手架如有更新，需要人工
> 同步到版本分支（可把 `main` 当作模板对照）。

## 2. 发布步骤

1. **更新版本分支**（人工）
   - 按 watcher 开的 issue，取上游 `jgrpp-<ver>` 源码；
   - 重新套用手机端改动（直接改源码，见 `docs/android-build.md`）；
   - 确认版本分支里带着脚手架（`harmony/`、`.github/`、构建文档）；
   - 版本号写入 `.ottdrev` / `AndroidAppSettings.cfg` 相应位置。

2. **本地构建并验证**（人工）
   - 按 `docs/android-build.md` 在 Windows 上构建 APK；
   - 安装到真机/模拟器，确认能启动、有图形与声音、能进游戏。

3. **打 tag 触发云端构建**（人工）
   ```sh
   git tag jgrpp-mobile-<ver>
   git push origin jgrpp-<ver>-mobile --tags
   ```
   - tag 名必须匹配 `jgrpp-mobile-*`；
   - 触发 `.github/workflows/android-release.yml`，云端重新构建 APK；
   - 构建成功后自动创建 / 更新 `jgrpp-mobile-<ver>` Release 并上传 APK。

4. **失败处理**
   - `android-release.yml` 失败会自动开 / 追加 issue；
   - 修好版本分支后重新推送 tag（或 `workflow_dispatch` 手动重跑）。

## 3. 资源打包（必须）

APK 首次启动按 `AndroidAppSettings.cfg` 的 `AppDataDownloadUrl` 从 APK assets
的 `/AndroidData/*.xz` 读取数据。`android-release.yml` 的
**Stage app data assets** 步骤会现场生成并打进 APK：

- `openttd-data-0.40.4-0.zip.xz`：baseset（含 OpenGFX 图形、OpenSFX 音效、
  `no_music`/`no_sound` 集合）+ `lang/` + `ai/` + `game/`；
- `timidity.zip.xz`：MIDI 音色；
- `icudt62l.zip.xz`：ICU 数据。

这些文件**不入库**（CI 每次现做、带缓存）。改上游数据版本时同步更新
`android-release.yml` 里对应的 URL 与文件名。

## 4. 上游监视

`.github/workflows/upstream-watch.yml` 每 6 小时检查上游
`JGRennison/OpenTTD-patches` 的最新 release：

- 若本仓库还没有对应的 `jgrpp-mobile-<ver>` Release，就开一个 issue 提醒
  人工走第 2 节流程；
- **不会**自动合并、推送、打 tag 或触发构建；
- 手动 `workflow_dispatch` 并填 `force_version` 可强制提醒某个版本。

## 5. 鸿蒙（暂停）

鸿蒙 HAP 的构建/发布**暂时停用**：workflow 已改名为
`.github/workflows/ohos-release.yml.disabled`，GitHub 不会执行它。
恢复时改名回 `ohos-release.yml` 即可；`harmony/` 目录与
`docs/ohos-build.md` 均保留。
