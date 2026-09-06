# Android 0.2.0-alpha 实际验证记录

验证日期：2026-09-06。使用合成数据，在 Windows 主机上构建和运行 JVM／Robolectric 测试。
**没有运行 Android 真机、模拟器、Compose 实际渲染或 `connectedDebugAndroidTest`。**
主机测试通过不能替代设备文件提供方、动画显示和真实 Android 密码提供方的验收。

## 构建与测试结果

本轮完整 Gradle 命令：

```powershell
.\gradlew.bat :core:check :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
```

实际结果为 `BUILD SUCCESSFUL in 1m 56s`，98 项任务，37 项执行、61 项保持最新。
使用项目固定的 Gradle 8.13、AGP 8.13.2、Kotlin／Compose Compiler 2.2.21、BC 1.85.2。

| 核验项 | 本轮实际结果 |
|---|---|
| 基础加密、PNG、SAES、布局回归 | 72 项通过，其中包含 16 组 Python → Kotlin 恢复 |
| 输入捕获与一致性回归 | 26 项通过 |
| PNG 自动扩容回归 | 24 项通过 |
| GIF 核心回归 | 43 项通过，其中包含 2 组 Python → Kotlin GIF 恢复 |
| PNG 内存预算与编解码 | 5 个独立 JVM 场景通过 |
| 桌面密钥指纹向量 | 3 个固定向量通过，并检查非法长度与输入不变性 |
| Android Robolectric 主机测试 | 31 项通过；0 失败、0 错误、0 跳过 |
| 主调试 APK 与 instrumentation APK | 均构建成功；设备测试 APK 未执行 |
| Android Lint | 0 错误、6 条警告 |

31 项 Robolectric 分别为：文档提供方 11、异步选择 9、自动扩容流程 7、GIF 流程 4。
GIF 流程包括预检、隐藏后恢复、只读验证及容器类型识别；它们没有实际打开系统 SAF 选择器。
Lint 警告为 3 条依赖新版本提示、1 条磁盘空间 API 建议、2 条 KTX 使用建议。

GIF 回归覆盖：调色板与动画帧结构、LZW 字典增长及非法码、正确的像素数、完整结束码、
合法的无首清除码输入、未知／重复 Moyle 扩展、截断、尾部垃圾、错误凭据、篡改、
精确容器预算边界、像素与帧预算、复制／嵌入阶段取消，以及原始输入不变性。

## 跨端互通与动画保留

对本轮 Gradle 新生成的 `core/build/` 输出执行了以下三个脚本：

```powershell
py -3 .\tools\verify_python.py .\core\build\interop-output
py -3 .\tools\verify_autoexpand_python.py .\core\build\autoexpand-output
py -3 .\tools\verify_gif_python.py .\core\build\gif-output
```

| 方向与格式 | 结果 |
|---|---|
| Python 1.4.1 → Kotlin PNG／SAES | 16 组通过，已计入基础 72 项 |
| Kotlin → Python 1.4.1 PNG／SAES | 16 组通过 |
| Kotlin 自动扩容 PNG → Python 1.4.1 | 口令、密钥各 1 组，共 2 组通过 |
| Python 1.5.0 → Kotlin GIF | 口令、密钥各 1 组，共 2 组通过，已计入 GIF 43 项 |
| Kotlin GIF → Python 1.5.0 | 口令、密钥各 1 组，共 2 组通过 |

GIF 反向验证使用随源码保存的桌面 1.5.0 核心，不依赖工作区之外的桌面项目。
恢复名称与 4,096 字节合成原文逐字节一致。两个 Kotlin GIF 均保留原载体所有动画块，
Pillow 独立解码的 3 帧 RGBA、40／90／120 ms 时长、处置方式以及循环次数 2 均与原载体相同。
这些是文件字节与解码层的验证结果，不代表已在 Android 界面播放验收。

GIF 新功能需要电脑版 **1.5.0 或后续兼容版本**；电脑版 1.4.1 不包含 GIF 扩展支持。
既有 PNG／SAES 格式保持不变。

参考文件在核验时与当前桌面源文件逐字节匹配：

| 参考源码 | SHA-256 |
|---|---|
| `tools/reference/desktop_1_5_0.py` | `3efe5802a38f08c2134938124a44ee19ac39fb1c2525a5fac3bd482b15459c0a` |
| `tools/reference/gif_carrier.py` | `75c9130a9540627af6bcf8dd19e8400cb6a391f6ca9739f9961f6c58a0cfb236` |

旧的 `desktop_1_4_1.py` 仍保留，供原有 PNG／SAES 互通脚本使用。

## APK 核验

- 版本：`0.2.0-alpha`，`versionCode=4`；最低 API 26，目标 API 36。
- 主 APK 大小：**15,052,703 字节**。
- 主 APK SHA-256：`cb0e20b7cb293b01b6365d94a32ef0038df73205dca88d37cfc537d84d9c7a16`。
- `apksigner verify --verbose --print-certs` 通过，APK Signature Scheme v2 有效。
- 使用开发环境调试证书；不是商店发布签名。签名证书摘要与上一版调试证书一致。
- APK 清单没有 `INTERNET` 权限，ZIP 完整性通过。
- 主 APK 中没有测试 GIF／互通资源、`.stegkey`、SAES、Python 参考源码或签名密钥文件；
  另检查公开测试口令及固定测试密钥的编码标记，未发现它们进入主 APK。
- instrumentation APK 大小为 1,542,444 字节；该包仅构建，未安装执行。

这里的摘要对应本次已构建的 APK；重新构建后应重新核验，不能套用本记录。

## 验证边界与后续设备验收

所有恢复案例均使用公开合成载荷与测试凭据。参考源码和测试资源只进入源码包／测试构建，
不能把其中的固定密钥用于真实文件。

GIF 容器上限 64 MiB、最多 500 帧、画布像素乘帧数最多 1 亿；这些是处理预算，
并不保证任意手机有足够资源。完整输入仍被捕获到内存，GIF LZW 校验使用有界字典，
并不意味着整个加密和导出系统已经流式化。

AES-GCM 认证隐藏文件；外层动画不属于这次认证。完整 GIF 摘要标识整份传输文件。
GIF 扩展可识别，也可能被重编码、优化或聊天软件转码移除，必须按原始文件传送。

待验证的真机 SAF、布局、动画及资源场景列在 [设备验收清单](../docs/DEVICE_ACCEPTANCE.md)。
本记录不等于正式密码学审计、无障碍认证或已通过 Android 商店发布审核。
