# Android 0.4.0-alpha · 多文件候选版验证

日期：2026-09-07。只使用合成内容、文件名和公开测试凭据。
运行在 Windows 主机，JDK21、Gradle8.13、Robolectric4.16；项目、构建、SDK、缓存与临时数据位于 H 盘。

| 实际检查 | 结果 |
|---|---|
| app 主机测试 | 163 项通过，0 失败、错误或跳过 |
| 多文件 ViewModel 流程 | 17 项，包含等待选择、部分保存、同名、空文件、重试、取消、权限与过时导出回复、预检、PNG和SAES创建 |
| Kotlin core:check | 通过；保留旧协议测试，增加 ZIP、受限堆和跨端容器回归 |
| ZIP 受限堆 | 64 MiB 成员在 32 MiB JVM 堆中创建、检查并恢复 |
| APK 与测试 APK | 构建通过；versionCode 8；与上一版同一调试签名 |
| lint | 0 错误，8 条警告；类别见机器汇总 |
| 原有加密核心 | 13 个生产文件与 0.3.2 源码包逐字节相同；新增独立 ZIP 模块 |
| 普通 APK | 不含合成测试资源或测试密钥 assets |

新增测试已计入 app 总数，不能重复相加。逐测试类计数、APK 字节与 SHA-256 见[机器汇总](0.4.0-alpha/validation.json)。

Python/Kotlin 的受管 ZIP 双向逐项核对名称、大小与 SHA-256；PNG、GIF、SAES 各覆盖口令/密钥两种方式。
逐容器结果见[双向合成记录](0.4.0-alpha/cross-end-envelope-summary.json)；独立源码包内旧版参考解码器的恢复结果见[参考版本记录](0.4.0-alpha/reference-envelope-verification.json)。
旧版参考实现可恢复完整标准 ZIP，新版在外层认证后显示成员。没有更改加密容器 v1。

每个成员独立提交；失败或取消后已保存项保留，未保存项可重试。完整 ZIP 导出与认证时的摘要绑定，保存位置回复也绑定到发起时的结果。
普通 ZIP 仍作为一个文件保存，长注释中恰巧包含标记或普通文本以标记结尾不会触发自动拆包。

## 范围与限制

Robolectric 使用合成 ContentProvider/MediaStore，实际产品保存代码、文件写入、回读与提交均被执行；不是手机系统服务的实测。
保留的 1 GiB Download 用例实际分块复制和回读一个稀疏合成源，但不是手机多文件加解密或性能测量。
旧 API FileProvider 的主机测试包含 Windows/Android 路径差异适配；该适配不进入 APK。

本轮 adb 未发现已连接手机或模拟器。未执行 iQOO 13、真实权限弹窗、系统打开方式、Compose 设备渲染或设备 instrumentation。
这是供用户验收的调试签名 APK，不是商店签名发行；[设备验收清单](../docs/DEVICE_ACCEPTANCE.md)保留待执行项目。

## 重跑

```text
./gradlew :core:check :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
python tools/package_source.py
```

Windows 使用 gradlew.bat。公开源包采用明确白名单和逐文件 SHA-256 清单；私人诊断路径、构建缓存与签名私钥不进入发布包。
