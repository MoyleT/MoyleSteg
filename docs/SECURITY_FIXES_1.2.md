# 1.2.0 文件安全修复与验证说明

这是 **1.2.0 的历史修复与验证记录**。其中测试数量、交付范围和命令对应 1.2.0，不代表 1.2.1 的验证结果。当前发布流程见 `RELEASE.md`，1.2.1 的可靠性修复及验证范围见 `RELIABILITY_1.2.1.md`。

本版本保持容器格式 v1、AES-256-GCM、随机 salt/nonce、HKDF 用途分离和既有像素布局不变。修改重点是文件操作、资源检查和长任务交互。测试使用合成数据；本说明不含私人文件路径、名称、内容、密钥或摘要。

## 修复范围

| 问题 | 共同底层的处理 | 回归验证 |
| --- | --- | --- |
| 新密钥或输出覆盖源文件、载体、凭据 | `validate_operation_paths` 在 CLI 生成密钥前检查完整写入集合；`Credential.from_key_file` 保留凭据路径；核心函数和提交层均保护输入及其路径别名。普通 `force` 不解除保护；密钥与输出互为父子路径也拒绝。 | CLI 危险参数、直接核心调用、按原名恢复冲突、普通允许覆盖的合法对照。 |
| 无覆盖授权仍被并发替换 | 所有文件先写同目录临时文件；默认提交在 Windows 使用不覆盖目标的 `os.rename`，POSIX 使用排他创建的 `os.link`。只有明确 `force=True` 使用 `os.replace`。不支持安全提交的文件系统直接报错。 | 两个独立 CLI 进程同时加密各自的 8 MiB 合成文件，竞争同一输出；还在提交原语前注入另一个文件创建。 |
| 工程 ZIP 带有私人测试元数据 | 发布脚本采用公开文件白名单，排除整个 `artifacts`、开发环境、缓存及历史 ZIP。运行库须匹配干净构建的完整清单和摘要，并在复制字节时再次校验；运行目录内额外诊断文件也会导致拒绝打包。 | 私有标记、运行目录任意位置的额外报告、已有运行文件改写及检查后改写均测试；保留必需的嵌套 `base_library.zip`。 |
| 资源检查太晚、不统一 | 载体只读尺寸检查先于载荷读取、压缩及像素展开；放大后的整数尺寸先检查再分配；SAES 固定头、实际长度和预算先检查再读取主体；解压前检查认证后的原始大小。密钥文件也限制读取长度。 | 以失败探针证明大操作未执行；图片各入口、文件读取、压缩后恢复、整数放大尺寸分别测试。 |
| SAES 保存后自检名不副实 | 临时文件写入、flush/fsync、关闭后，重新打开并独立解析、解密认证、核对摘要，最后提交。PNG 保持相同流程。 | 在 fsync 后篡改临时密文；必须认证失败、保留旧目标并清理临时文件。 |
| EXIF 预览与成品方向不同 | 只在准备载体时应用 EXIF 方向，嵌入后不旋转。重新创建的 PNG 不复制 EXIF/GPS。解码既有隐写 PNG 仍按原始像素顺序。 | 带方向标记的 80×40 JPEG 生成 40×80 PNG，恢复字节一致且无 EXIF。 |
| Windows 恢复文件名规则分裂 | 新载荷及按原名恢复使用共同严格验证器，拒绝设备名、盘符相对形式、流名称、非法字符与末尾点/空格。旧 POSIX 名称允许认证和手动指定安全输出名。 | 危险名称矩阵，以及由原始 v1 核心生成的旧格式与 POSIX 名称兼容夹具。 |

## 交互更新

- 真实阶段与阶段内计数：读取、压缩、加密、像素处理、保存、回读验证。无法计算总量的阶段显示活动状态，不模拟总进度。
- 协作式取消：工作循环与安全边界响应取消；提交前取消不发布结果，清理临时输出。原生加密、图像编解码等同步调用期间须等待该调用返回。文件提交后以成功为准。
- 容量预检：实际读取并压缩当前载荷，展示压缩后大小、密文大小、容量、尺寸、占用率及可行性；再次执行时重新检查。内存值为估算，不是测量值或操作系统硬性配额。
- 统一只读验证：按签名识别 PNG/SAES，不写出明文；分别展示恢复内容 SHA-256 与整个输入容器 SHA-256。

默认资源预算为 **25,000,000 像素、256 MiB 原始文件**。CLI 与 Python API 提供显式预算参数；超出预算不会因为启用自动扩容而自动放宽。Pillow 自身的解压炸弹保护仍然保留。

新密钥在任务内生成、受口令保护的密钥格式、批量队列与流式大文件加密不属于本次已交付功能。现有独立密钥工具保留；SAES v1 仍使用内存中的整体加密。

## 验证命令与证据

主要变更位于 `png_steg_aes256.py`（共同边界、资源、提交与取消）、`moyle_steg/service.py`（恢复与只读验证）、`worker.py` / `window.py` / `widgets.py` / `i18n.py`（交互）、`diagnostics.py`（真实控件自检）及 `scripts/build_desktop.py` / `package_project.py`（公开发布）。新增回归位于 `tests/test_core_safety.py`、`test_core_resources_progress.py`、`test_legacy_v1.py`、`test_packaging.py` 和 `test_v12_*.py`。

最终源码全套 **235 项通过**；Windows 原生界面单独 **21 项通过**；`git diff --check` 通过。曾失败的触发用例现均通过，普通路径、明确允许覆盖的普通目标、正确口令/密钥、原名恢复及旧格式夹具仍能正常完成。独立复核额外发现的盘符相对写入入口和运行目录诊断文件打包路径，均经复现、修复与回归验证。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\dist\MoyleSteg\MoyleSteg.exe --self-test <本机诊断报告位置>
.\.venv\Scripts\python.exe scripts/package_project.py --output dist/MoyleSteg-1.2.0-Full-Project.zip
```

原始问题的测试先在旧源码上失败，包括两个 CLI 进程均返回成功的竞争复现。修复后的聚焦验证已覆盖这些触发路径及正常回环、错误凭据、位篡改、Alpha 保持、随机性和旧格式兼容性。最终发布的运行结果见 `RELEASE.md`；本机原始诊断工件不随包分发。

本次验证不构成正式密码学审计，也不保证对恶意系统管理员、持续改变目录连接的外部程序或失效硬件提供隔离。Windows 为实际运行和打包环境；POSIX 提交分支按系统 API 语义实现，未声称完成 Linux 运行验证。

## 官方接口依据

- [Python 文件操作语义](https://docs.python.org/3/library/os.html#os.rename)：Windows 重命名目标存在时失败；`os.replace` 则允许替换。
- [Pillow EXIF 转置](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose)：在转换载体像素时应用方向。
- [Qt QThread](https://doc.qt.io/qt-6/qthread.html#requestInterruption)：线程中断请求本身不会停止同步函数，必须由工作代码响应。
