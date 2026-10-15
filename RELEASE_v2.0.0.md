# 拾字 PickText v2.0.0

屏幕离线 OCR 取字工具的第二个正式版本。本版本重点是**古籍场景支持**与**品牌化落地**。

## ✨ 新增功能

- **竖排古籍识别**：自动将竖排文本（从右到左、列内从上到下）重排为正常阅读顺序，适配扫描版古籍、碑帖。
- **简繁转换**：基于 OpenCC，识别结果一键转为繁体（传统汉字）。
- **规则自动标点**：离线规则引擎，自动补入逗号 / 句号等标点。默认开启，纯本地运行，无云端依赖。
- **锁定区域监控**（v2 早期提交）：`Ctrl+Alt+M` 启动，对指定屏幕区域按间隔轮询 OCR，结果实时刷新。
- **结果可编辑 + 导出**（v2 早期提交）：识别结果窗口支持编辑、复制与导出。

## 🎨 品牌与图标

- 正式定名「**拾字 / PickText**」：托盘、关于弹窗、README 统一品牌呈现。
- 全新图标：蓝→青渐变圆角磁贴 + 白色「字」+ 四角取景框，内置多尺寸（16–256），小尺寸自适应保证清晰可辨。
- `--version` 输出纯 ASCII（`PickText 2.0.0`），避免非 UTF-8 控制台乱码。

## 🛠 工程改进

- 日志轮转（`RotatingFileHandler`）。
- 依赖由 `opencc-python` 改为纯 Python `opencc`（规避原包构建失败）。
- 新增 `layout.py` 与 pytest 单测（当前 17 passed）。
- 构建目录规范化（`.gitignore` 忽略 `build*/` `dist*/`）。

## 🔑 快捷键

| 操作 | 快捷键 |
| --- | --- |
| 全屏识别 | `Win+Alt+O` |
| 区域识别 | `Win+Alt+Q` |
| 锁定区域监控 | `Ctrl+Alt+M` |
| 关闭结果窗口 | `Esc` |

## 📦 下载

- **Windows 64 位**：下载本 Release 附带的 `PickText-win64-v2.0.0.zip`，解压后运行 `OCRClient.exe` 即可（内部二进制名仍为 `OCRClient.exe`，品牌仅呈现在交互层）。
- 完全离线、不上传云端，基于 RapidOCR（ONNX）本地推理。

## 🐞 热修复（v2.0.0）

- 修复**触发模式**（选区触发 / 锁定区域监控）首次运行时 `NameError: name '_engine' is not defined` 崩溃：`get_engine()` 引用的模块级单例 `_engine` 此前未初始化，已在源码补充 `_engine = None`（提交 `f2ee965`）。已重建打包并刷新本 Release 附带的 `PickText-win64-v2.0.0.zip`。

## 🐞 后续补丁（v2.0.0 patch，已刷新资源）

> 托盘「OCR 选项...」点击无反应 + 弹窗内容显示不全，并合入若干稳定性修复。源码已提交并推送，附带的 `PickText-win64-v2.0.0.zip` 已重建刷新。

- **托盘「OCR 选项...」点击无反应**：`WM_OCR_SETTINGS_SHOW` 与 `WM_HOTKEY_RELOAD` 同为 `WM_APP+6` 撞车，`_wndproc` 先匹配后者，导致点击 OCR 选项实际执行「重新注册热键」并静默 return（日志无输出）。已将两个弹层消息号统一归拢到文件上方常量区（`WM_APP+11 / +12`），并新增模块级 `_CUSTOM_MSGS` **启动自检**——任意两个 `WM_APP+n` 重复即打印告警，防止同类事故复发。
- **弹窗内容显示不全（底部按钮被裁）**：三个弹层（OCR 选项 / 快捷键设置 / 运行日志）的布局坐标按客户区设计，但 `CreateWindow` 时把客户区高度当窗口总高度传入，标题栏+边框约 39px 吃掉底部一条。新增 `_client_size_to_window_size`（`AdjustWindowRect` 反算窗口尺寸）+ `_fit_client_area`（实测 `GetClientRect` 校正、兜底窗口级 `WS_VSCROLL`/DPI 残差），三个弹窗现已完整显示。
- **OCR 弱对比 / 小字增强**：识别前对淡灰字做 min-max 拉伸、短边 <200px 时放大（默认开，可在「OCR 选项」关闭），rec 阈值降到 0.35 提高召回，并滤除高 < 0.45×中位高且不含 CJK 的小框噪声（如 `99`），修小字 / 弱对比漏识（如「吃瓜时间到→」）。
- **冻结打包修复**：`rapidocr` 内联子模块注册进 `sys.modules`，PyInstaller `collect_submodules`，解决 `module 'ch_ppocr_v3_det' has no attribute 'TextDetector'`；OCR 选项弹窗改独立线程、Toast 改用 `threading.Timer` 替代缺失的 `win32gui.SetTimer`，修冻结环境弹窗 / 提示异常。
- 单测 **17 → 21 passed**；`OCRClient.exe --selftest` 自测通过（引擎初始化成功 + OK，无消息号冲突告警）。

> 注：「OCR 选项」四组开关：竖排模式 / 输出繁体 / 自动标点（离线规则）/ 弱对比小字增强，落盘 `ocr_settings.json`，重启保留。
