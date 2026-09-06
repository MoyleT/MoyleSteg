# Moyle 1.3 series — Desktop appearance / 桌面外观

## 1.3.1 popup correction / 下拉菜单修复

Version 1.3.1 fixes the dark strips above and below expanded menus. The list view already had an opaque theme surface, but its outer popup window retained an unthemed surface in the top and bottom margins. The popup shell now receives its own explicit theme stylesheet and palette, including a border-free frame to avoid Fusion's light/dark menu edge. Native 8-pixel spacing, list dimensions, selection and keyboard behavior are retained, along with all three themes, the 16-pixel loading effects, face-free fruit stickers and existing page layout. The encrypted formats and processing engine are unchanged apart from the CLI version label.

1.3.1 修复展开菜单上下出现黑边的问题。列表本身已有不透明主题背景，但外层弹窗上下留白仍显示未适配主题的底色。本版为弹窗外壳明确设置主题样式和调色板，并取消 Fusion 的亮暗框线；保留原生 8 像素留白、列表尺寸、选择与键盘操作。三种主题、16 像素细条加载效果、无表情水果贴纸及现有布局保持不变。除 CLI 版本文字外，加密格式与处理核心没有变化。

The diagnosis was checked against the [Qt 6.11 combo-box source](https://github.com/qt/qtbase/blob/6.11/src/widgets/widgets/qcombobox.cpp): the outer popup is a separate frame with style-controlled top and bottom spacing. Explicit popup styling also addresses the interaction between stylesheets and background filling described in the [QWidget background documentation](https://doc.qt.io/qt-6/qwidget.html#autoFillBackground-prop). Earlier diagnostics captured only the list viewport, excluding this outer edge; the corrected regression scope includes the entire popup.

定位时对照了 Qt 6.11 的下拉框源码：外层弹窗是独立框架，上下间距由样式控制。明确设置弹窗样式也处理了 QWidget 文档所述样式表与背景填充的相互影响。之前的诊断截图只覆盖列表 viewport，遗漏了外壳边缘；本次回归范围纳入整个弹窗。

The 1.3.1 native Windows regression run passed 83 tests in 51.93 seconds across theme rendering, diagnostics, theme personality, appearance preferences, layout and window behavior. This includes full-popup edge checks across three themes, two languages and three dropdown controls, plus a fault-injection test confirming that diagnostics reject a dark popup shell. A prior focused run of the 18 theme/language/dropdown combinations also passed; it is not added to the 83-test count. The rebuilt 1.3.1 EXE passed all 47 self-test checks in its actual frozen runtime on native Windows Qt at device-pixel ratio 1.5. Across 24 complete dropdown captures, the minimum theme-color match for the top and bottom popup edges was 100%. The 1.3.0 results below are historical and must not be presented as results for this patch.

1.3.1 的 Windows 原生回归测试 83 项通过，用时 51.93 秒，覆盖主题绘制、诊断、主题交互、外观偏好、布局与窗口行为。其中包括三主题、双语、三类下拉控件的完整弹窗边缘检查，以及确认诊断会拒绝黑色外壳的故障注入测试。此前另一次 18 组主题／语言／下拉控件专项运行也通过，不与 83 项相加。重新构建的 1.3.1 EXE 已在实际打包运行环境中通过 47 项自检，使用 Windows 原生 Qt 平台，设备像素比 1.5；24 次完整下拉弹窗截图的上下边缘主题色匹配率最低为 100%。下方的 1.3.0 结果属于历史记录，不能作为本补丁的验证结果。

## 1.3.0 changes / 主题版变化

Three selectable themes replace the previous fixed green-and-cream appearance. Midnight uses deep navy-violet surfaces, soft corners and star accents and is the initial default. Blossom combines cream-pink surfaces, rounded strawberry and cherry illustrations without faces, rounded controls and heart accents. Terminal uses near-black green-tinted surfaces, angular controls and terminal-chevron accents. Theme changes affect control styling and hover feedback as well as color, while keeping the same page layout and field positions. A shared palette covers fields, buttons, pop-up menus, navigation, results and progress so each theme remains coherent throughout a task.

本版将原来固定的绿色与米白色界面改为三种可切换主题：默认“星夜·深邃蓝紫” Midnight 采用柔和圆角与星点交互；“樱桃奶霜·浅粉” Blossom 使用没有面部表情的 Q 版草莓樱桃插画、奶霜粉底色、圆润控件与爱心交互；“终端·墨黑荧绿” Terminal 使用利落方形控件与终端提示符交互。切换主题同时改变控件样式、导航装饰和悬停反馈，页面布局与字段位置保持一致。输入框、按钮、展开菜单、导航、结果与进度使用同一套主题颜色，避免仅更换背景造成文字不可读。

The navigation and page layout use clearer hierarchy, more deliberate spacing and coordinated icons. Theme and language changes apply immediately without reconstructing forms or interrupting the active job. Only language, theme and motion preferences persist between launches. Passwords and private file history are not stored. Reduce motion disables page transitions and hover animations without changing the task's measured progress or safe cancellation. Blossom uses two bundled transparent fruit stickers generated during development, while Qt draws the remaining decorative shapes locally. The app does not download images or call an image-generation service at runtime.

导航与页面调整了文字层次、间距和图标。切换语言或主题会立即生效，保留当前表单和正在运行的任务。程序只记住语言、主题与动态效果偏好，不记录口令或秘密文件历史。侧栏底部的“减少动效”关闭页面切换与悬停动画，实际进度与安全取消保持可用。粉色主题使用开发时生成、随程序附带的两张透明水果贴纸，其余装饰由 Qt 在本机绘制。软件运行时不下载图片，也不调用图片生成服务。

The themes also have distinct loading visuals: Blossom uses a flowing juice surface and a few decorative bubbles, Terminal uses a data stream, and Midnight uses one small crystalline star with a soft glow at the leading edge of measured progress, with a fading trail spanning the filled area. When no total is available, a single star sweeps across the indeterminate track. The fill level follows the actual reported stage progress, not the animation clock. Stages without a measurable total do not invent a completion percentage. Reduce motion makes all decorative loading effects static while measured values continue to update. Each theme uses the same 16-pixel-high progress area and keeps its position unchanged. Animation stops when the progress widget is hidden or the task finishes.

加载视觉同样区分三种主题：粉色为果汁液面流动和少量气泡，绿色为数据流，蓝紫色为一颗位于真实进度前端、带自然柔光的小晶核，已完成部分形成渐隐拖尾；未知总量时由单颗流星掠过等待轨道。填充比例随真实上报的阶段进度变化，不随动画计时虚构完成度；无法计算总量的阶段不编造百分比。“减少动效”使所有装饰加载效果静止，实际进度数值照常更新。各主题共用高度为 16 像素的进度区域，位置保持一致；控件隐藏或任务结束时停止播放动画。

Empty image previews follow the selected theme with fruit, a moon and orbit, or a miniature terminal. Header and result decorations use matching motifs; results have a brief entrance animation that Reduce motion disables. A valid local file dragged over an input highlights its drop area. Dropping it references the existing path only and never moves the source file.

图片预览空态随主题显示水果、月亮轨道或小终端；页头与结果区也有相应装饰。结果区的短促入场动画可由“减少动效”关闭。将有效本地文件拖到输入框时会高亮接收区域；拖入只引用现有文件路径，不移动源文件。

## Design reference / 设计参考

The design work consulted [Impeccable by Paul Bakaus](https://github.com/pbakaus/impeccable), particularly its [color guidance](https://github.com/pbakaus/impeccable/blob/main/skill/reference/colorize.md), [layout guidance](https://github.com/pbakaus/impeccable/blob/main/skill/reference/layout.md), [motion guidance](https://github.com/pbakaus/impeccable/blob/main/skill/reference/animate.md), and [bolder guidance](https://github.com/pbakaus/impeccable/blob/main/skill/reference/bolder.md), as well as [Anthropic's frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design). The references informed a coherent visual direction and focused details within the requested layout, rather than introducing a web framework. No reference code, assets, hooks or executables are distributed with Moyle, and neither reference adds a runtime dependency.

本版参考 GitHub 上 Impeccable 的色彩、布局、动态与 bolder 指南，以及 Anthropic 的 frontend-design skill，将设计方向与局部细节应用到现有原生 Qt 界面和三种指定色调中，保持用户选择的布局与细条尺寸。公开工程不包含这些参考项目的代码、素材、钩子或可执行程序，也未新增运行依赖。

## Bundled sticker assets / 随包贴纸素材

The built-in ImageGen tool generated two sticker images for this project's Blossom theme and edited them to the user's requested face-free style with transparent alpha. The final PNGs are copied unchanged into the project. They are local UI assets, not examples copied from Impeccable or an external icon library.

开发时使用内置 ImageGen 为本项目粉色主题生成两张贴纸，再按用户要求编辑为没有面部表情、带透明 alpha 的 Q 版水果。最终 PNG 原样复制为以下项目素材。它们是随包的本地 UI 资源，不是从 Impeccable 或外部图标库复制的示例。

| Asset / 素材 | File / 文件 |
|---|---|
| Strawberry / 草莓 | `assets/strawberry-sticker.png` |
| Pair of cherries / 双樱桃 | `assets/cherry-sticker.png` |

Final generation and editing brief / 最终生成与编辑提示：

> face-free cute rounded strawberry / pair of cherries, soft glossy pink/red fruit, mint leaves, cream rim, transparent alpha, no eyes/mouth/blush/expressions/text.

Both exact filenames are allowlisted and required in the source archive and portable runtime. Their bytes and SHA-256 values are covered by the release manifests. No additional image-generation dependency is needed to use the app.

公开打包明确允许并要求这两个精确文件名同时存在于源码与便携运行目录，字节数与 SHA-256 由发布清单记录。使用软件不需要额外安装图片生成依赖。

## Compatibility and retained behavior / 兼容性与保留行为

This appearance release retains the v1 PNG, SAES and key-file formats. The original-name restore flow, input/key path protection, exclusive output creation by default, resource checks, staged progress and cooperative cancellation remain in place. Read-only verification continues to authenticate and hash the same captured encrypted-container data, as described in the historical `VERIFICATION_1.2.2.md` record. The CLI version label changes; the appearance work does not introduce a new container format or encryption algorithm.

本版保留 v1 PNG、SAES 与密钥文件格式，以及原名恢复、输入与密钥路径保护、默认不覆盖提交、资源检查、阶段进度和安全取消。只读验证仍基于同一份捕获容器数据进行认证并生成摘要；相关修复由历史文档 `VERIFICATION_1.2.2.md` 记录。外观更新没有引入新的容器格式或加密算法。

## Historical 1.3.0 validation / 历史主题版验证

For 1.3.0, the full source suite passed 413 tests in 197.86 seconds on Windows using Fusion before the final fruit-asset, compact-star and UI diagnostic revisions; core and tooling code stayed unchanged afterward in that release. Its final native Windows GUI run passed 142 tests in 59.73 seconds, covering the restored 16-pixel loading area, crystalline single-star effect, face-free transparent stickers and revised diagnostics. The loading effects also passed 18 focused tests. These are separate runs, not a summed full-suite count or validation of 1.3.1.

1.3.0 的完整源码测试在 Windows 上使用 Fusion 样式运行，413 项通过，用时 197.86 秒；该版本此后只调整水果素材、细条单颗流星效果与界面诊断，核心与工具代码没有变化。其最终 Windows 原生界面复测 142 项通过，用时 59.73 秒，覆盖恢复的 16 像素加载区域、小晶核单颗流星、无表情透明贴纸与改进的诊断。加载效果另有 18 项专项测试通过。以上是独立运行的历史结果，不相加冒充单次完整测试数量，也不代表 1.3.1 已通过。

The rebuilt 1.3.0 Windows EXE ran its opt-in self-test successfully: exit code 0, frozen runtime, native Windows Qt platform, device-pixel ratio 1.5, and all 47 checks passed. The three themes passed loading-animation, unchanged measured value, static reduced-motion and stopped-timer checks. The PNG and SAES verification association cases both reported `captured_original`, confirming that authentication and both reported digests referred to the same captured data. Source diagnostics also passed all 47 checks; those source results are distinct from this actual EXE run.

重建后的 1.3.0 Windows EXE 已实际运行内置自检：退出码 0，使用打包运行环境与 Windows 原生 Qt 平台，设备像素比 1.5，47 项检查全部通过。三种主题的加载动画、真实进度值保持不变、减少动效后静态显示及停止计时检查均通过。PNG 与 SAES 的验证关联检查均返回 `captured_original`，确认认证与两项摘要对应同一份捕获数据。源码诊断也通过了 47 项检查，与本次实际 EXE 运行分开记录。

Native input tests send targeted events through QWindow and verify Qt event routing and actual Windows rendering. They do not claim to drive the operating system's global mouse pointer. Tests cover theme and language switching, control states, animation and reduced motion, file-drop behavior, and the existing processing workflows.

原生输入测试通过 QWindow 定向发送事件，验证 Qt 事件路由与真实 Windows 绘制，不声称驱动操作系统全局鼠标。范围包括主题与语言切换、控件状态、动效与减少动效、文件拖放，以及现有文件处理流程。

The core engine changed only its CLI version label in this appearance release. Later appearance edits require focused rendering and interaction checks without implying that the underlying cryptographic format changed. Prior 1.2.2 test counts remain historical and are not counted as tests of the 1.3.0 executable.

本次外观更新中，核心引擎仅调整 CLI 版本文字。之后的外观修改使用有针对性的渲染与交互测试验证；不把旧版测试数量或修改前的源码检查冒充新 EXE 的测试结果。

Raw reports and screenshots stay in local diagnostic directories outside the public archive. Tests use synthetic inputs. Public packaging uses the explicit source allowlist, exact portable-runtime manifest and final archive checksum checks described in `RELEASE.md`.

原始报告与截图保留在公开包之外的本机诊断目录，测试使用合成文件。公开工程按 `RELEASE.md` 所述的明确白名单、便携目录完整清单与归档校验流程生成。
