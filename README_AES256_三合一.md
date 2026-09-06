# AES-256-GCM + 密钥随机全图 PNG 隐写工具

> 以下为 v1.0 CLI 的历史使用说明。当前桌面版与资源/输出保护见 `README_DESKTOP.md`；CLI 参数以当前 `--help` 为准。格式版本仍为 v1，历史 `SHA256SUMS.txt` 不用于验证当前已更新的源码文件。

版本：1.0  
运行环境：Windows、macOS、Linux；Python 3.10 或更高版本。

这个工具在一个脚本中提供两套工作流：

1. **独立 AES-256 文件加密**：`encrypt` / `decrypt`，生成本工具专用的 `.saes` 文件。
2. **密钥 + 加密 + 隐写 + 解码三合一**：`hide` / `info` / `extract`，先加密，再把密文随机分散到 PNG 的 RGB 最低有效位。

## 1. 安全结构

工具采用：

- AES-256-GCM：机密性、完整性和认证；
- 每个输出使用新的 16 字节随机 salt；
- 每个输出使用新的 12 字节随机 AES-GCM nonce；
- 密钥文件模式：随机生成 256-bit 主密钥；
- 口令模式：scrypt，参数 `N=32768, r=8, p=1`；
- HKDF-SHA256：从主密钥派生两把互相独立的子密钥：
  - AES-256 加密密钥；
  - 隐写位置布局密钥；
- HMAC-SHA256 计数器随机源：控制密文在整张图片中的分散位置；
- SHA-256：恢复后再次核对原文件内容；
- Alpha 透明通道保持不变。

原文件名、原始长度、压缩状态、SHA-256 和文件内容都位于 AES-GCM 加密区内。

图片中仍有一个很小的引导头，用于保存格式版本、凭据模式、salt、nonce 和密文长度。引导头不包含秘密文件名或明文内容，并被作为 AES-GCM 的附加认证数据。修改引导头或密文都会导致认证失败。

**实际秘密密钥不会硬编码进脚本，也不会写进隐写 PNG。** 否则加密会失去意义。脚本包含密钥生成、加密、定位、认证、解码和提取逻辑；秘密本身保存在口令或独立 `.stegkey` 文件中。

## 2. 安装

解压工具包，在目录空白处打开 PowerShell：

```powershell
py -m pip install -r .\requirements.txt
```

也可以双击：

```text
安装依赖.bat
```

若电脑没有 `py` 命令，使用：

```powershell
python -m pip install -r .\requirements.txt
```

查看帮助：

```powershell
py .\png_steg_aes256.py -h
```

## 3. 推荐方案：一条命令生成密钥并隐写

假设目录中有：

```text
Minecraft 2023_11_8 18_39_21.png
xiaomo.pdf
png_steg_aes256.py
```

运行：

```powershell
py .\png_steg_aes256.py hide `
  ".\Minecraft 2023_11_8 18_39_21.png" `
  ".\xiaomo.pdf" `
  ".\Minecraft_xiaomo_AES.png" `
  --new-key-file ".\xiaomo.stegkey"
```

这条命令同时完成：

1. 生成随机 256-bit 密钥文件 `xiaomo.stegkey`；
2. 尝试压缩 PDF，只有确实变小时才采用压缩结果；
3. 使用 AES-256-GCM 加密文件名、元数据和文件内容；
4. 派生独立布局密钥；
5. 将密文按密钥随机分散到整张 PNG 的 RGB 通道；
6. 保存后自动重新提取；
7. 执行 AES-GCM 认证和 SHA-256 校验。

输出：

```text
Minecraft_xiaomo_AES.png   隐写图片
xiaomo.stegkey             独立密钥文件
```

不要把唯一一份密钥只放在与图片相同的目录、硬盘或压缩包中。密钥丢失后，没有恢复通道。

## 4. 检查隐写图片

```powershell
py .\png_steg_aes256.py info `
  ".\Minecraft_xiaomo_AES.png" `
  --key-file ".\xiaomo.stegkey"
```

检查成功时会显示：

- 原文件名；
- 原始大小；
- 加密前存储大小；
- 是否使用 zlib；
- 凭据模式；
- SHA-256；
- AES-GCM 认证结果。

## 5. 提取并解密

```powershell
py .\png_steg_aes256.py extract `
  ".\Minecraft_xiaomo_AES.png" `
  ".\恢复_xiaomo.pdf" `
  --key-file ".\xiaomo.stegkey"
```

省略第二个路径时，程序会恢复加密区中保存的原文件名：

```powershell
py .\png_steg_aes256.py extract `
  ".\Minecraft_xiaomo_AES.png" `
  --key-file ".\xiaomo.stegkey"
```

已有同名输出时，程序默认拒绝覆盖。明确需要覆盖时加入：

```text
--force
```

## 6. 先单独生成密钥

```powershell
py .\png_steg_aes256.py keygen ".\private.stegkey"
```

之后重复使用该密钥：

```powershell
py .\png_steg_aes256.py hide `
  ".\cover.png" `
  ".\secret.pdf" `
  ".\hidden.png" `
  --key-file ".\private.stegkey"
