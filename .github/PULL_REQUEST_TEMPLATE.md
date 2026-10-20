## 改了什么

<!-- 一句话说清这个 PR 做了什么 -->

## 为什么

<!-- 解决什么问题？关联的 Issue：Fixes #123 -->

## 怎么验证的

<!--
  必填。例如：
  - pytest tests/ -q → 50 passed
  - python main.py --selftest → 五项 [OK]
  - 实机步骤：框选视频字幕条 → 按 Alt+Shift+1 → Toast 提示「已复制 3 行」，Ctrl+V 粘贴正确
-->

```text
（粘贴 pytest 输出）
```

## 检查清单

- [ ] `pytest tests/ -q` 全部通过
- [ ] `python main.py --selftest` 无 `[FAIL]`
- [ ] 新增功能已补单测到 `tests/`
- [ ] 新增的 `WM_APP+n` 消息号已登记到文件顶部 `_CUSTOM_MSGS` 常量区（**不要**在文件中部临时定义）
- [ ] 新增的 `print` 文案只用纯 ASCII 标记成败（`[OK]` / `[FAIL]`），**没有** ✓ ✗ ✅ ❌ 这类符号
- [ ] 一次 PR 只做一件事，没有夹带无关改动
- [ ] 未引入 copyleft（GPL / AGPL）依赖，未引入 GUI 框架或 Web 服务

## 截图（UI 改动必填）

<!-- 改界面的话，贴改前 / 改后 -->
