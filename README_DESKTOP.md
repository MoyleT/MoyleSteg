# Moyle 隐写工坊 / Steganography Studio

Windows 桌面版 1.6.0 支持一张图片隐写多个文件：多选、实际容量预检、认证后查看清单、保存全部或部分文件，保存失败可直接重试。支持可播放 GIF 动画载体，并保留深邃蓝紫、草莓樱桃粉色与黑客绿色三种主题、受控恢复预算、完成摘要、大字号与小屏适配。保留 v1 PNG / `.saes` / `.stegkey` 格式兼容性；只读验证的认证与两项 SHA-256 仍基于同一份捕获数据。

Version 1.6.0 adds native multi-file selection, actual ZIP capacity preflight and authenticated member lists. Save selected or all pending files with non-overwriting names and retry without decrypting again. Single-file containers retain their existing behavior. [Multi-file details and limits / 多文件说明与限制](docs/MULTIFILE_1.6.0.md).

GIF 可直接作为载体，输出保留动画，支持 Android 0.2.0-alpha 双向恢复。GIF 密文放在标准应用扩展块，不使用像素 LSB；动画不重编码，GIF 不做像素扩容。请按文件传输，避免聊天软件重新处理时删除扩展。完整协议、资源限制与实际验证范围见 [GIF 版本说明](docs/GIF_1.5.0.md)。

The inherited retry flow retains passwords when an operation fails. Animated GIF carriers remain interoperable with Android 0.2.0-alpha and later. An application extension contains the existing encrypted SAES payload; original animation blocks are preserved without re-encoding. GIF does not use pixel LSBs or pixel resizing. File analysis can identify the extension, and re-encoding may remove it. Existing PNG/SAES formats, themes and safety checks remain.

## 直接运行 / Run the portable app

在完整项目包中打开 `dist/MoyleSteg/MoyleSteg.exe`，或双击项目根目录的 `启动桌面版.bat`；在独立便携目录中直接打开 `MoyleSteg.exe`。便携版已包含 Python 与运行依赖，无需另外安装。移动或分发时请保留整个 `MoyleSteg` 文件夹，包括 `_internal` 和其中的 `base_library.zip`。

Open `dist/MoyleSteg/MoyleSteg.exe`. Python is included. Keep the entire `MoyleSteg` directory together, including `_internal`; the EXE alone is not a complete distribution.

窗口右上角可切换 **中文 / English**，立即更新界面且保留表单内容。软件仅记住语言、主题、字号和动态效果偏好，不保存口令、秘密文件历史或恢复预算。全部文件处理在本机执行。

Switch **中文 / English** in the top-right corner. Form values remain intact. Only language, theme, text size and motion preferences are remembered; passwords, private file history and recovery budgets are not stored. All file processing is local.

## 外观 / Appearance

在窗口右上角的外观选择器中即时切换主题，无需重启。首次启动默认使用深邃蓝紫主题；之后恢复上次选择。

| 主题 / Theme | 色调 / Palette |
|---|---|
| 星夜·深邃蓝紫 / Midnight·Dark | 深蓝紫背景、柔和圆角与星点交互，适合夜间使用。 / Deep navy-violet surfaces, soft corners and star accents for night use. |
| 樱桃奶霜·浅粉 / Blossom·Light | 草莓樱桃插画、奶霜粉底色、圆润控件与爱心交互。 / Strawberries and cherries, cream-pink surfaces, rounded controls and heart accents. |
| 终端·墨黑荧绿 / Terminal·Green | 墨黑绿色背景、利落方形控件与终端提示符交互。 / Near-black green-tinted surfaces, angular controls and terminal-chevron accents. |

切换主题会同时改变按钮、输入控件、导航装饰及悬停反馈，页面布局和字段位置保持一致。语言和主题切换会保留当前页面、表单与正在进行的任务。在侧栏底部勾选“减少动效”可关闭页面切换与悬停动画；真实任务进度和取消功能照常工作。

