# Moyle 1.4.1：恢复读取边界与原生交互验证

1.4.1 修复提取／解密容器预算的时序缺口，并修复窄窗口中很长的文件名或摘要撑宽结果卡的问题。三主题、细进度条、中英切换、文件／密钥格式、默认预算与高级恢复确认规则保持兼容。

Version 1.4.1 binds restoration container budgets to the opened input and fixes long-word overflow in narrow result cards. Existing themes, compact progress effects, language switching, v1 formats, default budgets and advanced-recovery confirmation rules remain compatible.

## 容器预算 / Container budget

此前，服务在凭据解析前检查路径大小，提取和解密随后按该路径重新打开输入。另一写入者在这段窗口追加 PNG 尾部或替换为较大的合法 SAES 时，可以通过旧检查。静止输入不触发这一问题；这不是 AES-GCM 认证绕过。

现在，核心 PNG／SAES 解码器接收可选 `max_container_bytes`。桌面服务在自动原名恢复与手动输出两条路径均传入当前预算，核心对最终打开的句柄执行 `fstat`。读取包装器在读取前后检查完整大小，并按预算剩余字节数限制读取请求；PNG 像素展开前后也检查。提取和解密无需因此复制整个容器。超限仍返回 `container_resource_limit`，无效值返回 `container_budget_invalid`，保留双语恢复提示。

The service retains an early pathname check for prompt feedback and passes its budget through both restoration modes. Core decoders inspect the actual opened handle, bound PNG/SAES read requests, and check size around reads and PNG raster conversion. Authentication still precedes plaintext publication. The new optional keyword also reaches core peek and restore helpers. Omitting it retains previous direct-core/CLI container-budget behavior; payload and pixel limits continue to apply. No new CLI flag or new encrypted format is introduced.

这项保护约束实际读取的容器及读操作，不提供操作系统级快照，也不保证外部程序在读取结束后不会修改原文件。只读验证仍使用一份私有加密副本关联认证结果与完整容器摘要；没有退回按路径分别认证与哈希。像素预算、载荷预算、容器预算与临时空间检查各自独立。整个加密系统仍是全量载荷处理，并非流式加密。

## 长路径与键盘 / Long paths and keyboard

Qt 的自动换行标签仍可能把一个很长的单词当作布局最小宽度；只约束控件宽度也可能裁掉实际文字。结果摘要和技术详情现使用只读、无独立滚动条的纯文本控件，按单词边界或必要时在词内换行，并按文档高度参与布局。完整文本保持可选择，不插入隐藏换行标记，也不将文件名解释为 HTML。两个 SHA-256 复制按钮仍独立。

Read-only text documents wrap at word boundaries or inside an otherwise oversized token, with height-for-width layout and no internal scrolling. Tests measure every rendered line and continuous character coverage, not only widget rectangles. Full plain text remains selectable without HTML interpretation or added wrap markers. Synthetic interaction tests exercise Tab/Shift+Tab, keyboard expansion/collapse, automatic focus scrolling, accessible names and label buddies, Chinese/English, standard/large text, long paths and both digest actions. Testing Qt accessibility interfaces is not a screen-reader certification.

## 验证记录 / Validation record

修复前，20 项新建服务边界测试中 4 项失败、16 项通过：PNG／SAES 的手动输出与原名恢复均能复现预算绕过；只读验证、查看信息及提高预算的对照组按预期工作。修复后新增 38 项完整容器回归通过，覆盖实际打开对象、凭据后替换、解码读取期间增长、精确边界和无效值；与邻近资源、验证一致性、核心进度、原名恢复测试合计 211 项通过（40.03 秒）。两组计数不相加。

最终 1.4.1 在 Windows x64 / Python 3.13.7 / PySide6 6.11.2 上完成以下运行，均使用合成数据：

| 运行 | 实際范围 | 结果 |
| --- | --- | --- |
| `scripts/run_tests.py full` | 完整源码套件，Qt offscreen | **615 项通过，365.31 秒** |
| `tests/test_keyboard_accessibility.py` | **20 项 Windows 原生**键盘／可访问接口／文本布局，另 **3 项离屏缩放模拟** | **23 项通过，8.75 秒** |
| `main.py --self-test` | Windows 原生 Qt，源码运行环境 | **55 项自检通过** |
| 新构建 `MoyleSteg.exe --self-test` | Windows 原生 Qt，`frozen=true` | **55 项自检通过** |
| 1.4.0 ↔ 1.4.1 独立进程兼容实验 | 两方向 × PNG／SAES × 口令／密钥 | **8 组通过**；新核心默认接口及精确容器预算额外覆盖，共 12 次恢复均逐字节一致 |

The final full-source run passed 615 tests in 365.31 seconds on Qt offscreen. Native interaction validation passed 20 Windows cases, with three additional isolated offscreen `QT_SCALE_FACTOR` simulations at 1.25, 1.5 and 2.0. Those simulations do not change OS display settings or certify physical multi-monitor scaling. Source and rebuilt frozen-EXE native self-tests each passed 55 checks. Eight independent-process compatibility groups between 1.4.0 and 1.4.1 passed in both directions, including optional exact-size budgets in the new decoder. Separate runs and subcases are not summed into a fictitious total.

长路径补测既检查控件祖先边界，也检查每个文档块的行宽与字符覆盖。八个中英／字号／摘要或详情组合的实际标签截图均确认完整；选中文本的 MIME 内容与原文逐字相同，实验未写系统剪贴板。

早前两次原生专项运行虽断言通过，但首窗显示记录过可恢复的 Windows COM `0x8001010d` 诊断；最终 23 项运行和最小空 Qt 窗口对照未再出现。原始日志保留，根因未确认，不把未复现当作操作系统问题已修复。

以上为维护方本轮实际执行结果，不是第三方独立审计或正式密码学审计。公开截图是演示，不能代替这些运行证据。原始本机日志留在未公开的 `artifacts/` 中。ZIP 清单核验和解压后运行属于单独发布检查，不由源码／EXE 自检计数自动推出。

## 公开截图 / Public screenshots

以下图像是 1.4.1 原生 Qt 控件渲染，带明确的“合成界面演示 / Synthetic UI demo”标记。完成卡使用固定展示夹具，不能作为真实认证成功的证据。画面仅含 `C:/MoyleDemo/` 下的虚构路径，口令和密钥输入为空，不包含个人诊断报告。

- [深邃蓝紫 / Midnight](screenshots/theme-midnight.png)
- [樱桃奶霜 / Blossom](screenshots/theme-blossom.png)
- [墨黑荧绿 / Terminal](screenshots/theme-terminal.png)
- [完成摘要 / Completion summary](screenshots/completion-summary.png)
- [窄窗口大字号 / Compact large text](screenshots/compact-large.png)

窄窗口截图为 900×550 逻辑像素，保留真实纵向滚动；侧栏较低的设置可通过侧栏滚动访问。三主题和完成摘要为 1220×820 逻辑像素。截图尺寸会随设备像素比变化；截图不是对所有物理显示器缩放配置的证明。

可运行 `python scripts/capture_public_ui.py` 重新生成；存在同名图像时使用 `--force`。脚本隔离偏好、检查可见演示路径、仅渲染当前窗口并移除 PNG 文本元数据，不进行桌面截屏。发布白名单只包含这五个命名图像，放在源码文档中，不向运行库额外复制。原始本机诊断日志、自动测试临时文件及整机信息仍排除在公开包外。

历史 1.4.0 功能、边界与维护方测试记录见 [RECOVERY_1.4.0.md](RECOVERY_1.4.0.md)；公开包规则见 [RELEASE.md](RELEASE.md)。
