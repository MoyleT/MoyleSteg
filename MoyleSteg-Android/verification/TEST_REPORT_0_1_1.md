# MoyleSteg Android 0.1.1-alpha 验证记录

日期：2026-09-06。使用合成文件；开发与测试输出均位于 H 盘，Java 运行时从 D 盘读取。未修改下载目录原件、冻结审查样本或桌面产品源码。未改全局 Java/SDK/Windows 环境配置。

## 已实际执行

| 项目 | 结果 |
| --- | --- |
| 固定版本 Android/Compose 构建 | 通过，主调试 APK 与设备测试 APK 均已生成 |
| 核心回归 | 72 项通过，含 16 组 Python→Kotlin PNG/SAES |
| 新增输入捕获回归 | 26 项通过 |
| PNG 内存回归 | wide/normal/budgets/filters/encode 5 个独立 128 MiB JVM 均通过 |
| 密钥指纹 | 3 个桌面固定向量、输入密钥不变与错误长度拒绝通过 |
| Android 文档服务层 | Robolectric SDK 35：11 项通过 |
| Android 异步选择状态 | Robolectric SDK 35：9 项通过 |
| Gradle 产物 Kotlin→Python | 另行 16 组通过，含 PNG Alpha 保留和 RGB 最大变化核对 |
| Lint | 0 错误，6 条建议：3 条依赖新版本、1 条可回收空间 API、2 条 KTX 写法 |
| APK | v2 签名验证通过；minSdk 26、targetSdk 36、versionCode 2 |
| 主 APK 内容 | ZIP 完整；无测试容器、`.stegkey`、Python 源码或签名私钥文件；未申请 INTERNET 权限 |
| Python 工具与源 XML | 语法解析通过 |
| 原生设备/模拟器安装、Compose 渲染、仪器测试运行 | **未执行**；不能以 Robolectric 代替 |

主 APK：15,036,315 字节。SHA-256：

```text
0005ca965152a32c8223107dccdcf70ed56ae2b9ad5f0d658aecb7753358da48
```

环境：Windows x64、JetBrains Runtime/OpenJDK 21.0.8、JVM target 17、Kotlin 2.2.21、BC 1.85.2、Gradle 8.13、AGP 8.13.2、SDK 36、Build Tools 35.0.0、Compose BOM 2025.11.01。JUnit 4.13.2、Robolectric 4.16、coroutines-test 1.10.2 仅用于主机测试。

完整构建通过 `Build-Android.ps1` 执行 `:core:check :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug`，最终为 BUILD SUCCESSFUL，96 个任务中 67 个执行、29 个复用。未降级密码学依赖或关闭检查以获得通过。

## 修复前后证据

- **源文件变化**：原版在读取首个 64 KiB 后被等长改写，仍返回混合版本；回归红灯。修复后，包括恢复修改时间、未知元数据和真实文件描述符的控制组都拒绝变化，稳定输入通过。
- **极宽 PNG**：原版 12,000,000×1 RGBA 在 128 MiB 堆发生 OutOfMemoryError，普通 4000×3000 对照通过。修复后极宽输入在分配前返回资源错误；普通图、全部五种滤波器、RGB/tRNS/RGBA 和编码往返通过。
- **异步选择**：在真实 ViewModel 上使用受控外部提供方，原实现 5 项测试中 4 项失败，分别为等待新输入时启动旧任务、查询倒序覆盖、切页后旧查询回写、旧失败回写。修复后这 5 项通过；另补取消、操作切换、失败后无旧输入回退和凭据模式切换，共 9 项通过。
- **指纹**：桌面规则的固定向量通过；实际 UI 已调用共同核心函数。没有改变 `.stegkey` 或 PNG/SAES 格式。

## 过程中的工具问题与处理

首次测试脚手架有一个 Robolectric API 调用错误，以及测试 ContentProvider 未 attachInfo 导致的空上下文错误；修正测试初始化后执行真实服务路径。它们未当作产品漏洞或成功证据。

Gradle Wrapper 首次网络下载触发默认 10 秒超时；改为 60 秒，并复用先前从官方地址下载、SHA-256 已核验的同版本发行 ZIP。Wrapper 仍核对固定 SHA-256，随后从正式 PS 入口完成完整构建。SDK 工具新旧 XML 提示、调试原生库未剥离符号提示及 Gradle 9 迁移提示不影响本次固定版本构建；未据此声称零警告。

## 复现与验收边界

从工程根目录运行 `Build-Android.ps1`，显式传入 Java、SDK 与 RuntimeRoot；也可使用官方 Wrapper 执行以上任务。独立 JVM 入口与全套回归已接入 `:core:check`；反向恢复用 `tools/verify_python.py core/build/interop-output`。

本版是可靠性修复版。中英文切换、主题专属动效及高级恢复预算界面尚未补齐。真机安装与交互验收见 `docs/DEVICE_ACCEPTANCE.md`，包括字体缩放、旋转、系统文件提供方与实际 Android 加密提供方测试。两遍输入核对不是操作系统快照；内存准入是保守估算，不是资源预留。

原始本机日志与复现脚本保留在工程外的 `artifacts/android-fix-0.1.1/`，源码包只收录合成基线资料与本版公开报告，不收录依赖缓存、调试签名私钥或本机诊断目录。

构建参考：[AGP 8.13 兼容表](https://developer.android.com/build/releases/agp-8-13-0-release-notes)、[Robolectric 配置](https://robolectric.org/getting-started/)、[协程测试调度](https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-test/)。这些文档用于工具配置，实际通过结论来自本轮执行结果。
