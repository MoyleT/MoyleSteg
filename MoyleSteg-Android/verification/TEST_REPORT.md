# 历史基线：0.1.0-alpha 原提交方验证结果（2026-09-06）

本文件保留原始提交方的环境与验证边界。0.1.1-alpha 的实际结果见 [TEST_REPORT_0_1_1.md](TEST_REPORT_0_1_1.md)。

## 已实际执行

| 项目 | 结果 |
|---|---|
| Kotlin/JVM 核心源码编译，JVM target 17 | 通过 |
| 核心回归 | 72 项通过 |
| Python 1.4.1 → Kotlin 恢复 | 16 个容器通过，包含在 72 项内 |
| Kotlin → 原样 Python 1.4.1 恢复 | 16 个容器通过，单独记录 |
| 透明 Alpha、RGB 最大变化、Pillow 读取输出 | 通过 |
| PNG 五种过滤器、RGB/tRNS | 通过 |
| XML 格式、Python 工具语法 | 通过 |
| 桌面参考源码与原 ZIP 的逐字节一致性 | 通过 |

环境为 Linux、OpenJDK 21.0.11、Kotlin CLI 1.9.0、系统 BC 1.80，Python 用于夹具
生成和反向恢复。生产 Gradle 目标 Kotlin 2.2.21、BC 1.85.2 **尚未在这里解析或运行**。
没有把旧版本 BC 二进制装入工程或 Android APK。

`core-tests-final.log` 是最终 JVM 测试日志；`kotlin-to-python-final.json` 是反向恢复记录。
`summary.json` 记录范围；`reference.json` 记录桌面参考源码 SHA-256。

## 未执行／未完成

- Android SDK 不存在。初始化构建时访问 Gradle 官方下载地址出现 DNS 失败：
  `<urlopen error [Errno -3] Temporary failure in name resolution>`。
- 因此未生成 APK，未执行 Android App 模块编译、Compose 渲染或真机安装。
- `DeviceInteropTest` 和 `UiSmokeTest` 已编写，未运行；不计入上述测试数。
- 未做正式安全审计、模糊测试、极限内存基准或外部文档提供方故障测试。

## 结论边界

证据支持：这份 Kotlin 协议核心在本次 JVM 环境中，与参考桌面核心完成了所列合成数据
的双向互通。证据不支持：任意 Android 设备均兼容、UI 已无布局问题、所有输入图像
均可解码、指定目标依赖已经构建成功、软件已通过安全审计。

首版是可以继续验证和完善的源码交付，不是可直接安装的正式手机版。
