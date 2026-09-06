# MoyleSteg Android 0.1.2-alpha 验证记录

日期：2026-09-06。本版增加 Android 隐藏页的自动扩容，保留 PNG/SAES 与密钥格式。全部输入为合成数据；项目、测试输出、SDK 与构建缓存位于 H 盘，Java 运行时从 D 盘读取。未修改下载目录原件或桌面产品源码。

## 已实际执行

| 项目 | 结果 |
| --- | --- |
| 自动扩容核心回归 | **24 项通过**，单个 512 MiB JVM |
| 新增 Android 扩容流程 | **7 项通过**，真实 ViewModel、Robolectric SDK 35 和合成文档提供方 |
| 全部 Android 主机测试 | **27 项通过**：扩容 7、文档捕获/导出 11、异步选择 9 |
| 原有核心回归 | **72 项通过**，含 16 组 Python→Kotlin PNG/SAES |
| 输入一致性回归 | **26 项通过** |
| PNG 内存/滤波器/编码 | 5 个独立 128 MiB JVM 场景通过 |
| 密钥指纹 | 3 个桌面固定向量、密钥不变和错误长度检查通过 |
| 原有 Kotlin→Python | **16 组通过**，含 PNG Alpha 与 RGB 变化核对 |
| 扩容 PNG→桌面 Python 1.4.1 | **2 组通过**，分别为口令和密钥；恢复原名、完整字节与 SHA-256 一致 |
| 独立大载荷实验 | 全新 256 MiB JVM 分别处理 256 KiB、1 MiB 随机文件，扩容隐藏及恢复通过 |
| 独立低堆实验 | 64 MiB JVM 处理 1 MiB 随机文件，在扩容前明确拒绝；未发生 OOM |
| Android/Compose 构建 | 主调试 APK、设备测试 APK 构建成功 |
| Lint | 0 错误、6 条非阻断建议 |
| APK 检查 | v2 签名、ZIP 完整性、版本与权限核对通过；无测试容器、测试密钥、Python 源码或签名私钥文件 |
| Python 工具、Android XML | 语法解析通过 |
| 真机/模拟器安装、Compose 渲染、设备测试执行 | **未执行**；Robolectric 不等于真机验收 |

新增自动扩容的 31 项回归覆盖：默认开关、关闭后拒绝、实际压缩后的容量、足够时不扩容（含占用超过 90%）、横竖比例、透明像素、预检与输出尺寸一致、错误载体、像素/行/内存预算、取消、输入不变、结果失效以及无失败成品。

本版自动扩容不改变恢复和只读验证入口：仅在隐藏流程嵌入头部和密文之前重采样，已有容器不会因恢复而被放大。渐变的 16×16 合成载体在核心测试中扩容为 882×882（256 KiB 载荷）和 1763×1763（1 MiB 载荷）；估算 PNG 工作内存分别为 22,879,272 和 88,152,012 字节。这些是指定合成输入的结果，不代表任意手机或任意文件保证成功。

## 构建与产物

环境：Windows x64、JBR/OpenJDK 21.0.8、JVM target 17、Kotlin 2.2.21、BC 1.85.2、Gradle 8.13、AGP 8.13.2、SDK 36、Build Tools 35.0.0、Compose BOM 2025.11.01。测试依赖为 JUnit 4.13.2、Robolectric 4.16、coroutines-test 1.10.2；未新增产品依赖。

通过正式 `Build-Android.ps1` 入口执行：

```text
:core:check :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
BUILD SUCCESSFUL in 1m 7s
97 actionable tasks: 28 executed, 69 up-to-date
```

APK：`MoyleSteg-Android-0.1.2-alpha-debug.apk`，15,052,703 字节；versionCode 3，minSdk 26，targetSdk 36。沿用 0.1.1 的本地调试签名证书；不是商店正式签名包，私钥未进入源码包。未申请 INTERNET 权限。

SHA-256：

```text
4aae3ce3560a5d562fd0f12e5abf7268643fa39a3d6c04caa5deaeb61232a981
```

结构化检查结果见 [autoexpand_0_1_2_results.json](autoexpand_0_1_2_results.json)。

## 失败记录与解释

- 原来关闭扩容的核心行为会拒绝小载体。应用新增开关但尚未把参数传入核心时，7 项新流程测试中 4 项失败；接入同一任务设置后，7 项全部通过。
- 首次完整构建将全部扩容测试放在同一个 256 MiB JVM；前面的 scrypt 和多次图片处理之后，最后的 1 MiB 预检触发“当前可用内存预算”拒绝。没有删掉准入检查、强制 GC 或把拒绝当成扩容成功。包含口令与多次往返的主回归改用与原核心回归一致的 512 MiB 堆，并另外在全新 256 MiB JVM 中逐个验证两种大载荷、在 64 MiB JVM 验证安全拒绝。
- 因此，可用堆准入是保守的瞬时检查，连续任务中尚未回收的垃圾也可能导致拒绝；预算估算不是内存预留。实际 Android 堆、系统负载及运行速度仍需真机测量。
- 构建仍有 SDK XML 版本提示、Gradle 9 迁移提示及 6 条 Lint 建议；未宣称零警告。

## 复现入口与后续验收

`core:autoExpandRegression` 已接入 `:core:check`，独立编译入口 `tools/test_core_local.py` 也会运行它。该任务生成合成扩容 PNG、载荷与测试密钥到 `core/build/autoexpand-output`；它们不进入主 APK。

```powershell
.\gradlew.bat :core:check :app:testDebugUnitTest
py -3 .\tools\verify_python.py .\core\build\interop-output
py -3 .\tools\verify_autoexpand_python.py .\core\build\autoexpand-output
```

原始日志、红灯记录和独立堆实验脚本保留在工程外的 `artifacts/android-autoexpand-0.1.2/`。公开源码包只收录合成资料和本版报告，排除运行缓存、诊断目录和签名私钥。

操作与预算说明见 [AUTO_EXPAND_0_1_2.md](../docs/AUTO_EXPAND_0_1_2.md)。手机安装、三主题渲染、字号、旋转、系统提供方和扩容时取消仍按 [设备验收清单](../docs/DEVICE_ACCEPTANCE.md) 验收；本次没有补充中英文切换、主题动效、JPEG 转换或后台续跑。
