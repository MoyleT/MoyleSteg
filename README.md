# Moyle 隐写工坊 · Steganography Studio

把秘密藏进图片或动图。支持 Windows 和 Android 的本地文件加密与恢复工具，提供 PNG 隐写、GIF 动画载体、独立 SAES、口令和密钥文件，以及三种主题。

Local encrypted steganography and file recovery for Windows and Android: PNG, animated GIF, standalone SAES, password/key-file protection and three themes.

**[Windows 1.5.1 下载](https://github.com/MoyleT/MoyleSteg/releases/tag/v1.5.1)** · **[Android 0.3.0-alpha 下载](https://github.com/MoyleT/MoyleSteg/releases/tag/android-v0.3.0-alpha)**

![星夜 · 深邃蓝紫](docs/screenshots/theme-midnight.png)

## 选择版本 / Choose a version

| 平台 | 当前版本 | 安装与说明 |
|---|---|---|
| Windows x64 | 1.5.1 | 下载 `MoyleSteg-1.5.1-Windows-Portable.zip`，完整解压后打开 `MoyleSteg.exe`。保留 `_internal` 文件夹。 [桌面说明](README_DESKTOP.md) |
| Android 8.0+ | 0.3.0-alpha | 下载 `MoyleSteg-Android-0.3.0-alpha-debug.apk`。当前为调试签名预发布版本。 [手机说明](MoyleSteg-Android/README.md) |

Windows 的完整工程包另含源码和便携运行目录。Android 的 Source ZIP 包含可构建工程。GitHub 自动生成的 Source code ZIP 包含两端源码，不包含 EXE 或 APK。

Windows portable releases include Python and dependencies; extract the whole directory. Android is an alpha debug-signed APK. Automatically generated GitHub source archives contain source only.

## 本轮变化 / Changes

- **Windows 1.5.1**：改善 Python 像素计算期间的界面响应。无效路径、容量不足、失败、取消及容量预检后保留口令，成功时只清理本次使用页，关闭时清理全部。口令不写入设置或日志。
- **Android 0.3.0-alpha**：独立 SAES 加密、恢复、只读验证与导出采用分块文件处理，原文件最多 1 GiB；加入自动／手动内存预算及真实文件头尺寸提示。
- **GIF**：两端都能使用动画载体，保留原动画块。Windows 1.5.1 已包含 1.5.0 的 GIF 支持；GIF 使用标准应用扩展封装密文，不能据此声称无法检测。
- **已有功能**：认证后按原名与格式恢复、PNG 自动扩容、实际容量预检、两种 SHA-256、协作式取消与三主题继续保留。

Desktop retry credential retention has not yet been ported to Android. Android still clears form credentials at task/lifecycle boundaries. The gallery 0×0 addition reports header information; it does not repair third-party gallery indexes.

## 大文件与兼容 / Files and compatibility

PNG/SAES format v1 and `.stegkey` remain compatible with Windows 1.4.1; GIF requires Windows 1.5.0 or newer. The current desktop and mobile versions can exchange supported containers using the same password or key.

Android's **1 GiB limit applies to standalone SAES**. PNG/GIF remain limited to 32 MiB original payload and 128 MiB container bytes, with pixel/frame and actual-memory limits. Automatic PNG expansion remains budgeted. Manual memory budget does not reserve RAM or override Android's app heap limit. Large SAES operations need temporary storage and foreground execution; background resume is not implemented.

电脑版恢复默认 256 MiB 载荷预算，较大文件需要调整高级恢复设置并具有足够内存；电脑版载荷处理仍主要使用内存。格式兼容不代表所有设备都能处理相同大小的文件。

请按原始文件传输。PNG 像素变化或 GIF 重编码可能破坏隐藏数据；完整容器摘要可用于比较传输前后字节。AES-256-GCM 认证隐藏文件及内部元数据，GIF 外层动画由完整容器摘要另行标识。遗失正确凭据后没有恢复后门。

## 验证范围 / Validation

| 本次版本记录 | 结果 |
|---|---|
| Windows 完整源码回归（Qt offscreen） | 692 项通过 |
| Windows 源码、冻结 EXE 原生自检 | 各 65 项通过 |
| Android SAES 流式回归 | 30 项通过 |
| Android Robolectric 主机流程与资源策略 | 70 项通过 |
| 1 GiB 合成随机 SAES | 128 MiB JVM 堆下，密钥模式完整往返与验证通过 |
| 新旧格式跨端补充矩阵 | 32 项通过 |

以上是维护方合成数据验证，计数不相加。Android 主机/JVM 测试不是手机速度或真实 Compose、图库、系统文件选择器验收；本轮未执行 Android 真机或模拟器测试。Windows 流畅度改进也不保证所有同步计算无延迟。

[Windows 更新与验证](docs/RELIABILITY_1.5.1.md) · [Android 验证](MoyleSteg-Android/verification/TEST_REPORT_0_3_0.md) · [手机资源边界](MoyleSteg-Android/docs/LARGE_FILES_0_3_0.md) · [GIF 协议](docs/GIF_1.5.0.md)

## 三种主题 / Three themes

| 樱桃奶霜 · Blossom | 墨黑荧绿 · Terminal |
|---|---|
| ![樱桃奶霜](docs/screenshots/theme-blossom.png) | ![墨黑荧绿](docs/screenshots/theme-terminal.png) |

电脑端保留果汁、数据流和流星进度视觉。截图为合成演示界面，不作为运行测试证据。

## 从源码构建 / Build from source

Windows 使用 Python 3.10+：运行 `Setup-Desktop.ps1`，再运行 `.venv/Scripts/python.exe main.py`；完整测试入口为 `scripts/run_tests.py full`，打包入口为 `Build-Desktop.ps1`。依赖和 CLI 说明见 [README_DESKTOP.md](README_DESKTOP.md)。

Android 工程位于 [MoyleSteg-Android](MoyleSteg-Android)，采用 Kotlin + Jetpack Compose。构建环境、官方 Gradle Wrapper、协议及核心测试命令见其 [README](MoyleSteg-Android/README.md)。不需要手机安装 Python。

公开源码来自已核验的发布文件，包含许可和明确的合成测试夹具，不包含本机工作笔记、原始私人报告、构建缓存或签名私钥。历史文档保留其当时版本的结果。
