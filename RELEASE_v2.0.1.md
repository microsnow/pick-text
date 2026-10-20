# 拾字 PickText v2.0.1

Toast 提示缺陷修复版本。v2.0.0 发布后用户反馈 toast「有框但无内容、且不会自动消失」，
本版本修复该问题并补充回归测试。

## 🐛 缺陷修复

### 1. Toast 有框但无内容（白刷覆盖深色底）

**现象**：toast 弹出后只有一个彩色边框方框，内部空白，看不到任何文字。

**根因**：`ToastWindow._paint` 先用 `FillRect` 铺设深色底`RGB(30,30,30)`，
紧接着调用 `Rectangle` 绘制边框。GDI 语义上：

- `Rectangle` 会用**DC 当前选中的画刷**填充矩形内部；
- 而 `FillRect` 只是临时使用传入的画刷，**不会改变** DC 的当前画刷。

因此默认的白色画刷把刚铺好的深色底重新填成了白色，
白色文字 `RGB(255,255,255)` 落在白色背景上，等于什么都没显示。

**修复**：`Rectangle` 前 `SelectObject(GetStockObject(NULL_BRUSH))`，绘制完还原画刷。

**验证**：离屏像素对比——修复前内部纯白像素 5481/5481（100%），
修复后深色底占 93%、白色文字 150px。

### 2. Toast 不会自动关闭（消息未被分发）

**现象**：toast 一直停留在屏幕上，直到手动关闭。

**根因**：`_on_timeout` 使用 `PostThreadMessage(thread_id, WM_TIMER, ...)` 投递定时消息。
该 API 投递的消息 **hwnd 为 NULL**，`DispatchMessage` 不会将其分发给任何窗口过程，
于是 `WM_TIMER` 永远到不了 `_wndproc` → 不触发 `PostQuitMessage` →
`PumpMessages` 永久阻塞 → 窗口无法自行销毁。

**修复**：改用 `PostMessage(self.hwnd, WM_TIMER, ...)`（消息携带窗口句柄，可正常分发）。
另新增 `_force_quit` 兜底（`PostThreadMessage` 投递 `WM_QUIT` 结束消息循环），
并将两个定时器设为daemon，保证任何异常路径下 toast 都不会残留。

**顺带纠正**：原代码注释称「打包环境的 pywin32 不带 `win32gui.SetTimer`」——
实测 `win32gui.SetTimer` 与 `win32api.SetTimer` 在 pywin32 中**均不存在**，
这正是当初绕道 `threading.Timer` 的原因，注释判断有误。

## 🧪 测试

新增 `tests/test_toast.py`（7 项，全部通过）：

| 用例 | 覆盖点 |
| --- | --- |
| `test_toast_content_is_visible[×3]` | 三种 kind 的深色底 + 白字可见性 |
| `test_toast_auto_closes[600/1200]` | 到点消息循环自行退出 |
| `test_multiple_toasts_close_independently` | 多条并发 toast 各自按时消失、无残留 |
| `test_post_thread_message_would_not_dispatch` | AST 静态断言，防止回退到 `PostThreadMessage` |

验证方式说明：分层窗口（`WS_EX_LAYERED`）用 `GetWindowDC`/`PrintWindow`
常抓不到内容，故内容校验改为将 `_paint` 画到离屏位图读回像素，绕开屏幕合成与 DPI 干扰。

## 📦 构建产物

- 目录版：`dist/OCRClient/`（185 文件，240 MB）
- 发布包：`dist/PickText-win64-v2.0.1.zip`（97.9 MB，CRC 校验通过）

打包环境：Python 3.13 + PyInstaller 6.22.3（onedir，`console=False`，`assets/icon.ico`）。

**打包后自检**（`OCRClient.exe --selftest`）五项全通过：

```
[selftest] OCR 引擎: RapidOCR [OK]
[selftest] 系统托盘: 可用 [OK]
[selftest] 自定义消息号: 11 个 全部唯一 [OK]
[selftest] Esc 键盘钩子: 安装/卸载正常 [OK]
[selftest] 钩子结构体: 24 字节 [OK]
```

实机启动确认：托盘静默驻留（内存约 127 MB），`ocrclient.log` 无任何报错，
低级键盘钩子安装正常。

## 🔑 快捷键（与 v2.0.0 一致）

| 操作 | 快捷键 |
| --- | --- |
| 全屏识别 | `Win+Alt+O` |
| 区域选择识别 | `Win+Alt+Q` |
| 锁定区域监控 | `Ctrl+Alt+M` |
| 定义/触发选区预设 | `Ctrl+Shift+N` / `Alt+Shift+N` |
| 关闭当前弹窗 | `Esc` |