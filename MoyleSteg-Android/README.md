# MoyleSteg Android · 0.3.1-alpha

**Kotlin + Jetpack Compose 的 Android 首版源码工程。** 不使用 Python 运行时，不依赖服务器。
PNG／SAES 保持与电脑版 1.4.1 兼容；GIF 动画载体需要电脑版 1.5.0 或后续兼容版本。

> 本版增加 **JPG／JPEG 照片作载体、输出 PNG**：支持照片方向校正、实际容量预检和自动扩容。
> 保留最多 1 GiB 的独立 SAES 文件处理、自动／手动内存预算、GIF 和三主题。
> 应用源码已经通过 Android 编译；最新构建、回归和设备验证边界见
> [本版验证记录](verification/TEST_REPORT_0_3_1.md)。历史版本记录保留为基线。

## 已编写的能力

| 部分 | 当前状态 |
|---|---|
| AES-256-GCM SAES 加密／解密 | Kotlin 核心已实现、JVM 测试通过 |
| scrypt + HKDF-SHA256 | 保持桌面 v1 参数；流式 SAES 使用 BC lightweight GCM，图片字节接口保留 JCA |
| 大文件与内存设置 | SAES 文件接口最多 1 GiB；图片按本次堆和系统可用内存评估，支持有界手动预算 |
| 密钥文件导入、生成与导出 | 兼容 `.stegkey`；密钥不嵌入 PNG |
| 全图分块密钥布局、RGB 1-LSB | 精确移植，包括 Python randbelow 的位宽规则 |
| PNG 隐藏与恢复 | 支持下述严格的 PNG 子集；透明像素 RGB 不丢失 |
| JPG／JPEG 照片载体 | 创建时用 Android 解码器处理主图并应用 EXIF 方向，输出现有 v1 PNG；不输出 JPEG 隐写容器 |
| GIF 动画载体 | 保留动画原始块，标准应用扩展封装 SAES；支持预检、恢复与只读验证 |
| 容量预检、只读验证、双摘要 | 已实现；摘要与认证使用同一捕获的字节序列 |
| 隐藏时自动扩容 | 界面默认开启；实际压缩后规划尺寸，预算内放大后再嵌入 |
| Android 系统文件选择／导出 | 已接入 SAF；设备提供方仍需实机验收 |
| Compose 手机界面与三主题 | Android 编译通过；未进行实机渲染验收 |
| 协作式取消、进度、私有成品 | 已接入；不承诺系统杀进程后自动恢复 |

### 当前范围与资源限制

- **独立 SAES：原始文件最多 1 GiB（1,073,741,824 字节）**，容器最多 1 GiB + 1 MiB。
  使用 64 KiB 缓冲、私有磁盘暂存与完整认证，不把整个载荷装进数组。保留 v1 格式，桌面恢复也须使用足够的载荷预算。
- **PNG／GIF：原文件最多 32 MiB，完整容器最多 128 MiB，最多 100,000,000 像素**，仍受实际内存预算约束。
  这些是应用显式上限，不是所有手机都能达到的容量承诺；巨图仍可能受控拒绝。原有核心字节 API 默认值保持 4 MiB／12M／64 MiB。
- 工作内存默认自动评估应用堆上限、已用堆与系统可用内存；高级设置允许在当时安全范围内手动选择，最高 512 MiB。
  预算不代表已分配或预留 RAM，不能突破 Android 应用堆。口令任务至少 64 MiB 工作预算，密钥任务至少 32 MiB。
  PNG 单行缓冲上限仍为 4 MiB。详见 [大文件与内存说明](docs/LARGE_FILES_0_3_0.md)。
- 输入捕获后重新打开并逐块核对；发现内容变化会拒绝。不能重新打开的提供方需先保存本机副本。
  这不是操作系统快照；认证和完整容器摘要仍始终对应同一份捕获字节。
- PNG 限于 **非交错、8-bit RGB（类型 2）或 RGBA（类型 6）**，支持过滤器 0–4。
  类型 2 的 tRNS 透明色已处理。支持桌面 1.4.1 标准输出的 RGBA PNG。
