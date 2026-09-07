# Android 0.3.1-alpha · JPG 载体验证记录

日期：2026-09-07。全部图片、载荷与测试凭据均为合成数据。
运行环境为 Windows 主机、JDK 21、Android SDK 36、Gradle 8.13、Robolectric 4.16 / SDK 35 native graphics。
工程、缓存、测试临时目录和交付文件在 H 盘，JDK 在 D 盘。

## 本轮实际运行

| 检查 | 结果 |
|---|---|
| Android app 主机单元／Robolectric 测试 | 100 项通过，0 失败／错误／跳过 |
| 新 JPEG 辅助类测试 | 上述 100 项中包含 23 项：八方向的像素位置、普通／渐进式 JPEG、预算、取消、截断、尾部辅助数据等 |
| 新 JPEG ViewModel 流程测试 | 上述 100 项中包含 6 项：口令／密钥、实际预检与扩容、关闭扩容、签名识别、改名为 JPG 的透明 PNG 恢复 |
| 新 JPEG 双向互通测试 | 上述 100 项中另有 1 项矩阵测试，读取 22 个 Windows PNG、生成 22 个 Android 代码 PNG；反向 Python 再逐个认证通过 |
| Kotlin core:check | 通过；包含原有 72 项核心、26 项捕获、24 项扩容、43 项 GIF、30 项流式 SAES 及受限堆检查；新增 14 项解码像素入口检查 |
| Windows Qt JPEG 流程 | 14 项通过，覆盖真实 Qt 窗口／工作线程／服务、文件选择器和 11 种 JPEG；使用 offscreen 平台 |
| 原有 Kotlin→Python 互通 | 16 组 PNG／SAES、2 组扩容 PNG、2 组 GIF 均通过 |
| Debug APK 与 instrumentation APK | 均构建成功；主 APK 包名 com.moyle.steg.android，versionCode 6 |
| Android lint | 0 错误，8 警告：依赖有更新 3、可用磁盘空间提示 3、KTX 建议 2 |
| APK 签名、版本、ZIP 完整性 | 通过；与 0.3.0-alpha 使用同一签名；正常 APK 不含合成测试图片／测试密钥 assets |

**这些计数属于不同的测试程序，不能相加当作一种统一的单元测试数量。**
44 组 JPEG 互通覆盖普通、渐进式、灰度和八种 EXIF 方向，每种分别使用口令、密钥。
Windows→Android 由当前 Windows 1.5.1 Python 核心生成；Android→Windows 的图片通过 Android JPEG 解码辅助类和现有 Kotlin 隐写核心生成。

首轮新增 ViewModel 测试曾得到 6 项中 5 项失败，原因是旧流程把 JPEG 当 PNG 解码；
另一项改名 `.jpg` 的真实 PNG 恢复控制组通过。补齐 JPEG 入口后全部通过。
打包前另行修正成功编码后的像素数组驻留：提前释放已擦除的 JPEG RGBA 和原载体引用，再进行保存回读验证。
修正后重新执行全部 100 项 app 主机测试、APK／测试 APK 构建、lint 与 22 组 Python 反向认证，均通过。

## 重跑入口

```text
./gradlew :core:check
./gradlew :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
python tools/verify_jpeg_python.py --output jpeg-python.json
python tools/verify_python.py
python tools/verify_autoexpand_python.py
python tools/verify_gif_python.py
```

Windows 使用 `gradlew.bat`。Python 验证工具需要 Pillow 与 cryptography；JPEG 工具在完整桌面工程中默认使用相邻的当前核心，
独立 Android 源码包会使用包内 1.5.0 参考核心。需要重建 Windows 合成夹具时使用 `tools/generate_jpeg_vectors.py`。
`tests/test_jpeg_carrier_ui.py` 位于桌面工程，需要 PySide6、pytest-qt 和该工程的测试依赖。

公开的 [验证汇总](0.3.1-alpha/validation.json) 和 [逐文件反向认证结果](0.3.1-alpha/jpeg-python.json)
只保留合成标识和相对工程位置；本机日志／报告 XML 不随公开源码包发布。

## 未执行与边界

- 未连接或操作 iQOO 13，未在手机或模拟器上执行本版 instrumentation 测试。
  主机 native graphics 测试不是手机实际运行；`DeviceJpegCarrierTest` 已编译，供设备验收使用。
- 本轮没有重打或运行 Windows EXE；Windows 1.5.1 已有 JPEG 载体路径，本轮测试其当前源码 GUI 流程。
- 未独立操作微信或 QQ。用户提供的微信二次保存 0×0／QQ 原图正常的对照已记录于
  [JPG 载体说明](../docs/JPEG_CARRIER_0_3_1.md)，不作为维护方复测结果，也不作传输完整性保证。
- 本轮没有再跑 1 GiB 大文件性能实验；已有流式 SAES 回归通过，历史受限 JVM 1 GiB 记录仍属于 0.3.0-alpha。
- JPEG 主图由 Android 平台解码器处理；结构和预算检查不构成完整图像格式或密码学审计。
