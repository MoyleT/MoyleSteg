# Moyle 1.4.0：恢复预算与清晰的任务结果

本版改进恢复资源管理、结果状态和桌面可读性，保留现有三主题与 16px 加载效果。AES-GCM、密钥派生、PNG／SAES／STEGKEY 的 v1 格式不变；`png_steg_aes256.py` 本轮仅同步 CLI 版本号。新增恢复容器预算位于桌面服务层，不宣称为原 CLI 增加了同名参数。

Version 1.4.0 improves recovery resource management, result context and desktop readability. It retains the three themes, compact progress visuals and existing v1 formats. The cryptographic engine changes only its CLI version string; the new container budget belongs to the desktop service API.

## 恢复预算 / Recovery budgets

恢复超限提示明确区分处理预算与文件损坏，并提醒：**请勿缩放、裁剪或重新保存原隐写图片**。确认设备资源充足后，可以在提取、解密或验证页面展开高级恢复设置。

| 预算 | 默认值 | 桌面允许的最高值 | 限制对象 |
|---|---:|---:|---|
| 像素 / Pixels | 25,000,000 | 100,000,000 | 图片展开后的处理规模 |
| 载荷 / Payload | 256 MiB | 1024 MiB | 恢复文件大小与受限解码 |
| 容器 / Container | 512 MiB | 4096 MiB | 整个恢复输入的字节数，包括 PNG 附加数据 |

选择输入后，大小和临时卷空间在后台探测；高级面板展示输入大小，只读验证／查看信息还展示私有副本所需的临时空间与可用空间。开始恢复任务时，工作线程重新探测，并先在界面显示结果再继续处理。界面预算数值仅保留在当前窗口表单，退出后不保存。任一值高于默认值时，本次任务需要勾选资源确认；变更输入、预算或结束任务会清除该确认，避免沿用此前的授权。

The panel probes input size and temporary-space information in the background. At recovery start, the worker probes again and displays the result before continuing. GUI limits are explicit ceilings, not hardware capability guarantees. Recovery settings are not persisted. Increasing any default requires acknowledgement for the current run. A resource-limit message does not establish corruption; preserve the original PNG and change the budget only after checking device resources.

## 容器副本与磁盘 / Container capture and temporary disk

完整容器大小与像素／载荷大小分开限制：一张小图片可能带有大量附加数据。服务在真正创建验证副本前再次检查容器预算、可提前读取的图片／SAES 头部限制和临时磁盘可用空间，不依赖界面此前显示的数值。临时空间要求为**输入容器大小 + 16 MiB 安全余量**；副本放在系统临时目录，不修改输入原件。显示可用空间并不代表已经为任务预留空间。

认证、原文摘要和完整容器摘要继续使用同一份私有捕获数据，不会退回按原路径分别认证与哈希。完整容器摘要包含附加数据；原文摘要对应经过认证的解密内容。成功、失败和协作式取消都会清理临时副本；复制过程中发生空间不足也有专用提示。

The service rechecks container bytes, early header limits and free temporary disk space immediately before capture, independently of the earlier UI preview. Verification requires the input size plus a 16 MiB reserve; displaying available space does not reserve it for the task. It authenticates and hashes the same captured encrypted bytes, and cleans up the temporary copy on success, failure or cooperative cancellation. Payload and complete-container checksums retain different meanings.

可用磁盘空间可能在检查后被其他程序占用，安全余量不能预留或锁定空间。内存需求仍是估算，图片解码与载荷处理仍可能同时持有多份缓冲区。分块捕获不是操作系统级原子快照；验证成功仅描述本次捕获的数据，不保证外部文件在返回后保持不变，也不提供数据库或虚拟机镜像的快照保证。

Disk availability can change after inspection; the reserve does not allocate or lock that space. Memory estimates do not guarantee peak usage, and this release does not add streaming encryption. Capture is not an OS-level atomic snapshot, nor a guarantee that another process will leave the original unchanged afterward.

## 完成摘要与输入状态 / Results and selected input

服务结果增加 `input_path` 与带时区的 `completed_at`，对应任务启动时捕获的请求；进度回调或之后的表单修改不会重写结果来源。界面默认展示任务、对应输入、完成时间、状态和输出位置；有输出时提供打开目录。大小、算法、摘要等位于可展开的技术详情，原始文件 SHA-256 与完整容器 SHA-256 保留各自的复制按钮。

更换对应输入或切换加密／解密模式时，旧结果清除，摘要复制失效；新的恢复输入显示尚未验证。验证成功明确标为本次捕获数据已验证，不把旧输入的成功结果当作当前输入的状态。

The default completion summary identifies the task, input, completion time, status and output location. Technical details are expandable. Changing the associated input or encryption/decryption mode clears the old result and its copy actions; the new recovery input is unverified. Result context comes from the captured request, not later form contents.