- 上述 PNG 入口明确拒绝调色板、灰度、16-bit、Adam7 交错、APNG。JPG／JPEG 仅在创建时转换，
  先检查编码大小、图片尺寸与 Bitmap／RGBA 工作内存，再解码；成品不复制 EXIF／GPS 元数据。
  手机平台支持的普通、渐进式、灰度 JPEG 均可作为照片载体；详见 [JPG 载体说明](docs/JPEG_CARRIER_0_3_1.md)。没有 HEIC 载体转换、
  批量、多图分片、纠错、后台续跑、生物识别保险库。
- 自动扩容仍受上述预算限制。容量足够时保持原尺寸，不足时按比例放大，目标占用不超过 90%。
  扩容不增加画质，不改动原载体，也不作用于恢复或验证。详见 [扩容说明](docs/AUTO_EXPAND_0_1_2.md)。
- GIF 不进行像素扩容，以完整成品字节预算计容量；最多 500 帧、画布像素 × 帧数最多 1 亿。
  动画字节保留，密文位于可识别的标准扩展块，重编码可能删除它；按文件发送。
  AES-GCM 认证隐藏文件，不认证外层动画；完整容器摘要另行标识整个 GIF。详见 [GIF 协议](docs/GIF_PROTOCOL.md)。
- 不要为了让已有隐写图片变成“支持的格式”而缩放、截屏或重存；可能破坏载荷。
- 不是完整 PNG 通用库。自有的受限 PNG 编解码代码也需要模糊测试与真机评估。
- 加密不是不可检测性保证；固定引导头、像素统计和文件大小仍可暴露隐写存在。

## 工程组织

```text
app/                     Android Manifest、SAF、ViewModel、Compose 页面、三主题
core/                    独立 Kotlin/JVM 协议、加密、PNG／GIF 和布局实现
core/src/test/           已运行的回归程序与公开合成夹具
app/src/androidTest/     真机协议测试和 UI 冒烟测试（本次未运行）
tools/reference/         桌面 1.4.1 与 1.5.0 Python 参考核心、GIF 封装器，不进入 APK
tools/generate_vectors.py    生成合成互通夹具
tools/png_vectors.py         生成独立 PNG 过滤器夹具
tools/verify_python.py       Python 反向恢复 Kotlin 生成的文件
tools/verify_autoexpand_python.py  验证 Kotlin 扩容 PNG 的桌面恢复
tools/verify_gif_python.py   验证 Kotlin GIF 桌面恢复及逐帧动画一致性
tools/test_core_local.py     无 Android SDK 的 JVM 测试入口
tools/build_android.py       校验下载的 Gradle 并生成官方 Wrapper／构建
verification/            实际测试日志、环境和构建失败记录
docs/                    设计、格式说明、安全边界与待验证项
```

`core` 的生产代码没有 Android 依赖，方便在 JVM 与设备上运行同样的协议测试。
`.stegkey` 测试文件使用公开确定性测试密钥，**绝对不要拿来加密私人数据**。
测试资源只进入 JVM 测试与 instrumentation APK，不放入正常应用的 assets。

## 在 Windows 构建

开发环境：JDK 17 或更新版本、Android Studio、Android SDK 36、Build Tools 35.0.0，
以及首次拉取依赖所需的网络。辅助脚本需要 Python 3.10+；**这是开发辅助依赖，不是 APK 运行依赖**。

在 Android Studio 的 SDK Manager 安装 SDK。为命令行配置 `JAVA_HOME` 与 `ANDROID_HOME`，
或在本机 `local.properties` 写入 `sdk.dir=...`。不要把这个本机文件提交到工程。

在工程根目录执行：

```powershell
py -3 .\tools\build_android.py --wrapper-only
```

脚本从 Gradle 官方地址下载固定的 8.13，核对内置 SHA-256，然后在隔离的小工程里
生成真正的 `gradlew`、`gradlew.bat`、`gradle-wrapper.jar`。本版已经生成并附带官方 Wrapper，
完整源码包可直接使用，以上命令仅在需要重新生成时运行。

随后用 Android Studio 打开根目录同步，也可执行：

```powershell
py -3 .\tools\build_android.py
```

默认执行 `:core:check :app:testDebugUnitTest :app:assembleDebug`。**仅在成功后**，调试 APK 才应位于：

