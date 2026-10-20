# 开源发布清单（Open Source Release Checklist）

本清单记录把拾字 PickText 发布为公开开源项目所需的全部事项。
**已完成的标记为 `[x]`**，需人工在GitHub / 本机操作的标记为 `[ ]` 并注明原因。

> 目标状态：**免费商用、无署名义务、无 copyleft 传染**，任何人可放心集成到商业产品中。

---

## 一、许可与法律合规

- [x] **选定许可证：MIT-0（MIT No Attribution）**
      理由：法律效果等同 Unlicense / CC0（零义务、可闭源商用、无需署名），
      但保留 MIT 外形，企业法务系统扫描即过，不触发人工审核。
- [x] 生成 [`LICENSE`](LICENSE)（英文原文 + 中文说明，非法律条款以英文为准）
- [x] 生成 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)（依赖许可完整清单）
- [x] 在 `LICENSE` 与 `README` 中说明第三方义务不影响用户对自己代码的支配权
- [x] 确认依赖树**无GPL / AGPL 传染性依赖**

### 依赖许可审计结果

| 检查项 | 结果 |
|---|---|
| GPL / AGPL 依赖 | ✅ 无 |
| LGPL 依赖 | ⚠️ 仅 `pystray`（LGPL-3.0-or-later，见下） |
| 未声明许可的依赖 | ✅ 无（逐包读取安装元数据核实） |
| 内置模型的许可 | ✅ PP-OCR ONNX 模型为 Apache-2.0，可商用 |
| 内嵌字体（再分发风险） | ✅ 无（仅调用本机已装字体，不随包分发） |

**pystray（LGPL-3.0-or-later）—— 已确认不构成约束**，四条理由：

1. LGPL 允许闭源链接，只要求"修改 pystray 本身时才需公开修改部分"
2. 本项目**未修改** pystray 源码，无公开修改的义务
3. **可替换性由生态保证**：通过标准 pip 依赖引入，下游可自行替换/换版本/替换整个托盘模块
4. Python wheel 分发正是 LGPL 设计的适用形态（库随调用方加载）

下游唯一义务：在产品中保留一行告知（如「本软件使用了 pystray (LGPL-3.0)」），
并随分发附带 LGPL v3 与 GPL v3 全文。

## 二、代码层面的开源化改造

- [x] **移除 `pynput`（LGPL-3.0）依赖**
      全项目仅一处使用（`main.py` 监听 Esc），改用 `ctypes` 直调 `user32.dll`
      的 `WH_KEYBOARD_LL` 低级键盘钩子，代码更轻、依赖更少。
      新增 6 个回归测试（结构体布局、指针宽度、按键过滤、异常吞吐、装卸幂等）。
- [x] `vk_to_pynput` → `vk_to_hotkey_str`（移除 pynput 字样）
- [x] `requirements.txt` 移除 `pynput`
- [x] `ocrclient.spec` 移除 `collect_submodules("pynput")`
- [x] 模块 docstring 顶部补充许可声明
- [x] 验证：自测通过、`pytest` **27 passed**（21 → 27）

## 三、去除个人/私有痕迹

- [x] `run.ps1` 移除硬编码的 `C:\Users\microsnow\...` 个人路径，
      改为自动探测 `.venv` / `venv` / `build_venv` / PATH 中的 python
- [x] `README` 快速开始章节去除本机绝对路径，改用 `<venv>` 占位符
- [x] `README` 打包章节去除 WorkBuddy 私有 Python 路径
- [x] `README` 移除「本项目使用 WorkBuddy 管理的隔离 Python」等环境说明
- [x] 扫描源码：无硬编码个人路径、无 API key / token / 密码、无外部 URL
- [x] `.gitignore` 注释去除内部工具名（`.workbuddy/` 条目说明改为通用措辞）
- [x] 内部规划文档 `开发计划-v2.md` → `docs/ROADMAP-v2.md`，并加归档说明
      （含内部人日估算，不宜置于仓库根目录显眼处）

