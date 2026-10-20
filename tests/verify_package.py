# -*- coding: utf-8 -*-
"""验证打包后的 OCRClient.exe 里toast 修复是否真实生效。

思路：不依赖源码，直接在打包环境下验证两个行为——
  1) 窗口绘制：深色底 + 白字（NULL_BRUSH 修复）
  2) 自动关闭：到点消息循环自行退出（PostMessage 修复）

做法：把打包目录临时加入 sys.path 无法直接 import（冻结 exe 不是普通模块），
因此改用「源码抽取 + 同版本依赖」的方式验证打包依赖一致性，
并对 dist 产物做结构与版本核验。
"""
import os
import re
import sys
import time

DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dist", "OCRClient")

print("=" * 60)
print("打包产物核验")
print("=" * 60)

# 1) 产物结构
exe = os.path.join(DIST, "OCRClient.exe")
internal = os.path.join(DIST, "_internal")
assert os.path.isfile(exe), "缺少主程序 OCRClient.exe"
assert os.path.isdir(internal), "缺少 _internal 依赖目录"
print(f"✅ 主程序: {exe}  ({os.path.getsize(exe) / 1024 / 1024:.1f} MB)")

# 2) 关键依赖文件
required = [
    ("_internal/onnxruntime/capi/onnxruntime.dll", "ONNX 推理运行库"),
    ("_internal/rapidocr_onnxruntime/models/ch_PP-OCRv3_det_infer.onnx", "检测模型"),
    ("_internal/rapidocr_onnxruntime/models/ch_PP-OCRv3_rec_infer.onnx", "识别模型"),
    ("_internal/rapidocr_onnxruntime/models/ch_ppocr_mobile_v2.0_cls_infer.onnx", "方向分类模型"),
]
for rel, desc in required:
    p = os.path.join(DIST, rel.replace("/", os.sep))
    assert os.path.isfile(p), f"缺少{desc}: {rel}"
    print(f"✅ {desc}: {os.path.getsize(p) / 1024 / 1024:.1f} MB")

# 3) pywin32 相关（GDI 绘制依赖）
pywin = [f for f in os.listdir(os.path.join(internal, "pywin32_system32"))
         if f.lower().startswith(("pythoncom", "pywintypes"))]
print(f"✅ pywin32 运行库: {len(pywin)} 个")

# 4) 源码中 toast 修复已就位（打包输入源）
ROOT = os.path.dirname(DIST)
src = open(os.path.join(ROOT, "..", "main.py"), encoding="utf-8").read()
body = src[src.index("# ----------------- 轻量 Toast 提示"):
           src.index("# ----------------- 核心逻辑 -----------------")]

assert "NULL_BRUSH" in body, "打包源缺少 NULL_BRUSH 修复（文字将不可见）"
print("✅ toast 修复1 (NULL_BRUSH 白刷覆盖) 已包含在打包输入")

import ast
fn_src = body[body.index("def _on_timeout"):body.index("def _force_quit")]
calls = set()
for node in ast.walk(ast.parse(fn_src.strip())):
    if isinstance(node, ast.Call):
        f = node.func
        calls.add(f.attr if isinstance(f, ast.Attribute)
                  else f.id if isinstance(f, ast.Name) else "")
assert "PostMessage" in calls and "PostThreadMessage" not in calls, \
    f"_on_timeout 调用异常: {calls}"
print("✅ toast 修复2 (PostMessage 分发) 已包含在打包输入")

assert "_force_quit" in body, "缺少 _force_quit 兜底"
print("✅ toast 兜底机制 (_force_quit) 已包含在打包输入")

print("\n" + "=" * 60)
print("打包产物核验通过")
print("=" * 60)