```text
app/build/outputs/apk/debug/app-debug.apk
```

这是调试包，不是商店签名发布包。本工程没有附带生产签名密钥。
构建网络不能访问 Google/Maven 时应解决网络配置，不要盲目降级密码库或跳过校验。

构建版本被固定为 AGP 8.13.2、Gradle 8.13、Kotlin/Compose Compiler 2.2.21、
Compose BOM 2025.11.01、Activity 1.11.0、Lifecycle 2.9.4、BC 1.85.2。
这是固定的构建组合，不声称每个组件都是最新版本。

### 指定全部构建目录

Windows 可使用 `Build-Android.ps1 -JavaHome <JDK目录> -AndroidSdk <SDK目录> -RuntimeRoot <构建缓存目录>`。
缓存、临时文件和 Android 用户文件重定向到指定目录；环境设置只作用于本次进程，结束后恢复。
直接 Python 构建入口默认使用项目下 `.android-build`，可用 `--runtime-root` 指定位置；不自动使用用户目录中的 SDK。
请把项目、SDK 和 RuntimeRoot 放到希望使用的磁盘。SDK/JDK、缓存和签名密钥不进入源码包。

## 核心测试与互通

联网的完整开发环境：

```powershell
.\gradlew.bat :core:check
py -3 -m pip install Pillow cryptography
py -3 .\tools\verify_python.py .\core\build\interop-output
py -3 .\tools\verify_autoexpand_python.py .\core\build\autoexpand-output
py -3 .\tools\verify_gif_python.py .\core\build\gif-output
```

只验证 JVM 核心也可使用命令行 Kotlin 编译器和自己取得的 BC jar：

```powershell
py -3 .\tools\test_core_local.py --bc-jar "H:\dev\bcprov-jdk15to18-1.85.2.jar"
py -3 .\tools\verify_python.py .\core\build\interop-output
py -3 .\tools\verify_gif_python.py .\core\build\gif-output
```

生成夹具是可选开发操作；包中已经附带夹具。重新生成会创建新的随机 salt/nonce，
因此容器字节及其 SHA 会变化，属于正常现象。

连接设备后运行（本次没有执行）：

```powershell
.\gradlew.bat :app:connectedDebugAndroidTest
```

### 0.3.1-alpha 本轮验证

JPG 载体、方向与资源检查、实际 ViewModel 流程、双向合成互通及构建记录见
[0.3.1 验证报告](verification/TEST_REPORT_0_3_1.md)。Android 实机验收与主机测试分开记录。

### 0.3.0-alpha 历史验证

完整的主机测试、受限 JVM 大文件测试与实际设备边界见 [0.3.0 验证报告](verification/TEST_REPORT_0_3_0.md)。
主机上的流式处理成功不等于已在 iQOO 13 上完成相同大小的文件测试。

### 0.2.0-alpha 历史结果

- 完整 Gradle 构建通过，主 APK 与设备测试 APK 均已生成。
- 核心回归分别为 **72 项基础、26 项捕获、24 项扩容、43 项 GIF**，全部通过；另有 5 个 PNG 独立 JVM 场景和 3 个指纹向量通过。
- **31 项 Robolectric 主机测试通过**，其中 4 项为新增 GIF 流程测试；0 失败、0 错误、0 跳过。
- GIF 的口令／密钥 **双向共 4 组跨端恢复通过**；本轮 Kotlin 输出的原动画字节及 Pillow 逐帧 RGBA、时序、处置方式和循环次数一致。
- 原有 PNG／SAES 双向各 16 组、扩容 PNG 的桌面恢复 2 组继续通过。
- APK v2 签名、版本及正常 APK 不含测试凭据／夹具检查通过；Lint 0 错误、6 条警告。
- **未执行 Android 手机／模拟器安装、真实 Compose 渲染、系统文件选择器或设备测试。**

准确的测试范围、APK 摘要与复跑命令见 [0.2.0 验证报告](verification/TEST_REPORT_0_2_0.md)。

### 0.1.2-alpha 历史结果

