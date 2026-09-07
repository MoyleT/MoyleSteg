# Multi-file release / 多文件版 1.6.0

Windows now accepts multiple files on the Hide and Encrypt pages. Select or drop
files together, remove unwanted entries, and check the original total size.
One file follows the existing single-file path; two or more are packaged into a
managed standard ZIP, then encrypted with one shared password or key. Capacity
preflight creates the actual archive and reports both source total and ZIP size.
JPEG carriers still produce PNG; GIF carriers retain the existing GIF extension.
No encrypted container version or key format changes are introduced.

隐藏文件和独立加密页面支持多选、拖入、移除与原始大小合计。单文件保持原流程；
两个及以上文件会自动打包，再共用一组口令或密钥加密。容量预检使用实际 ZIP，
分别显示源文件总大小、打包大小与成品容量。JPEG 载体仍输出 PNG，GIF 保持原动画。

## Recover all or selected files / 按需恢复

Authentication comes first. A managed bundle displays its authenticated names,
sizes and selection controls before any member is written to the chosen public
folder. Save selected files or all pending files. Duplicate names receive numbered
suffixes. The ordinary overwrite checkbox does not authorize replacing multi-file
outputs. Each file is privately extracted, checked against its authenticated
SHA-256 and size, copied in bounded blocks, read back independently and committed
without replacing an existing file.

认证成功后先显示文件清单，用户可保存选中项或全部待保存文件。同名文件自动增加
编号，不覆盖已有文件；普通覆盖选项不适用于多文件恢复。每项在私有副本中校验后
才保存，落盘回读通过后以禁止覆盖方式提交。

A batch is a sequence of per-file commits, not a transaction across every file.
If cancellation or a later write failure occurs, files already committed remain
saved and are recorded with their actual output paths. Retry saves only pending
files, without asking for the password again. Changing the container, starting a
different task, clearing the result or closing the app cleans its owned private
recovery session; public saved files remain. Cleanup is ordinary file deletion,
not a promise of secure erasure on SSDs or operating-system caches.

多文件保存按项完成。取消或某项失败时，已完成文件保留，剩余项可直接重试，无需
再次输入口令。更换输入、开始其他任务、清空结果或关闭软件会删除程序持有的私有
恢复副本，但保留已保存到所选文件夹的文件。这里的清理不承诺存储介质级安全擦除。

The explicit **Save complete ZIP** action exports the complete managed archive.
Ordinary user ZIPs without the exact marker are restored as one file and are never
automatically unpacked. Older app versions can recover `MoyleSteg-files.zip`, then
users can unzip it with a standard archive application. Read-only verification
continues to write no plaintext recovery files.

“另存完整 ZIP”可导出整个多文件包。没有明确标记的普通用户 ZIP 仍按单文件恢复，
不会自动解包。旧版可以恢复 `MoyleSteg-files.zip` 后使用常规工具解压；只读验证
继续不写出明文恢复文件。

## Profile and limits / 格式与限制

The standard ZIP comment is exactly ASCII `MOYLESTEG-BUNDLE-V1`. There are 1–100
regular-file entries, ordered and numbered `0001/<original-name>` through
`0100/<original-name>`. Names are UTF-8, 1–180 bytes, and pass the shared safe
filename rules. Numbered ZIP entry paths preserve repeated basenames. Only STORED
and raw DEFLATE are accepted; no encryption inside ZIP, ZIP64, spanning, symbolic
links, device entries, nested directory trees or arbitrary extraction paths.

Both archive bytes and total expanded source bytes have explicit limits. The
desktop creation flow applies its file budget to each total. Before parsing ZIP
entries the core validates the fixed end record and bounds central metadata to
128 KiB. Streaming CRC and SHA-256 checks enforce actual data sizes. Selecting
many files does not increase a PNG's capacity or remove the existing resource
limits. Current desktop image and payload encryption still use memory; bounded
ZIP copying does not make the complete desktop encryption pipeline streaming.

## Release checks / 发布验证

The Windows full test run passed **815 tests**. Subsequent bundle-only layout
refinements were checked by **47 native Windows Qt tests**, covering multi-file
selection, keyboard navigation, the native diagnostic workflow, 100 long-name
entries, narrow windows, large text, and immediate hiding of retired list rows.
These are separate runs; 815 is the full-run count before those final layout
refinements, not an additional full run of every final test definition.

The delivered **1.6.0 Windows EXE passed 73 native self-checks**, including real
multi-file PNG creation through the UI, authenticated member selection, saving
selected and remaining members, duplicate-name handling, ZIP fallback, private
session cleanup, and readable saved rows at normal and narrow/large-text sizes.
Synthetic member bytes and the authenticated ZIP SHA-256 were checked after
saving. The EXE was rebuilt after the final changes; no offscreen rendering is
being described as native Windows execution.

Windows 全量测试 **815 项通过**。此后的多文件列表局部排版收尾由 **47 项原生
Qt 定向测试**验证；两者是不同测试轮次，不应相加或表述成最后又跑过一次全量。
最终交付的 **1.6.0 EXE 原生自检 73 项通过**，覆盖实际界面操作、按项保存、
同名处理、ZIP 导出、私有副本清理及普通/窄屏大字号布局。测试使用合成文件。

Release archives include public source and the exact inventoried runtime only;
private diagnostic reports, screenshots containing local paths, and temporary
recovery files are excluded. Archive membership, sizes and SHA-256 are verified
when packaging. These checks do not claim an independent external audit or a
physical Android device test.