Change the appearance instantly without restarting. Midnight is the initial default; later launches restore your choice. Themes change button and field styling, navigation decoration and hover feedback while keeping the same page layout and field positions. Theme and language changes preserve the current page, form values and active task. Enable **Reduce motion** to disable page transitions and hover animations; measured progress and cancellation remain available.

侧栏提供“标准 / 大字号”：大字号将正文从 13px 提高到 15px，字段标签从 11px 提高到 13px，其余显式字号增加 2px；进度条仍为 16px。输入框边界与键盘焦点使用独立颜色，装饰分隔线保持柔和。三种主题的隐藏／提取导航均保留图片与提取图标，水果用于品牌和空态装饰。窗口按屏幕可用逻辑工作区调整初始大小；较窄时表单两列改为上下排列，侧栏可滚动。

Choose **Standard / Large text** in the sidebar. Large text changes body text from 13px to 15px, field labels from 11px to 13px, and other explicit font sizes by 2px; progress stays 16px high. Input boundaries and keyboard focus have separate colors, while decorative separators stay subtle. Task icons remain recognizable across themes, with fruit retained as decoration. Initial window sizing uses the available logical screen area; narrow forms stack their columns, and the sidebar can scroll.

加载视觉也会随主题切换：粉色是果汁液面与少量气泡，绿色是数据流，蓝紫色是一颗位于真实进度前端的星核和整段渐隐拖尾；未知总量时单颗流星掠过等待轨道。填充比例对应当前阶段的真实进度，不以动画代替百分比。“减少动效”使装饰静止，真实进度照常更新，布局保持不变。粉色主题的无表情 Q 版草莓、樱桃透明贴纸在开发时由内置 ImageGen 生成并编辑，随包提供；运行软件无需联网获取图片。

Loading visuals follow the selected theme: juice and a few bubbles for Blossom, a data stream for Terminal, and one star at the leading edge of measured progress with a fading trail for Midnight. Without a measurable total, a single star sweeps across the indeterminate track. Reduce motion keeps the decoration static while measured values update, without changing the layout. Blossom's bundled transparent, face-free strawberry and cherry stickers were generated and edited with the built-in ImageGen tool during development; no runtime image download is needed.

将本地文件拖入输入框会引用它的现有路径，不移动源文件。有效文件悬停时会高亮提示。

Dropping a local file into an input references its existing path without moving the source. The field highlights when a valid file is dragged over it.