## 可读性与窗口适配 / Readability and window fit

侧栏提供标准／大字号。大字号对所有显式 QSS 字号增加 2px：正文 13→15px、字段标签 11→13px；字体增大不机械放大内边距，进度条保持 16px。输入框边界使用独立 `input_border`，键盘焦点使用 `focus`，装饰 `border` 和原有正文颜色保持不变。

| 主题 | 输入边界颜色 | 对页面背景 | 对卡片背景 | 对输入背景 |
|---|---|---:|---:|---:|
| 深邃蓝紫 | `#65749E` | 4.087:1 | 3.635:1 | 3.883:1 |
| 樱桃奶霜 | `#AC718B` | 3.559:1 | 3.741:1 | 3.693:1 |
| 墨黑荧绿 | `#597D68` | 4.205:1 | 3.736:1 | 4.042:1 |

这些比值根据当前颜色的相对亮度计算，并以 Qt 实际控件渲染回归检查边界与焦点。它们用于控制本轮输入边缘的可见性，不代表完整桌面无障碍认证。设计参考 [W3C 非文本对比度说明](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)，其中识别控件所需的视觉信息与邻接颜色使用 3:1 基准；装饰分隔线不需要一并提亮。

窗口使用可用工作区的 Qt 逻辑坐标，并考虑窗口边框；窄空间下两列变为纵向堆叠，侧栏独立滚动。标准尺寸下保留熟悉布局，主题切换仍共用同一套结构。依据 [Qt 高 DPI 文档](https://doc.qt.io/qt-6/highdpi.html) 与 [QScreen.availableGeometry](https://doc.qt.io/qt-6/qscreen.html#availableGeometry-prop)，布局不将逻辑尺寸再次乘以设备像素比。

Large text increases explicit font sizes by 2px while retaining compact progress geometry. Input boundaries and focus use separate tokens without brightening all separators. Window fitting uses the available logical screen area and native frame margins; narrow forms stack and the sidebar scrolls. Functional image/extract icons remain stable across themes; face-free fruit stays in branding and empty-state decoration.

## 隐藏流程与口令 / Hide workflow and passwords

隐藏页把“检查实际容量”放到文件选择之后、凭据之前，鼓励先确认能否装下，再输入口令。预检仍使用实际压缩结果，没有把估计写成精确进度。原有策略保留：所有任务结束后清理各页口令，包括不需要口令的容量预检。

Capacity checking now appears after file selection and before credentials. It still measures the compressed data. All jobs continue to clear password fields, including password-free preflight; the new order reduces unnecessary re-entry without keeping secrets longer.

## 本版验证状态 / Validation status

最终 1.4.0 使用合成文件完成以下独立运行，统计均来自布局修复后的实际日志：

| 运行 | 平台与范围 | 实际结果 |
|---|---|---|
| 项目完整测试入口 `full` | 完整源码测试，Qt offscreen | **541 项通过，460.80 秒** |
| 最新源码 `main.py --self-test` | Windows 原生 Qt | **55 项自检通过** |
| 重新编译的 `MoyleSteg.exe --self-test` | Windows 原生 Qt，`frozen=true` | **55 项自检通过** |

回归覆盖复制前预算拒绝、后续临时空间不足与清理、恢复错误文案、输入上下文与旧结果失效、字号／控件对比度、窄屏几何及历史格式兼容。结果出现后曾暴露卡片高度不足；最终版本修正了内部布局高度计算，并增加真实父容器边界检查，防止只检查视口可达而遗漏祖先裁切。760×480 逻辑窗口的大字号指南也已回归。

完整日志在本地记录为 `tests-release.log`；两份原生自检报告分别为 `source-release/report.json` 和 `exe-release/report.json`。原始报告与截图不随公开项目包发布。不同运行的数量不相加，旧版结果不作为本版证据；原生 Qt 自检不等于完整桌面无障碍认证。

The final full-source run passed 541 tests in 460.80 seconds on Qt offscreen. Final source and freshly compiled frozen-EXE self-tests each passed 55 checks on native Windows Qt using synthetic data. Coverage includes ancestor containment after result display and the 760×480 large-text guide following the layout-height correction. Counts from independent runs are not combined. These checks are not a complete accessibility certification. Archive integrity and extracted-runtime execution are separate release checks; neither is claimed by this table. Public packaging policy is documented in [RELEASE.md](RELEASE.md).

历史主题、素材与 1.3.1 弹窗修复记录保留在 [APPEARANCE_1.3.0.md](APPEARANCE_1.3.0.md)。本说明使用合成示例，不包含真实文件路径、用户文件名、密钥或私人诊断数据。
