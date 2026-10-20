# 第三方许可声明（THIRD_PARTY NOTICES）

拾字 PickText 自身代码适用 [MIT-0 许可证](LICENSE)（无需署名、可闭源商用）。

但本项目运行时依赖若干第三方库。**这些库各自适用其原始许可证，与本项目的 MIT-0 无关**——
本项目无法、也不打算改变它们的条款。下游使用者在再分发本项目或其衍生作品时，
请一并遵守下表所列义务。

本清单依据 v2.0.0 实际锁定的依赖版本整理（取自 `requirements.txt` 与构建环境元数据）。

---

## 一、运行时依赖（`requirements.txt`，随程序分发）

| 库 | 版本 | 许可证 | 再分发义务 | 是否允许闭源商用 |
|---|---|---|---|---|
| [mss](https://github.com/boboblox/...) | 10.2.0 | MIT | 保留版权声明 | ✅ 允许 |
| [rapidocr-onnxruntime](https://github.com/RapidAI/RapidOCR) | 1.2.3 | Apache-2.0 | 保留版权声明与 NOTICE | ✅ 允许 |
| [OpenCC](https://github.com/BYVoid/OpenCC) | 1.4.2 | Apache-2.0 | 保留版权声明与 NOTICE | ✅ 允许 |
| [opencv-python](https://github.com/opencv/opencv-python) | 5.0.0.93 | Apache-2.0 | 保留版权声明与 NOTICE | ✅ 允许 |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | 1.30.0 | MIT | 保留版权声明 | ✅ 允许 |
| [numpy](https://github.com/numpy/numpy) | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 保留版权声明 | ✅ 允许 |
| [pyperclip](https://github.com/asweigart/pyperclip) | 1.11.0 | BSD-3-Clause | 保留版权声明 | ✅ 允许 |
| [pywin32](https://github.com/mhammond/pywin32) | 312 | PSF-like | 保留版权声明 | ✅ 允许 |
| [pywin32-ctypes](https://github.com/zochow/pywin32-ctypes) | 0.2.3 | BSD-3-Clause | 保留版权声明 | ✅ 允许 |
| [Pillow](https://github.com/python-pillow/Pillow) | 12.3.0 | MIT-CMU | 保留版权声明 | ✅ 允许 |
| [protobuf](https://github.com/protocolbuffers/protobuf) | 7.36.2 | BSD-3-Clause | 保留版权声明 | ✅ 允许 |
| [shapely](https://github.com/shapely/shapely) | 2.2.0 | BSD-3-Clause | 保留版权声明 | ✅ 允许 |
| [PyYAML](https://github.com/yaml/pyyaml) | 6.0.3 | MIT | 保留版权声明 | ✅ 允许 |
| [flatbuffers](https://github.com/google/flatbuffers) | 25.12.19 | Apache-2.0 | 保留版权声明与 NOTICE | ✅ 允许 |
| [pyclipper](https://github.com/samhocevar/pyclipper) | 1.4.0 | MIT | 保留版权声明 | ✅ 允许 |
| [six](https://github.com/benjaminp/six) | 1.17.0 | MIT | 保留版权声明 | ✅ 允许 |
| **pystray** | 0.19.5 | **LGPL-3.0-or-later** | 见下方专项说明 | ✅ 允许 |

> 上述依赖**均允许闭源商业集成**，无 copyleft 传染风险（pystray 的 LGPL 专项说明见下）。

## 二、LGPL 依赖专项说明

本项目依赖 [pystray](https://github.com/mhammond/pystray) 实现 Windows 系统托盘图标
（LGPL-3.0-or-later）。这是本项目依赖树中唯一的 copyleft 组件，使用方式与影响如下：

**为什么可以放心用于闭源商业产品**

1. **LGPL 允许闭源链接**。LGPL 的 copyleft 只要求"修改 pystray 本身时必须开源"，
   不要求使用它的作品开源。你的业务代码仍完全受MIT-0 支配，可闭源、可收费分发。
2. **未修改 pystray**。本项目按原样使用 pystray，未打任何补丁，因此无"必须公开
   修改后源码"的义务。
3. **可替换性已由生态保证**。LGPL 要求用户能够替换该库。本项目通过标准 Python
   依赖机制（`pip install -r requirements.txt`）引入 pystray；下游可以自行
   `pip install` 不同版本、用补丁版本替换、或在等价实现（如直接调用
   `Shell_NotifyIcon`）存在时替换整个托盘模块。你的源码不以任何方式绑定
   pystray 的内部实现。
4. **Python 导入即动态链接**。LGPL 的设计意图正是覆盖"库被单独分发、随调用方
   加载"这一形态；pip 安装的 wheel 属标准分发渠道，条件天然满足。

**你实际需要做的**

- 在你的产品中**保留一条告知**：本软件使用了 pystray（LGPL-3.0-or-later）。
  最简做法是在"关于/开源许可"页面列一行。
- **随分发附带 LGPL v3 与 GPL v3 全文**（多数情况下，Apache-2.0 类依赖也已
  要求附带 NOTICE，可一并满足）。
- 若你**修改了 pystray 源码**，则必须公开你的修改部分，并允许用户替换回原版。

## 三、构建期依赖（不随程序分发）

以下仅用于开发与打包，不会进入最终产物，但遵循各自的许可证：

| 库 | 版本 | 许可证 | 说明 |
|---|---|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | 6.22.3 | GPL-2.0-or-later **附例外条款** | 其例外条款明确允许用它打包并分发商业闭源程序，**不构成本项目的开源义务** |
| [pytest](https://github.com/pytest-dev/pytest) | 9.1.1 | MIT | 仅测试 |
| [pluggy](https://github.com/pytest-dev/pluggy) | 1.6.0 | MIT | 仅测试 |
| [iniconfig](https://github.com/pytest-dev/iniconfig) | 2.3.1 | MIT | 仅测试 |
| [packaging](https://github.com/pypa/packaging) | 26.3 | Apache-2.0 OR BSD-2-Clause | 工具链 |
| [Pygments](https://github.com/pygments/pygments) | 2.21.0 | BSD-2-Clause | 工具链 |
| [pyinstaller-hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib) | — | Apache-2.0 | 打包辅助 |
| [pefile](https://github.com/erocarrera/pefile) | 2024.8.26 | MIT | 打包辅助 |
| [altgraph](https://github.com/ronaldoussoren/altgraph) | 0.17.5 | MIT | 打包辅助 |

> **PyInstaller 说明**：它本身是 GPL，但附带一条广为人知的例外条款——明确授权
> 将 PyInstaller 用于打包并分发非自由（包括商业闭源）程序。因此使用它打包本项目
> **不会**使你的产品承担 GPL 义务。这是打包 Python 桌面软件的通行做法。

---

## 四、OCR 模型权重

本项目内置 [RapidOCR](https://github.com/RapidAI/RapidOCR) 的三个 ONNX 模型
（PP-OCR 检测/识别/方向分类）。这些模型源自百度飞桨 PaddleOCR 团队发布的
PaddleOCR 模型，遵循 **Apache-2.0** 许可，可自由商用。

> 模型权重与 RapidOCR 框架代码均为 Apache-2.0，同样允许闭源商业集成。

## 五、字体

托盘图标在运行时使用系统字体渲染 "拾字" 二字（如需指定字体，会优先选用 Windows
自带的微软雅黑 `msyh.ttc`）。**系统字体不在分发物中**，仅调用本机已安装的字体文件，
不构成字体再分发。项目中无内嵌字体文件。

## 六、如何自行复核

本清单不是法律意见。如需确认某个版本的准确条款：

```bash
pip show <包名>                      # 查看版本
pip show -f <包名>                   # 查看随包分发的许可文件
# 或直接读取安装元数据
python -c "import importlib.metadata as m; print(m.metadata('<包名>').get('License'))"
```

各许可证全文：

- MIT-0 · MIT · BSD · Zlib · PSF：随各库源码分发，详见其仓库
- Apache-2.0：<https://www.apache.org/licenses/LICENSE-2.0>
- LGPL-3.0：<https://www.gnu.org/licenses/lgpl-3.0.html>
- GPL-3.0：<https://www.gnu.org/licenses/gpl-3.0.html>（LGPL v3 是它的补充条款）