1.3 系列主题参考了 GitHub 上 [Impeccable](https://github.com/pbakaus/impeccable) 的层次、留白、色彩和动态设计方法，以及 [Anthropic frontend-design](https://github.com/anthropics/skills/tree/main/skills/frontend-design) 的设计指导。应用仍为原生 Qt 桌面程序；这些参考未成为运行依赖。历史外观与素材来源见 [docs/APPEARANCE_1.3.0.md](docs/APPEARANCE_1.3.0.md)，本版变化见 [1.6.0 多文件说明](docs/MULTIFILE_1.6.0.md)，合成截图见下方图库。

## 功能 / Workflows

| 页面 / Page | 用途 / Purpose |
|---|---|
| 隐藏文件 / Hide a file | 选择载体和秘密文件，先检查实际容量，再设置凭据。GIF 输出保持动画的 .gif；其他载体输出 PNG。GIF 预检显示帧数与成品体积，PNG 可按预算扩容。 / Choose a cover and secret, check capacity, then set credentials. GIF stays animated; other images produce PNG. GIF preflight reports frames and output bytes; PNG can resize within its budget. |
| 提取文件 / Extract a file | 选择保存文件夹，认证后自动按原文件名及后缀恢复；也可查看元数据或自定义文件名。 / Choose a folder and recover the original name and extension after verification. Metadata inspection and custom filenames are also available. |
| 文件加解密 / File encryption | 使用独立 `.saes` 容器加密；解密默认恢复原文件名和格式。 / Encrypt standalone `.saes` containers; decryption restores the original name and format by default. |
| 验证文件 / Verify a file | 自动识别 PNG、GIF 或 SAES，基于同一份临时容器副本认证内容并显示原始文件与完整输入容器的两份 SHA-256，不输出解密文件。 / Detect PNG, GIF or SAES, authenticate one temporary container copy and show separate SHA-256 values for its original payload and complete container, without writing a decrypted file. |
| 密钥工具 / Key tools | 创建随机 256-bit `.stegkey` 文件。 / Create a random 256-bit `.stegkey` file. |
| 使用指南 / User guide | 查看离线操作说明。 / Read the offline guide. |

验证先按块读取输入，在系统临时目录建立私有容器副本；认证、原始文件 SHA-256 和完整输入容器 SHA-256 均基于本次捕获的数据。原始文件摘要对应解密后的内容，完整输入摘要对应整个 PNG、GIF 或 SAES（含该格式允许的附加数据），不能混用。副本保留输入的加密容器数据，不输出解密文件；复制前检查容器大小与系统临时卷可用空间，要求容器大小加 16 MiB 安全余量。副本在任务成功、失败或取消后清理。源文件仍可能被其他程序修改；分块读取不是操作系统原子快照，验证结果也不保证之后的源文件保持不变。

Verification reads the input in bounded chunks into a private copy in the system temporary directory. Authentication and both checksums use this captured data. The original-file checksum identifies decrypted content; the container checksum covers the entire PNG, GIF or SAES, including additional data permitted by that format. Before copying, the service checks the container budget and temporary-volume free space, requiring the container size plus a 16 MiB reserve. The copy contains encrypted container bytes, is cleaned up after success, failure or cancellation, and does not write a decrypted file. Chunked reading is not an atomic operating-system snapshot; verification does not guarantee the source stays unchanged afterward.

任务在后台运行，进度显示当前阶段、该阶段可用的真实计数/百分比及用时；切换阶段时百分比可重置，没有细分计数的计算显示等待状态，而非总任务百分比。点击“取消操作”会在安全检查点停止，当前不可中断计算可能需要等待。运行中关闭窗口会请求安全取消，待工作线程结束后再关闭；已完成提交的结果仍按成功报告。运行中禁止重复提交。完成后可查看验证信息、复制 SHA-256，并在有输出时打开其目录。

Operations run in the background. Progress shows the current stage, its available measured counts/percentage, and elapsed time. Percentages may reset between stages; computations without finer counters show a waiting state, not an overall completion percentage. Cancel operation stops at a safe checkpoint, so an indivisible computation may need to finish first. Closing a busy window requests safe cancellation and closes after its worker finishes; already committed results are reported as successful. Duplicate submissions are blocked. Results include verification details, checksum copy actions and, when applicable, an output-folder shortcut.

完成摘要优先显示任务、对应输入、完成时间、状态与输出位置；有输出时可打开目录。展开“技术详情”查看大小、算法和摘要，原始文件 SHA-256 与完整容器 SHA-256 分别复制。更换对应输入或切换加密／解密模式后，旧结果立即清除；当前恢复输入会显示尚未验证。成功验证的状态描述的是本次捕获数据。

The completion summary shows the task, input path, completion time, status and output location first. Expand technical details for sizes, algorithms and separate payload/container checksum copy actions. Changing the associated input or encryption/decryption mode clears the old result; a newly selected recovery input is marked unverified. Successful verification describes the captured data for that run. Long tokens wrap within the available width while the complete plain text remains selectable.

输出默认不覆盖已有文件。即便允许覆盖，输入文件、载体与所选密钥路径也始终受保护。加密口令需输入两次；解密只需一次。选路径失败、容量不足、任务失败和取消后保留当前口令，便于修改参数后重试；容量预检不清空口令。成功的认证操作只清理本次使用页面的口令，实际关闭窗口时清理所有页面。口令仅留在当前表单，不写入设置或日志，重新启动后需重新输入。

Existing files are preserved by default. Even with overwrite enabled, inputs, covers and the selected key path remain protected. Encryption requires matching passwords; decryption requires one entry. Failed paths, insufficient capacity, failures and cancellation preserve current password fields for retry; preflight leaves them intact. Successful authenticated operations clear only their own page, and closing the window clears all pages. Passwords stay in live form controls without settings or log persistence; restarting requires re-entry.

提取或解密时默认勾选“按原文件名和格式恢复”。例如原文件为 `报告.pdf`，恢复后仍为 `报告.pdf`，并校验内容一致。文件名来自经过认证的加密元数据，无需猜测文件格式，也不会统一改为 `.bin`。默认保存到输入旁独立的恢复文件夹。取消此选项可选择完整文件名；两种模式会分别保留手选位置。认证失败不会新建恢复目录或写入明文。

Extraction and decryption default to **Restore original filename and format**. A file named `report.pdf` returns as `report.pdf`, with content integrity verified. The name comes from authenticated metadata rather than format guessing; files are not renamed to `.bin`. A separate folder beside the input is suggested. Uncheck this option to choose a custom filename; each mode remembers its destination independently. Authentication failure creates no recovery directory or plaintext.

## 图片与凭据 / Images and credentials

PNG 隐写图片需保留像素原样；截图、裁剪、缩放、转换 JPEG 或平台重压缩可能导致认证失败。GIF 则需保留应用扩展块，不能仅靠画面相同判断隐藏数据是否还在。建议作为原始文件传输。随机布局不代表无法检测。丢失正确口令或密钥后没有恢复后门。

Preserve the PNG's original pixels. Screenshots, cropping, resizing, JPEG conversion or platform recompression can break authentication. GIF requires its application extension to remain intact; matching pictures alone do not establish that the hidden data remains. Transfer the original file. Random placement does not guarantee undetectability. There is no recovery backdoor for lost credentials.

桌面和服务默认预算为 **25,000,000 像素**、**256 MiB 文件载荷**和 **512 MiB 完整恢复容器**。小像素 PNG 也可能带大量附加数据，三个限制不能互相替代。超过恢复预算不代表文件损坏：请勿缩放、裁剪或重新保存原隐写图片。提取、解密与验证页可展开高级恢复设置，查看输入大小；验证／查看信息还显示临时空间需求及可用空间。

Desktop/service defaults are **25,000,000 pixels**, **256 MiB of file payload**, and **512 MiB for a complete recovery container**. A small PNG can contain substantial appended data, so these budgets are separate. A budget error does not establish corruption: do not resize, crop or re-save the original steganographic image. Extraction, decryption and verification offer advanced recovery settings; verification/information checks also show temporary-space requirements and free space.

选择输入后，大小与临时空间在后台探测，不阻塞界面；开始恢复任务时，工作线程重新探测并先在界面显示结果。只读验证／查看信息真正复制容器前，服务层还会再次检查预算和可用空间。显示的磁盘状态只是检查当时的可用量，不代表空间已经预留。

After input selection, file size and temporary-space information are probed in the background. At recovery start, the worker probes again and displays the result before continuing. Immediately before verification/information capture, the service rechecks budgets and free space. Displayed availability is a point-in-time observation, not reserved disk space.

提取／解密还在核心打开输入后检查完整容器预算，并限制读取请求；两种输出模式均适用，不额外复制整个容器。直接调用核心解码／恢复／头部检查函数可传 `max_container_bytes`；省略时维持旧核心／CLI 的容器预算行为，仍受像素与载荷限制。这不是文件系统快照。

Extraction/decryption additionally enforce the service budget on the actual opened handle and bound read requests in both output modes, without another complete temporary copy. Core decoding/restoration/peek APIs accept optional `max_container_bytes`; omitting it preserves previous direct-core/CLI behavior while pixel/payload limits remain. This is not a filesystem snapshot.

桌面可调上限为 **100,000,000 像素 / 1024 MiB 载荷 / 4096 MiB 容器**，属于界面允许值，不代表设备一定能够处理。预算只留在当前窗口的表单，不保存到偏好；超过默认值须勾选设备资源确认，变更输入、数值或结束任务会清除确认。建议先检查容量、再设置口令；预检和失败重试不会清空已填口令。内存提示和可用磁盘空间都是估算或当时状态；其他程序可能继续占用资源，实际写入空间不足仍会报错并清理临时副本。本版仍为内存处理，并未新增流式加密。

GUI ceilings are **100,000,000 pixels / 1024 MiB payload / 4096 MiB container**, not promises that every device can process them. Values remain in the current window only. Exceeding defaults requires resource acknowledgement, which clears when the input or limits change or a task finishes. Checking capacity before entering credentials remains convenient; preflight and failed retries preserve filled password fields. Memory figures are estimates and disk availability can change after inspection; a later out-of-space error is still reported and the temporary copy is cleaned up. This release does not add streaming encryption.

## 从源码运行 / Run from source

需要 Python 3.10+。本次构建环境是 Windows x64 / Python 3.13。

```powershell
.\Setup-Desktop.ps1
.\.venv\Scripts\python.exe main.py
```

也可自行创建虚拟环境后安装 `requirements-gui.txt`。纯核心测试依赖为 `requirements-dev.txt`（不含 Qt），完整桌面测试为 `requirements-test.txt`，打包为 `requirements-build.txt`；`requirements-lock.txt` 记录此次构建的实际版本。原 CLI 入口 `png_steg_aes256.py` 保留。

Use `requirements-gui.txt` for the app, Qt-free `requirements-dev.txt` for core tests, `requirements-test.txt` for the full desktop suite, and `requirements-build.txt` for packaging. `requirements-lock.txt` records the verified build environment. The original `png_steg_aes256.py` CLI is retained.

## 测试与打包 / Test and build

本版实现与验证范围见 [docs/MULTIFILE_1.6.0.md](docs/MULTIFILE_1.6.0.md)，此前版本文档保留历史结果。测试使用合成文件；完整源码测试、Windows 原生交互及源码／EXE 自检分别记录，不相加冒充单次测试数量。Qt 可访问名称检查不代表完成屏幕阅读器或所有物理显示器缩放认证。公开工件规则见 [docs/RELEASE.md](docs/RELEASE.md)。

See `docs/MULTIFILE_1.6.0.md` for current behavior and verification scope and `docs/GIF_1.5.0.md` for the GIF protocol. Full-source, native Windows interaction and source/EXE self-tests are separate runs using synthetic data. Qt accessibility-name checks do not certify a screen reader or every physical monitor configuration. Earlier versioned reports remain historical records.

双击 `运行测试.bat` 执行完整测试；命令行可选 `运行测试.bat core --no-pause` 或 `运行测试.bat full --no-pause`。入口只使用项目 `.venv`，缺失时创建它，并在其中安装所选模式的依赖，不向全局 Python 安装。测试失败的退出码会原样保留，暂停不会把失败变成成功。

Double-click `运行测试.bat` for the full suite, or choose `core` / `full` with optional `--no-pause`. The entry creates and uses the project's `.venv` and installs matching dependencies there, never globally. Test exit codes are preserved across the optional pause.

```powershell
# --install creates .venv if needed and installs matching local dependencies.
py scripts\run_tests.py core --install
py scripts\run_tests.py full --install
# Once installed, omit --install; pytest arguments follow --.
.\.venv\Scripts\python.exe scripts\run_tests.py core -- tests/test_png_steg_aes256.py -q
# Optional native rendering; the full entry defaults to offscreen.
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe scripts\run_tests.py full -- tests/test_theme.py -q
.\Build-Desktop.ps1
```

`core` 明确排除 GUI 测试，仅验证核心、服务与无 Qt 的工具；通过不代表桌面完整验证。完整模式明确加载 pytest-qt，并与实际程序一样使用 Fusion。缺少 GUI 依赖时，选择 GUI 或完整测试会明确失败并提示安装 `requirements-test.txt`，不会静默跳过后报告完整通过。

`core` explicitly excludes GUI tests and covers the engine, service and Qt-free tooling; passing it is not full desktop validation. Full mode explicitly loads pytest-qt and uses the application's Fusion style. Selecting GUI/full tests without GUI dependencies fails with setup guidance instead of silently reporting a complete pass.

已有只安装 `requirements-dev.txt` 的环境可直接原位运行单个核心模块，无需 Qt 或 pytest-qt。若当前环境还安装了其他 pytest 插件，可禁用自动加载以确认隔离；`--core` 在收集前排除 GUI 模块。测试入口脚本自动完成此隔离。

An environment with only `requirements-dev.txt` can run individual core modules directly in place, without Qt or pytest-qt. Disable plugin autoload when an environment also contains unrelated plugins; `--core` excludes GUI modules before collection. The supported runner applies this isolation automatically.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest tests/test_png_steg_aes256.py tests/test_core_safety.py -q
python -m pytest --core -q
```

测试使用合成文件，隔离在项目 `artifacts/test-runs/` 中。构建工具仅生成项目内的 `build/` 与 `dist/`。

Tests use synthetic files in isolated `artifacts/test-runs/` directories. The build writes to the project's `build/` and `dist/` directories.

便携包的内置自检 / Opt-in packaged runtime check:

```powershell
$app = Start-Process -FilePath '.\dist\MoyleSteg\MoyleSteg.exe' -ArgumentList '--self-test', '"C:\your-test-folder\report.json"' -WindowStyle Hidden -PassThru -Wait
$app.ExitCode
```

请将示例路径换成自己的测试目录。自检用临时合成文件验证 PNG/SAES 往返、错误口令拒绝、通过实际按钮检查容量、只读验证、取消与按原文件名恢复，以及中英按钮与展开菜单的渲染，随后写出 JSON 报告和界面截图。它不会读取你的秘密文件。正常双击运行不会执行自检。

Replace the example path with your own test directory. The check uses temporary synthetic data to verify roundtrips, wrong-password rejection, actual capacity/readonly verification/cancel actions, original-name restoration through actual buttons, and bilingual button/dropdown rendering. It writes a JSON report and UI screenshots without reading private input files. It runs only when explicitly requested with `--self-test`.

## 公开项目包 / Public project archive

完成当前版本的干净构建与合成数据验证后，运行：

```powershell
.\.venv\Scripts\python.exe scripts\package_project.py --output releases\MoyleSteg-1.6.0-Full-Project.zip
```

打包脚本只纳入明确白名单中的源码、测试、资源、许可与公开说明，并保留当前便携运行目录，包括 `_internal/base_library.zip`。本地 `artifacts/`、私人数据、Git/虚拟环境/构建缓存、旧发布 ZIP 和本机调查报告不属于公开包。仅三份指定的历史格式合成测试夹具可位于 `tests/fixtures/`；真实 `.saes` 或 `.stegkey` 不随包发布。

The packager includes allowlisted source, tests, assets, licenses and public documentation plus the current portable runtime. It excludes local reports, private data, development caches and old releases. The named legacy test fixtures contain synthetic data only. Nothing is uploaded.

`SHA256SUMS.txt` 是首次导入 v1.0 文件的历史校验清单，不代表当前源码未变化。原始基线保存在维护者 Git 提交 `1e3026a73822e65d236e2f2b158713262f8705b1` 中；每个公开 ZIP 的 `RELEASE_MANIFEST.json` 记录本次实际文件大小与 SHA-256。当前变更与验证边界见 [docs/MULTIFILE_1.6.0.md](docs/MULTIFILE_1.6.0.md)，五张合成展示图见 [docs/RELIABILITY_1.4.1.md](docs/RELIABILITY_1.4.1.md)；其余版本化文档保留历史结果。依赖许可见 `THIRD_PARTY_NOTICES.md` 和便携包 `_internal/third_party_licenses/`。