## 四、仓库卫生

- [x] `.gitignore` 补充：`ocr_settings.json`、`exports/`、`selftest_result.txt`、
      `PickText-win64-*.zip`
- [x] `.gitignore` 去重（`*.spec.bak` 原重复两次）
- [x] `README` 文件结构章节同步新增文件、移除运行时文件
- [x] `README` 标注运行时文件（`region_presets.json` / `hotkeys.json` / `ocrclient.log`）不入库
- [x] 编写 [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [x] `README` 新增「开源许可 / 免责声明」章节（权限表 + 免责声明 + 第三方说明）

### 仍需人工确认

- [ ] **确认仓库当前是 Public**（`Settings → General → Danger Zone`）
- [ ] **确认 `PickText-win64-v2.0.0.zip` 未被提交进历史**
      （当前未跟踪，若曾提交过需用 `git filter-repo` 清理历史）
- [ ] 检查 Git 历史中是否有误提交的运行时文件
      `git log --all --diff-filter=A --name-only | grep -E "region_presets|hotkeys|\.log$"`

## 五、GitHub 仓库设置（需人工操作）

- [x] `README.md` 含许可证与免责声明（GitHub 会自动在侧栏显示许可证）
- [ ] `Settings → General → Description` 填一句话简介
- [ ] `Settings → General → Topics` 添加：`ocr`, `windows`, `offline`, `screenshot`,
      `text-recognition`, `rapidocr`, `pystray`, `win32`, `chinese`, `pytorch`
- [ ] 补充 `Issues` 模板（建议问：Windows 版本 / Python 版本 / 运行方式 / 日志）
- [ ] 补充 `Pull request` 模板（建议问：改了什么 / 为什么 / 怎么验证）
- [ ] `Settings → Pages`（可选）：把 `docs/` 或截图做成项目主页
- [ ] 添加仓库 `Topics` 时确认不含内部项目名

## 六、发布前的最终验证

- [ ] 克隆到**干净环境**（全新机器 / 新目录）按 `README` 步骤跑通
      ——这是验证"无个人路径依赖"最直接的方式
- [ ] `pytest tests/ -q` 全绿
- [ ] `python main.py --selftest` 输出 `OK` 且无冲突告警
- [ ] 重新打包（`PyInstaller -y ocrclient.spec`）并人工验证：
      - [ ] Esc 关闭/取消弹窗（**本次改造重点，需真机验证**）
      - [ ] 区域多选识别
      - [ ] 选区预设一键取字
      - [ ] 锁定区域监控
      - [ ] 托盘菜单全部条目
      - [ ] 竖排 / 繁体 / 标点选项
- [ ] 重建 Release zip（旧的 `PickText-win64-v2.0.0.zip` 含 pynput，已过时）
- [ ] 撰写 Release Notes，说明本次的许可变更（LGPL 依赖移除 + MIT-0 开源）

## 七、已知遗留事项

- [ ] **`pystray` 仍是 LGPL**（经评估决定保留）
      若未来希望彻底无copyleft 依赖，需用 `pywin32` 直接调用 `Shell_NotifyIcon`
      自写托盘子系统（约 250~350 行）。当前 LGPL 已被确认不构成商业约束，
      优先级不高，但值得记在案上。
- [ ] 非 Windows 平台完全不支持（依赖 `user32` / `shell32` 全局热键与托盘）。
      如需跨平台，应拆出「OCR 核心层」与「平台适配层」，而非在现有代码里加分支。

---

## 附：许可变更对使用者的影响

| 变更前（未声明许可） | 变更后（MIT-0） |
|---|---|
| GitHub 默认「保留所有权利」，他人**不敢使用** | 可自由使用、修改、商用 |
| 需先联系作者取得授权 | 无需申请，自动生效 |
| 无法确认可否闭源商用 | 明确允许闭源商用 |
| 无第三方依赖说明 | 依赖清单完整披露（含 LGPL 专项说明） |

对使用者而言，这是**从"不可用"变为"无条件可用"**。