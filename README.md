# 屏幕 OCR 客户端（离线 · 全屏一键识别）

一个常驻后台的 Windows 屏幕取字小工具。按快捷键抓取整个屏幕，用本地 OCR 引擎识别其中所有中英文 / 字母 / 数字，自动复制到剪贴板，并弹出结果窗口支持「框选复制」与「一键复制全部」。**全程离线，不依赖任何云端 API。**

## 功能特性

- **全局快捷键触发**：即使焦点在其它软件上也能唤起识别。
- **全屏一键识别**：抓取主显示器（或全部显示器）整屏，自动 OCR。
- **一键复制全部**：识别完成后整段文本自动写入剪贴板，可直接粘贴。
- **选择复制**：弹出原生结果窗口，鼠标框选任意部分后 `Ctrl+C` 即可复制；也可点「复制全部」按钮。
- **ESC 退出**：随时退出整个程序。
- **离线引擎**：基于 [RapidOCR](https://github.com/RapidAI/RapidOCR)（ONNX 推理），内置模型，无需联网。

## 运行环境

- Windows 10 / 11（依赖 Win32 API 与全局热键）
- Python 3.13（隔离 venv，不污染系统环境）
- 依赖：`mss`、`rapidocr-onnxruntime`、`pynput`、`pyperclip`、`numpy`、`pywin32`

> 说明：本项目使用 WorkBuddy 管理的隔离 Python（`C:\Users\microsnow\.workbuddy\binaries\python\envs\ocrclient`），依赖已安装在该 venv 中。

## 快速开始

### 1. 安装依赖（仅首次）

若 venv 未创建或未装依赖，先建隔离环境并安装：

```bat
:: 使用 WorkBuddy 管理的 Python 创建 venv（路径按本机实际情况调整）
C:\Users\microsnow\.workbuddy\binaries\python\versions\3.13.12\python.exe -m venv C:\Users\microsnow\.workbuddy\binaries\python\envs\ocrclient

:: 激活并安装依赖
C:\Users\microsnow\.workbuddy\binaries\python\envs\ocrclient\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 运行

**方式一（推荐）：双击启动器**

直接双击项目目录下的 `run.bat`，它会调用 PowerShell 脚本 `run.ps1` 用隔离 venv 启动 `main.py`，并绕过默认执行策略。

**方式二：直接运行**

```bat
C:\Users\microsnow\.workbuddy\binaries\python\envs\ocrclient\Scripts\python.exe main.py
```

**方式三：PowerShell 直接运行**

在文件管理器中右键 `run.ps1` →「使用 PowerShell 运行」。（注意：直接双击 `.ps1` 默认会用记事本打开，不要直接双击。）

## 使用说明

启动后控制台会常驻监听，并显示当前配置（快捷键、识别范围等）。

| 操作 | 效果 |
|---|---|
| 按 `<ctrl>+<alt>+o>` | 抓取屏幕 → OCR 识别 → 自动复制全部 → 弹出结果窗口 |
| 在结果窗口中框选文字 + `Ctrl+C` | 复制选中部分（选择复制） |
| 点结果窗口「复制全部」按钮 | 复制整段文本 |
| 点「关闭」或标题栏 X | 隐藏结果窗口（下次识别再显示） |
| 按 `ESC` | 退出整个程序 |

典型流程：常驻后台 → 看到想复制的文字 → 按快捷键 → 自动复制 → 切换目标窗口 `Ctrl+V` 粘贴；如需只取某几行，从结果窗口框选复制。

## 配置说明

所有配置集中在 `main.py` 顶部「配置区」，按需修改后重新运行即可：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `HOTKEY` | `<ctrl>+<alt>+o` | 识别触发快捷键，可改为 `<ctrl>+<shift>+o` 等 |
| `EXIT_KEY` | `<esc>` | 退出快捷键 |
| `MONITOR` | `1` | `1` = 主显示器；`0` = 全部显示器（拼接大图，4K 下较慢） |
| `AUTO_COPY_ALL` | `True` | 识别后是否自动复制全部到剪贴板；设 `False` 则只弹窗手动选择 |
| `SHOW_WINDOW` | `True` | 是否弹出结果窗口（支持框选复制） |

> 快捷键语法遵循 `pynput`：`+` 连接组合键，`<ctrl>` `<alt>` `<shift>` `<esc>` 等为按键名。

## 文件结构

```
09-ocr/
├── main.py          # 主程序：截屏 + OCR + 剪贴板 + 原生结果窗口
├── requirements.txt # Python 依赖清单
├── run.bat          # 双击启动器（调用 run.ps1）
├── run.ps1          # PowerShell 启动脚本（环境检查 + 启动）
└── README.md        # 本说明文档
```

## 常见问题

**Q：运行报错 `ModuleNotFoundError: No module named 'tkinter'`？**
A：旧版本使用 tkinter 弹提示，已改为 `pywin32` 原生窗口，不再依赖 tkinter。请确认已安装 `pywin32`（`pip install pywin32`）。

**Q：双击 `run.bat` 提示找不到路径 / 乱码？**
A：`.bat` 必须是纯 ASCII 且使用 CRLF 换行，否则中文 Windows 的 `cmd` 会误读。当前 `run.bat` 已为最小启动器（仅一行调用 PowerShell），不会出现该问题。

**Q：识别速度？**
A：首次启动会加载 ONNX 模型（约 1 秒）；之后每次热键识别通常 1 秒左右（含整屏截屏）。`MONITOR=0` 抓取全部显示器会明显变慢。

**Q：支持多显示器吗？**
A：支持。将 `MONITOR` 改为 `0` 可抓取全部显示器并拼接识别（注意性能）。

**Q：能识别表格 / 复杂版面吗？**
A：RapidOCR 为行列文本识别，适合一般文字抓取。如需版面分析（表格、排版还原），可后续替换为 PaddleOCR 的 PP-Structure（引擎已抽象，便于切换）。