- 新增 **24 项自动扩容核心回归、7 项 Android 流程回归通过**；全套 Android 主机测试为 27 项。
- 原有 72 项核心、26 项输入捕获、5 个 PNG 独立进程与指纹向量均通过。
- 原有双向互通矩阵保持通过，另外 **2 组扩容 PNG（口令/密钥）由桌面 Python 1.4.1 正确恢复**。
- 全新 256 MiB JVM 分别完成 256 KiB、1 MiB 随机载荷扩容及恢复；64 MiB JVM 安全拒绝超出当前堆的扩容。
- 主调试 APK、设备测试 APK 构建成功，APK v2 签名检查通过；Lint 0 错误、6 条建议。
- **未执行手机/模拟器安装、实际 Compose 渲染或设备测试。**

完整记录及测试堆大小说明见 [0.1.2 验证报告](verification/TEST_REPORT_0_1_2.md)。

### 0.1.1-alpha 历史结果

- Kotlin/JVM 生产核心编译成功。
- **72 项 JVM 回归通过**，其中包含 **16 个 Python→Kotlin 容器恢复案例**。
- **16 个 Kotlin→Python 容器恢复案例通过**；同时用 Pillow 对生成 PNG 的 Alpha
  和 RGB 最大修改幅度进行核对。
- 覆盖空文件、不可压缩数据、压缩数据、中文/Emoji 文件名、两类凭据、错误口令、
  错误密钥、篡改、截断、长度预算、scrypt 参数、布局已知值、PNG 五种过滤器等。
- 新增 **26 项输入捕获回归**，PNG 内存/滤波器/编码 5 个独立进程，以及跨端指纹固定向量通过。
- **20 项 Android 服务与状态测试通过**（Robolectric：11 项文档提供方、9 项异步选择）。
- Windows、JBR/OpenJDK 21.0.8、Kotlin 2.2.21、BC 1.85.2；目标 Gradle 8.13 / AGP 8.13.2 构建通过。
- 主调试 APK、设备测试 APK 均已构建；主 APK 签名验证通过。Lint 为 0 错误、6 条非阻断建议。
- 未执行真机/模拟器安装、实际 Compose 渲染或 connectedDebugAndroidTest；Robolectric 不等于真机验收。

详见 [0.1.1 验证记录](verification/TEST_REPORT_0_1_1.md)。

## 操作流程

隐藏：选择支持的 JPG／PNG／GIF 和秘密文件 → 检查实际容量、动画帧数或 PNG 扩容尺寸 → 输入口令或选择密钥 → 处理 →
私有文件保存后重新认证 → 系统选择器创建新文档 → 导出并回读核对完整字节摘要。

恢复：选择 PNG、GIF 或 SAES → 凭据 → 认证成功后生成私有明文成品 → 明确另存为新文档。

验证：对同一次捕获的容器完成认证、原文摘要与容器摘要；不向共享存储写出明文。

密钥：独立生成 → 先导出并备份 → 在隐藏或恢复中选择。未实现“生成后直接保存到
设备密钥保险库”；不应在原文件仍只有一份时依赖这个 alpha 版本。

## 隐私与导出边界

没有 INTERNET、全盘访问权限或统计上传。云端文档提供方由系统处理，主动选择云文件
仍可能触发提供方联网，不能把“应用本地计算”理解为“整个系统绝不联网”。

口令不写 SharedPreferences 或 SavedState；任务开始、后台切换等时清空表单值。
JVM String、GC、系统换页无法给出物理内存安全擦除保证。

私有输出使用 `noBackupFilesDir`，备份被禁用。任务失败或清空结果时清理；进程崩溃后
残留在下次进程启动时删除。删除不是 SSD 物理安全擦除。

SAF 提供方不保证原子替换。首版只向新建的空文档导出，拒绝已知输入 URI 和非空目标，
写后回读校验。失败会尽力删除部分输出；提供方不允许删除时明确提示。选择器本身创建
的空文档也可能保留。不能对不可信提供方作绝对的路径别名或快照保证。

系统会在设备资源紧张时终止进程。没有前台服务或后台续跑保证，建议保持前台。
取消是协作式；scrypt 和单次 AES 调用不保证立即打断。屏幕默认启用 FLAG_SECURE。

这是可继续开发、可审阅和可验证的首个源代码增量，不是已完成安全审计的正式手机版。