```

从密码学隔离角度看，不同用途使用不同密钥更好。不要长期用一把密钥覆盖所有资料。

## 7. 口令模式

省略所有密钥参数时，程序会在终端中安全询问口令，并要求输入两次：

```powershell
py .\png_steg_aes256.py hide ".\cover.png" ".\secret.pdf" ".\hidden.png"
```

提取：

```powershell
py .\png_steg_aes256.py extract ".\hidden.png" ".\recovered.pdf"
```

也支持：

```text
--password "你的口令"
```

但该写法可能把口令保留在 PowerShell 历史、进程参数或日志中，因此只适合临时测试。正式使用应省略 `--password`，让程序交互输入。

口令建议使用长度至少 16 个字符的随机短语，不要使用生日、手机号、姓名、常见句子或单个单词。

## 8. 独立 AES-256 文件加密版

### 8.1 自动生成密钥并加密

```powershell
py .\png_steg_aes256.py encrypt `
  ".\xiaomo.pdf" `
  ".\xiaomo.pdf.saes" `
  --new-key-file ".\xiaomo_aes.stegkey"
```

### 8.2 解密

```powershell
py .\png_steg_aes256.py decrypt `
  ".\xiaomo.pdf.saes" `
  ".\恢复_xiaomo.pdf" `
  --key-file ".\xiaomo_aes.stegkey"
```

`.saes` 是本工具的认证加密容器，不是 ZIP、7z、PDF 或通用行业格式，必须使用本工具解密。

## 9. 容量与自动放大

查看图片容量：

```powershell
py .\png_steg_aes256.py capacity ".\cover.png"
```

版本 1.0 的可用 AES 密文容量为：

```text
floor((宽 × 高 × 3 - 432) / 8) 字节
```

其中：

- 每像素只使用 R、G、B 三个通道；
- 每通道使用 1 个最低有效位；
- 432 个通道用于 54 字节引导头；
- AES-GCM 密文还包含 16 字节认证标签；
- 加密区内部还有文件名和元数据开销。

容量不足时：

```powershell
py .\png_steg_aes256.py hide `
  ".\cover.png" `
  ".\secret.pdf" `
  ".\hidden.png" `
  --new-key-file ".\secret.stegkey" `
  --auto-resize `
  --max-fill 0.60
```

`--max-fill 0.60` 表示自动放大后，密文最多占可用主体容量的 60%。较低占用率通常意味着更大的输出尺寸；它不能保证对隐写分析不可检测。

默认最大像素数为 150,000,000。超过时程序拒绝继续，避免普通电脑出现异常内存消耗。可以用 `--max-pixels` 调整，但不建议盲目提高。

## 10. 不能对隐写图片做的操作

以下处理通常会破坏最低有效位：

- 转换成 JPEG；
- 微信、QQ、社交平台的图片压缩；
- 缩放、裁剪或旋转后重新保存；
- 截图；
- 滤镜、降噪、锐化、调色；
- PNG 优化器重写像素；
- 任何会改变像素值的编辑。

传输时应：

- 作为“文件”发送，而不是作为“图片”；
- 或先把隐写 PNG 放进 ZIP/7z；
- 上传网盘时选择原文件；
- 提取前先用 `info` 验证。

## 11. 威胁模型边界

AES-256-GCM 能保护秘密内容，并检测错误密钥与像素破坏；它不意味着隐写图片不可被发现。

该工具仍属于 LSB 隐写：

- 专业隐写分析可能判断图片统计分布异常；
- 输出尺寸、文件大小或最低位分布可能引起注意；
- 固定格式的引导头对了解本工具的人可被识别；
- 加密解决“读不懂内容”，随机布局降低直接顺序提取的可行性，但不能保证隐藏通信的存在永远不暴露。

不应把它描述成“绝对隐身”“无法检测”或“不可破解”。安全性主要依赖：

1. 密钥或口令不泄露；
2. AES-GCM 和 KDF 实现保持正确；
3. 原始 PNG 不被修改；
4. 密钥与隐写图片分开保存；
5. 使用足够强的口令。

## 12. 常见错误

### `图片容量不足`

换更高像素的载体，或添加：

```text
--auto-resize
```

### `认证失败`

常见原因：

- 口令错误；
- 使用了错误的 `.stegkey`；
- 图片被重压缩或编辑；
- 隐写图片传输时被平台改变。

### `凭据类型与隐写文件不匹配`

创建时使用了密钥文件，提取时却输入了口令，或反之。

### `输出文件已存在`

更换输出名称，或确认后添加：

```text
--force
```

## 13. 工具包文件

```text
png_steg_aes256.py              主程序
requirements.txt                运行依赖
requirements-dev.txt            测试依赖
安装依赖.bat                    Windows 安装入口
运行测试.bat                    Windows 测试入口
tests/test_png_steg_aes256.py   自动化测试
SHA256SUMS.txt                   包内关键文件哈希
```
