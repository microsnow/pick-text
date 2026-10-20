# OCRClient 下一版本开发计划（v2.0）

> **说明（归档）**：本计划已随 v2.0.0 全部落地，保留作为功能演进的路线图参考。
> 文中的「估时」为立项时的内部估算，不再作为排期依据。实际交付说明见
> [`RELEASE_v2.0.0.md`](../RELEASE_v2.0.0.md)。

> 范围说明：本计划覆盖上一轮建议中"最贴合使用习惯"的三个高价值功能：
> 1. 锁定区域轮询抓取（监控模式）
> 2. 竖排 + 繁体古籍识别（含自动标点）
> 3. 结果可编辑 + 一键导出
>
> 工程化项（日志轮转、自动化测试、版本号、代码签名）作为配套在对应里程碑中顺带落地，不单列大块。
> 代码现状基准：`main.py` 2273 行，已具备离线 RapidOCR、Win32 独占热键、原生 Win32 UI、系统托盘、选区预设。

---

## 总览

| # | 功能 | 用户价值 | 技术风险 | 估时 |
|---|---|---|---|---|
| 1 | 锁定区域轮询抓取 | 高（命中反复抓字幕/歌词的真实场景） | 中（线程/坐标/CPU） | ~2 人日 |
| 2 | 竖排 + 繁体古籍识别 | 高（国学采集闭环） | 中-高（排版几何 + 依赖） | ~2.5 人日 |
| 3 | 结果可编辑 + 一键导出 | 中-高（所有结果都受益） | 低（UI 改造） | ~1 人日 |
| — | 配套：版本号 / 日志轮转 / 测试骨架 | — | 低 | ~1 人日 |
| | **合计** | | | **~6.5 人日** |

**建议开发顺序**：3 → 1 → 2（自低风险的"可编辑+导出"打底，再上核心监控，最后做最重的引擎侧排版；每步可独立验证、独立提交）。

---

## 功能 1：锁定区域轮询抓取（监控模式）

### 目标
用户锁定一个预设选区（或临时框选区域）后，程序按固定间隔自动重新截图 + OCR，结果框实时刷新，无需每次手动按键。适用于视频字幕、直播弹幕、歌词等"固定位置、内容滚动"的场景。

### 技术方案
- 新增监控状态机：`_monitor = {"running": False, "rect": None, "last_text": "", "paused": False}`。
- 后台工作线程 `monitor_loop()`：`time.sleep(interval)` → `grab_rect(rect)` 截图 → `ocr_image(img)` 推理 → 与 `last_text` 做差异判断 → 变化则 `PostMessage(WM_MONITOR_UPDATE, text)` 让 UI 线程更新结果框。
- **省 CPU 关键**：每次循环先对截图做像素哈希（DCT/平均哈希），仅当画面变化才跑 OCR；监控间隔默认 1000ms，且必须大于单次推理耗时（实测 RapidOCR CPU 约 200–500ms）。
- 退出/暂停：复用 pynput 的 Esc 监听（`on_activate_esc_close` 扩展——监控中 Esc 先停止监控而非关窗）；托盘菜单增"开始/停止监控""暂停/继续"。

### 改动点（真实函数）
- 新增 `grab_rect(rect)`：基于 `grab_monitor(mon)`（L479）扩展，用 `mss.grab({"mon": m, "left":..,"top":..,"width":..,"height":..})` 截取指定矩形（rect 复用 `region_presets.json` 的屏幕坐标格式）。
- 新增 `start_monitor(rect)` / `stop_monitor()` / `pause_monitor()`。
- `ResultWindow` 新增 `update_text(text)`：仅 `SetWindowText` 编辑框，不重建窗口、不抢焦点（区别于 `show()` L743）。
- `ResultWindow._wndproc`（L637）新增 `WM_MONITOR_UPDATE` 分支派发到 `update_text`。
- `on_activate_esc_close`（L1403）增加监控态判断；`_register_hotkeys` / `build_hotkey_map` 增加 `MONITOR_HOTKEY`（建议默认 `Ctrl+Alt+M`，非 Win 系以避本机占用，走现有冲突检测）。
- 新增跨线程消息常量 `WM_MONITOR_UPDATE = WM_APP + 9`（避开已用的 `WM_APP+8` 日志查看）。

