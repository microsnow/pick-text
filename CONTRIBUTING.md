# 贡献指南（Contributing）

感谢你考虑为拾字 PickText 贡献代码。本项目很小，流程尽量简单。

## 许可约定

本项目采用 **MIT-0（无需署名）** 许可证。你贡献的代码将以同样的方式授权——
**不要求你放弃著作权到公有领域，也不需要在作品里署名**。你保留自己代码的
著作权，只是授予他人使用、修改、分发的自由。

> 若你希望自己的贡献以其他条款授权（例如禁止他人商用），请**不要**提交 PR，
> 或在 PR 中明确说明，我们会在讨论后再决定如何处理。

## 开发环境

```bat
:: 1) 创建虚拟环境
python -m venv .venv

:: 2) 安装依赖
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pystray pillow pytest   :: 桌面版 + 测试

:: 3) 运行
.venv\Scripts\python.exe main.py
```

**运行环境**：Windows 10 / 11（依赖 Win32 API、全局热键与系统托盘）。
本项目不打算支持 macOS / Linux——大量代码直接调用 `user32` / `shell32`。

## 提交前必做

```bat
:: 1) 全部测试必须通过
.venv\Scripts\python.exe -m pytest tests/ -q

:: 2) 自检（初始化 OCR 引擎、校验自定义消息号无冲突）
.venv\Scripts\python.exe main.py --selftest
```

两条命令都必须在提交前跑通。`--selftest` 会输出 `自定义消息号冲突` 之类的告警，
**这些告警不是可以忽略的**——历史上就发生过 `WM_APP+n` 撞车导致托盘菜单点了
没反应的事故，代码里为此加了自检，务必尊重它。

## 代码风格

- 保持与现有风格一致：中文注释、模块级配置区集中在文件顶部、函数写清意图
- **所有 `WM_APP+n` 自定义消息号必须集中定义在文件顶部的常量区**，并登记进
  `_CUSTOM_MSGS` 字典。禁止在文件中部临时定义（这正是上述事故的根因）
- 纯逻辑函数尽量放在 `layout.py`，便于单测；`main.py` 只放与 UI/线程相关的代码
- 新增功能请顺带补单测到 `tests/test_ocr.py`

## 涉及 Win32 的改动请特别小心

这个项目里有几处**看起来能跑、实际会静默失效**的坑，改动时务必注意：

- **低级键盘钩子**：`lParam` 必须用指针宽度（`ctypes.c_ssize_t`）。用
  `wintypes.LPARAM`（有符号 32 位）会截断指针，`vkCode` 读出来的是地址碎片。
  回归测试见 `tests/test_ocr.py` 中 `test_hook_*` 系列
- **`CallNextHookEx` 必须声明 `argtypes`**，否则整数参数溢出
- **钩子回调里不要做耗时操作**，否则 Windows 会在 `LowLevelHooksTimeout`
  之后静默摘除钩子。正确做法是回调里只 `PostMessage`
- **自定义消息用 `PostMessage` 跨线程传递**，不要在非 UI 线程直接操作窗口
- **不要在 `print` 的文案里用非 ASCII 符号**（如 ✓ ✗ ✅ ❌）。打包版
  `console=False`，输出重定向到管道时编码会退化为 GBK，一个无法编码的字符就会
  抛 `UnicodeEncodeError`，PyInstaller 会弹出 "Unhandled exception in script"
  对话框，程序直接崩溃。判定成败请用 `[OK]` / `[FAIL]` 这类纯 ASCII 标记
  （程序已在 `main()` 开头对 stdout 做 `errors='replace'` 加固作为兜底）

## Pull Request

1. 从 `main` 切出分支，命名随意（`fix/xxx`、`feat/xxx` 均可）
2. 保持一次 PR 聚焦一件事——混在一起的巨型 PR 很难审
3. PR 描述里写清：**改了什么、为什么、怎么验证的**
4. 附上测试结果（`pytest` 输出）和必要的截图（UI 改动）

## 报告 Bug

开 issue 时请附上：

- Windows 版本（`winver` 输出）
- Python 版本
- 运行方式（源码直跑 / 打包版）
- 复现步骤
- **托盘右键 →「运行日志」的完整内容**——这里有详细信息，比"报错了"有用得多

## 不接受的贡献

- 引入带 copyleft（GPL / AGPL）传染性的依赖。当前依赖树刻意保持宽松，
  唯一的 LGPL（pystray）已确认不构成约束。若你确有必要引入新的依赖，
  请先开 issue 讨论许可影响
- 引入重量级框架（GUI 框架、Web 服务等）——本项目坚持 pywin32 原生 + 轻依赖
- 未经讨论的大规模重构

---

再次感谢。你的贡献不需要署名，但会很有价值。