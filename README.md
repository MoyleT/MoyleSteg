# Moyle 隐写工坊 · Steganography Studio

把一个或多个秘密文件藏进图片或动图。Windows 与 Android 均支持本地加密、按原名恢复、只读验证、口令／密钥文件及三种主题。JPG 照片载体输出 PNG，GIF 载体输出可播放的 GIF，也可以直接生成独立 SAES 加密文件。

Local encrypted steganography for Windows and Android. Hide one or multiple files in PNG or animated GIF, use JPEG photos as PNG-output carriers, or encrypt directly to SAES. Restore original filenames, verify content and choose from three themes.

**[Windows 1.6.0 下载](https://github.com/MoyleT/MoyleSteg/releases/tag/v1.6.0)** · **[Android 0.4.1-alpha 下载](https://github.com/MoyleT/MoyleSteg/releases/tag/android-v0.4.1-alpha)**

![星夜 · 深邃蓝紫](docs/screenshots/theme-midnight.png)

## 选择版本 / Choose a version

| 平台 | 当前版本 | 安装与说明 |
|---|---|---|
| Windows x64 | 1.6.0 | 下载 `MoyleSteg-1.6.0-Windows-Portable.zip`，完整解压后打开 `MoyleSteg.exe`，保留 `_internal` 文件夹。[桌面说明](README_DESKTOP.md) |
| Android 8.0+ | 0.4.1-alpha | 下载 `MoyleSteg-Android-0.4.1-alpha-debug.apk`。调试签名预发布版本，versionCode 9，与 0.3.2-alpha 使用相同签名。[手机说明](MoyleSteg-Android/README.md) |

Windows 完整工程包另含源码与便携运行目录；Android Source ZIP 包含可构建工程。GitHub 自动生成的 Source code ZIP 包含两端源码，不包含 EXE 或 APK。

Windows portable packages include Python and dependencies. Keep the whole extracted directory. Android is a debug-signed alpha APK; its source builds with Kotlin and Jetpack Compose and needs no Python runtime on the phone.

## 一个容器，多个文件 / Multiple files in one container

1. 选择 JPG／PNG／GIF 载体，添加最多 **100 个文件**；独立 SAES 不需要载体。列表可添加、移除并查看数量与大小。
2. 隐藏到图片时，先点击实际容量预检；应用会完成真实 ZIP 打包，显示原始总量、ZIP 大小及图片容量或扩容结果。
3. 设置**同一组口令或密钥**，统一加密整个包，再保存 PNG／GIF／SAES 成品。
4. 在新版任一端认证后查看文件清单，选择部分或全部保存。同名自动改名，失败或取消时保留已保存项，剩余项可直接重试，无需再次解密。

Two or more selected files become one marked standard ZIP protected by one shared password or key. Current apps authenticate the container and inspect every member before showing the recovery list. Save selected or all remaining members, or export the complete ZIP. Each saved file is independently checked; retry does not save successful members again.

单文件保持原流程；用户自己的普通 ZIP 仍按一个文件恢复，不会自动拆开。Windows 保存到所选恢复目录，Android 多文件先选后保存到 `Download/`，每项提供“打开文件”。手机单文件及普通 ZIP 继续自动保存到 Download。

[Windows 多文件说明](docs/MULTIFILE_1.6.0.md) · [Android 多文件流程与格式](MoyleSteg-Android/docs/MULTIFILE_0_4_0.md)

## 本轮变化 / Changes

- **Windows 1.6.0**：增加多选／拖入、真实 ZIP 预检、认证后的成员清单、按需保存和完整 ZIP 导出。保留 1.5.1 的界面响应改进，以及路径失败、容量不足、失败、取消和预检后的口令保留；成功时清理本页口令，关闭时清理全部。
- **Android 0.4.1-alpha**：本次相对已发布的 0.3.2-alpha 增加多文件流程，并完善临时空间、文件选择取消和导航成果保护。
- **手机临时空间**：按捕获、ZIP、加密封装和成员恢复阶段检查新增空间需求，保留 **32 MiB** 余量；ZIP 回读验证后释放源捕获副本。写入途中检查空间，明确报告磁盘不足。
- **手机文件选择**：取消或更换选择会停止旧任务并向支持取消的提供方传递请求，尝试关闭读取句柄；迟到结果不能替换新选择。外部提供方忽略取消时仍可能需要等待。
- **手机成果保留**：设置往返保留文件列表、当前子功能与认证结果；重复点击当前页不重置。切换功能或清空尚未保存的成果前确认丢弃，已保存的公共文件保留。

Android now preserves the current task across settings, cancels obsolete document selections and checks private workspace by processing stage. The 32 MiB allowance is a free-space check, not a reservation. Existing Download saving, open-with actions, PNG expansion, key tools and themes remain available.

[Android 可靠性说明](MoyleSteg-Android/docs/RELIABILITY_0_4_1.md) · [Download 保存与打开](MoyleSteg-Android/docs/DOWNLOAD_RESTORE_0_3_2.md) · [Windows 原有可靠性改进](docs/RELIABILITY_1.5.1.md)

## 大文件与兼容 / Files and compatibility

PNG／SAES／`.stegkey` 继续使用原有 v1 格式；GIF 需要 Windows 1.5.0 或更新的兼容版本。多文件是在既有加密载荷中放入标准 ZIP，没有改变外层加密格式。旧版 Windows 可以恢复整个 `MoyleSteg-files.zip` 后自行解压；直接显示和选择成员需要 Windows 1.6.0 或当前 Android 版。

| 预算 | Windows | Android |
|---|---|---|
| 原始文件／多文件原始总量 | 默认 256 MiB；完整 ZIP 也受载荷预算限制 | PNG／GIF 为 32 MiB；独立 SAES 为 1 GiB；完整 ZIP 同样受限 |
| 完整恢复容器 | 默认 512 MiB；高级恢复设置可调整 | PNG／GIF 为 128 MiB；SAES 为 1 GiB + 1 MiB |
| 图片资源 | 默认 25,000,000 像素，可在高级恢复设置中受控调整 | 最多 100,000,000 像素，并受应用堆、实际内存及 GIF 帧数限制 |

ZIP 头和索引也占容量，多选文件不会增加图片容量。手机的 **1 GiB 指独立 SAES**，不代表图片隐写能处理同样大小。Windows 仍主要使用内存处理载荷；Android 的流式 ZIP／SAES 不代表图片处理也已流式化。临时空间、内存预算和像素预算分别生效。

Format compatibility does not imply equal device capacity. Larger mobile SAES files may need higher desktop recovery budgets and sufficient RAM. Automatic or manual memory budgets do not reserve RAM or bypass Android's heap limit; keep long tasks in the foreground. No background resume is promised.

PNG 像素变化、转换 JPG 或 GIF 重编码可能破坏隐藏内容，请按原始文件传输。完整容器 SHA-256 用于比较传输文件字节，原始文件 SHA-256 用于比较恢复内容，两者不能混用。AES-256-GCM 保护内容与内部元数据，不保证隐写不可检测；遗失正确凭据后没有恢复后门。

[手机资源边界](MoyleSteg-Android/docs/LARGE_FILES_0_3_0.md) · [GIF 协议](docs/GIF_1.5.0.md)

## 验证范围 / Validation

| 实际执行 | 结果与范围 |
|---|---|
| Windows 全量测试 | 815 项通过；发生在最终列表排版收尾之前 |
| Windows 后续定向测试 | 最终排版修改后 47 项原生 Qt 测试通过 |
| Windows 最终 EXE | 73 项原生自检通过，包含多文件实际界面操作、保存及窄屏大字号布局 |
| Android 主机／Robolectric | 196 项通过，0 失败、错误或跳过 |
| Kotlin core:check | 通过，包含私有磁盘 15 项、受管 ZIP 20 项及既有协议回归 |
| 双端多文件互通 | PNG／GIF／SAES × 口令／密钥 × 两个方向，共 12 组通过、60 次成员恢复核对 |
| Android 构建与 lint | APK 和设备测试 APK 构建通过；lint 0 错误、9 条警告 |

Windows 三行是不同测试轮次，不能相加；815 也不是最终排版后再次执行的全量数字。Android 各测试类已计入相应总数，Robolectric 和编译成功不等于设备测试通过。**本版未在 Android 手机或模拟器上执行安装、系统提供方／权限弹窗、Compose 渲染或性能验收。** 全部测试数据为合成内容。

Current validation distinguishes host tests, native Windows EXE checks and Android device testing. Android device acceptance remains pending. Historical version reports retain their original scope and are not counted as new runs.

[Windows 验证说明](docs/MULTIFILE_1.6.0.md#release-checks--发布验证) · [Android 本版验证](MoyleSteg-Android/verification/TEST_REPORT_0_4_1.md) · [双向容器结果](MoyleSteg-Android/verification/0.4.1-alpha/cross-end-envelope-summary.json) · [旧参考实现验证](MoyleSteg-Android/verification/0.4.1-alpha/reference-envelope-verification.json)

## 三种主题 / Three themes

| 樱桃奶霜 · Blossom | 墨黑荧绿 · Terminal |
|---|---|
| ![樱桃奶霜](docs/screenshots/theme-blossom.png) | ![墨黑荧绿](docs/screenshots/theme-terminal.png) |

三主题保留稳定布局和各自的控件风格。桌面提供中文／English、大字号、减少动效，并保留果汁、数据流和流星进度视觉。以上为合成内容的主题示意截图，不作为本版运行测试证据。

## 从源码构建 / Build from source

Windows 使用 Python 3.10+：运行 `Setup-Desktop.ps1`，再运行 `.venv/Scripts/python.exe main.py`。完整测试入口为 `.venv/Scripts/python.exe scripts/run_tests.py full`，打包入口为 `Build-Desktop.ps1`。依赖、CLI 和预算设置见 [README_DESKTOP.md](README_DESKTOP.md)。

Android 工程位于 [MoyleSteg-Android](MoyleSteg-Android)，采用 Kotlin + Jetpack Compose 并附官方 Gradle Wrapper。在配置 JDK／Android SDK 后，可运行 `gradlew.bat :core:check :app:testDebugUnitTest :app:assembleDebug`；完整构建条件与跨端核验命令见其 [README](MoyleSteg-Android/README.md)。

公开源码来自已核验的发布包，保留许可与公开合成夹具，排除私人诊断目录、构建缓存和签名私钥。源码构建需要下载依赖；应用文件处理在本机执行。