### 验收标准
- 在视频字幕区域启动监控 → 结果框随字幕切换自动刷新，无需手动按键。
- 托盘"暂停/继续""停止"、Esc 停止均生效，停止后恢复常态。
- 选区被遮挡/窗口最小化时不崩溃，自动暂停并在恢复后继续。
- 空闲时 CPU 占用可控（画面静止时近似 0 OCR 调用）。

### 风险 / 依赖
- 多显示器下 rect 坐标空间须与 `mss` 一致（预设存的是屏幕绝对坐标，需验证跨屏正确）。
- 监控中结果框若同时可编辑会与实时刷新冲突 → 监控态下禁用编辑（见功能 3）。

---

## 功能 2：竖排 + 繁体古籍识别（含自动标点）

### 目标
- 支持**竖排**版式的正确阅读顺序（上→下、右→左）。
- 输出可切换 **简体 / 繁体**。
- 可选**自动加标点 + 分段**，直接对接国学古籍采集 pipeline。

### 技术方案
- **竖排重排（纯几何，无需换引擎）**：`ocr_image()`（L1145）返回的 `boxes` 是 4 点多边形。新增 `layout.reorder_vertical(boxes, texts)`：按列 x 中心聚类 → 列间按 x 降序（右→左）→ 列内按 y 升序（上→下），重组文本顺序。RapidOCR 检测竖排框通常仍可用，仅顺序错，几何重排即可纠正。
- **繁体转换**：引入 `opencc-python`（离线），`layout.to_traditional(text)` 用 `s2t.json` 转换；作为可选开关，默认"保留原样"。
- **自动标点**：提供两种模式——(a) 离线规则/轻量模型（保守，仅补逗号句号）；(b) 调用云端 LLM（复用 cloud-service 大模型能力）做断句+标点+分段，质量高但需联网。默认规则模式，LLM 模式可开关。
- **模式开关**：在 `HotkeySettingsDialog`（L1728）增设"排版：横排/竖排""输出：简/繁/保留""自动标点：关/规则/LLM"三组选项，落盘到 `ocr_settings.json`（新文件，结构参照 `hotkeys.json`）。

### 改动点（真实函数）
- 新增模块 `layout.py`：`reorder_vertical()`、`to_traditional()`、`add_punctuation()`。
- `ocr_image(img)`（L1145）返回后，按当前设置依次：竖排→重排、繁体→转换、标点→补全。
- `load_hotkey_config` 体系扩展读取 `ocr_settings.json`（或在现有 config 结构加字段）。
- `HotkeySettingsDialog.build()`（L1780）增加三组控件；`_on_ok`（L1962）保存设置。
- `requirements.txt` 增加 `opencc-python`；`ocrclient.spec` 的 `hiddenimports` 补 `opencc`（避免冻结 exe import 失败）。

### 验收标准
- 竖排样张 → 文本阅读顺序正确（上→下、右→左）。
- 繁体开关开启 → 输出为繁体；关闭 → 保留识别原样。
- 标点开关（规则/LLM）→ 输出含合理标点；关闭 → 纯识别文本。
- 离线模式（规则+OpenCC）在无网时仍可用；LLM 模式在无网时优雅降级并提示。

### 风险 / 依赖
- RapidOCR 对竖排框检测精度有限，极端版式可能漏框 → 几何重排为启发式，需实测样张校准。
- OpenCC 增加包体 ~数 MB；LLM 标点有网络/成本，须强制可选。

---

## 功能 3：结果可编辑 + 一键导出

### 目标
识别结果可在结果框内直接编辑（纠错、润色），并一键导出为 `.txt` / `.md`，方便进 Obsidian / 古籍 pipeline。

