# Android 0.3.2-alpha · 自动保存与打开验证记录

日期：2026-09-07。仅使用合成载荷、文件名和测试凭据。
运行环境：Windows 主机，JDK 21、Gradle 8.13、Robolectric 4.16；工程、构建、SDK、缓存和临时数据位于 H 盘。

## 本轮实际运行

| 检查 | 结果 |
|---|---|
| app 主机单元／Robolectric 测试 | 146 项通过，0 失败／错误／跳过 |
| 新 Download 导出测试 | 19 项，包含 SDK 29／35 的 pending 发布、SDK 28 兼容路径、同名保护、写入／回读失败、取消、空文件、1 GiB 输出 |
| 新文件类型与打开方式测试 | 16 项，包含 4 KiB 上限、文档／媒体类型、未知类型、只读授权、系统 chooser 和没有查看应用的处理 |
| 新恢复流程集成测试 | 11 项，包含 PNG／GIF／SAES 自动保存、错误凭据不发布、失败不重解而直接重试、权限拒绝／过期回调、清空结果保留公共文件 |
| Kotlin core:check | 通过；包含现有 PNG／GIF／SAES、捕获、扩容、像素入口和受限堆回归 |
| 主 APK 与 instrumentation APK | 构建通过；主 APK 0.3.2-alpha，versionCode 7 |
| Android lint | 0 错误，8 条警告；种类见机器汇总 |
| APK 签名与包内容 | 签名验证通过，与 0.3.1-alpha 相同；普通 APK 不含合成测试凭据／图片 assets |

三个新增测试类已经包含在 app 总数中，不应重复相加。
完整统计、各测试类计数、APK SHA-256 与字节大小见 [机器汇总](0.3.2-alpha/validation.json)。

## 数据与测试边界

- 1 GiB 检查使用实际长度为 1,073,741,824 字节的稀疏合成源文件，实际分块写出完整文件并独立回读 SHA-256。
  这是主机上的 Download 导出层测试；不代表本轮在手机上执行了 1 GiB 解密、性能或空间压力实验。
- Robolectric 中的 MediaStore 服务由合成 ContentProvider 提供；真实导出代码、文件字节、文件描述符、发布顺序、长度和摘要校验均被执行。
  它不能替代 iQOO 13 的系统媒体服务。
- Windows 的规范路径使用反斜杠，AndroidX FileProvider 的 Android 路径判定使用斜杠。
  旧 API 主机用例仅适配该私有路径归属谓词，并按 Manifest 初始化真实 Provider，清理测试之间的静态路径缓存。
  URI 解析、实际读取、所有写模式拒绝以及 Download 之外的兄弟目录拒绝均仍有断言。
  此适配属于测试环境，未进入 APK，也不是旧 Android 真机验收。
- 初始两项恢复集成测试在旧实现下失败于缺少保存 URI；新增辅助类的 33 项初始测试也确认红灯。
  后续修复测试环境的公共目录映射、分隔符和 FileProvider 缓存后，最终全套通过。
- 与已交付的 0.3.1-alpha 源码包逐字节比对，13 个加密核心生产文件保持相同。
  原有主机互通用例随核心与 app 回归运行；本轮没有另外执行 Windows EXE 或新一轮独立 Python 反向互通矩阵。

## 重跑

```text
./gradlew :core:check :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
python tools/package_source.py
```

Windows 使用 `gradlew.bat`。源码包使用明确白名单，排除本机诊断目录、缓存、构建目录、签名私钥与本机配置。
包内清单逐项记录公开文件的大小和 SHA-256，外部 SHA256SUMS-0.3.2.txt 对应 APK 与源码 ZIP。

## 尚未执行

本轮未连接手机或模拟器；未执行真实权限弹窗、系统打开方式选择器、其他应用读取、Compose 设备渲染或设备 instrumentation。
新版使用同一调试签名，供在上一版上更新验收；这不是正式商店签名发行。
旧 Android 写入时部分文件可能可见、应用被系统结束时没有续跑保证，详见 [恢复保存说明](../docs/DOWNLOAD_RESTORE_0_3_2.md) 与 [设备验收清单](../docs/DEVICE_ACCEPTANCE.md)。