### 技术方案
- `ResultWindow.build()`（L586）的编辑框去掉 `ES_READONLY`，改为可编辑；保留现有"复制全部 / 框选复制"（pyperclip）。
- 结果框底部按钮行新增：**复制 / 导出 TXT / 导出 MD**。
- 导出用原生"另存为"对话框（`win32gui` + `GetSaveFileName`），默认路径取 `_app_dir()`（L1444）下的 `exports/`，文件名带时间戳。
- `.md` 导出：将 OCR 按行结构映射为段落（每行一段；多段之间空行）；`.txt` 为纯文本。
- 监控态下编辑框自动只读（见功能 1），避免实时刷新打断输入。

### 改动点（真实函数）
- `ResultWindow.build()`（L586）编辑框样式调整 + 新增按钮控件与回调。
- 新增 `export_result(text, fmt)`：`fmt in {"txt","md"}`，调 `GetSaveFileName` 写文件。
- `ResultWindow` 增加"监控中→只读"标志位联动（与功能 1 的 `update_text` 协调）。

### 验收标准
- 结果框内可自由编辑，复制内容反映编辑结果。
- 导出 TXT / MD 在所选路径生成正确文件；MD 段落结构合理。
- 复制全部 / 框选复制无回归。

### 风险 / 依赖
- 可编辑 EDIT 与监控实时刷新冲突 → 监控态强制只读（已设计规避）。
- 原生 SaveAs 对话框在冻结 exe 下的 COM/样式兼容（参照现有对话框实现，风险低）。

---

## 配套工程项（顺带落地）

| 项 | 做法 | 落点 |
|---|---|---|
| 版本号 | `main.py` 顶部 `__version__ = "2.0.0"`；`_about_text()`（L497）与 `--version` 显示；`ocrclient.spec` 可嵌入 | main.py / spec |
| 日志轮转 | `setup_logging()`（L1456）改 `RotatingFileHandler`（按大小切分，保留 3 份），解决 `ocrclient.log` 无限增长 | main.py |
| 测试骨架 | 抽纯函数 `layout.reorder_vertical` / `to_traditional` / `_crlf` / `_is_cjk` / `_parse_hotkey` 为 pytest 用例，防回归 | 新增 `tests/` |
| 构建验证 | 每里程碑结束 `pyinstaller -y ocrclient.spec` 重建 `dist/OCRClient` 并 `--no-tray` 冒烟 | 沿用现有流程 |

---

## 里程碑与排期（参考，按 ~6.5 人日）

- **M1（第 1 周上半）功能 3 + 版本号 + 测试骨架**
  - 结果可编辑、导出 TXT/MD、可复制。
  - 建立 `tests/`，抽纯函数单测。
  - 重建 + 冒烟。
- **M2（第 1 周下半–第 2 周初）功能 1 锁定区域轮询**
  - `grab_rect` / `monitor_loop` / `ResultWindow.update_text` / 托盘+Esc 控制。
  - 实测字幕场景，校验 CPU 与跨屏坐标。
- **M3（第 2 周）功能 2 竖排+繁体+标点**
  - `layout.py` 三函数、`ocr_settings.json`、设置 UI、OpenCC 依赖与 spec hiddenimports。
  - 竖排/繁体/标点样张验收。
- **收尾**：日志轮转、README 更新（新增功能与快捷键）、`git commit` + tag `v2.0.0`、重建交付 `dist/OCRClient`。

---

## 待确认 / 开放问题
1. "一到三"是否即指上述三个功能（而非第一/二/三节）？如理解有误可调整。
2. 功能 2 的"自动标点"默认走**规则模式（离线）**还是直接接 **LLM（需联网）**？影响依赖与体积。
3. 监控默认热键 `Ctrl+Alt+M` 是否可接受？还是偏好从托盘菜单启动、不设热键？
4. 是否需要在本计划外一并做"日志轮转/自动化测试"（已纳入配套，可剔除或单列）。
