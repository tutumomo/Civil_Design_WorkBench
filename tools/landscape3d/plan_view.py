# -*- coding: utf-8 -*-
r"""避車彎俯視平面圖：正交相機由上往下，凸顯「車道邊線局部外凸、路緣石隨之退讓」的幾何。

以既有 .blend 載入後只補一顆正交相機並出圖，**不改動任何模型**。

執行（務必先跑過 bay_scene.py 產生 .blend）：
    python tools\blender\blender_runner.py run "tools\landscape3d\plan_view.py" ^
        --blend "out\路旁避車彎_3D\路旁避車彎_3D場景.blend" --timeout 600

注意（踩過的坑，見 docs\3D景觀模擬_作業經驗與踩坑.md）：
1. `--blend` 模式下**不得**呼叫 bpy.ops.wm.read_factory_settings()，否則載入的場景被清空。
2. 結果要機讀，必須在模組層設 `RESULT = {...}` 與 `ARTIFACTS.append(...)`；
   只 `print("RESULT:", ...)` 的話 runner 回傳的 result 會是 null，只能翻 log。
3. 重跑前先刪同名相機，否則會累積 CAM_俯視平面.001 ...
"""
import os
import sys

import bpy

# ------------------------------------------------------------ 輸出路徑
_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from project_paths import out_dir  # noqa: E402

OUT = os.environ.get("BAY_OUT") or str(out_dir("路旁避車彎_3D"))
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------ 前置檢查（防呆）
scene = bpy.context.scene
_n_obj = len(bpy.data.objects)
if _n_obj == 0:
    raise RuntimeError(
        "載入的場景是空的（%d 個物件）。請確認有帶 --blend，且腳本沒有呼叫 read_factory_settings()。" % _n_obj)
print("載入場景物件數 =", _n_obj)

# ------------------------------------------------------------ 正交相機
CAM_NAME = "CAM_俯視平面"
for _old in [o for o in bpy.data.objects if o.name == CAM_NAME or o.name.startswith(CAM_NAME + ".")]:
    bpy.data.objects.remove(_old, do_unlink=True)   # 重跑冪等

cam_data = bpy.data.cameras.new(CAM_NAME)
cam_data.type = 'ORTHO'
cam_data.ortho_scale = float(os.environ.get("BAY_ORTHO", 18.0))  # 水平涵蓋 18 m（避車彎 -3 ~ 12 m 全段漸變）
cam_data.clip_start = 0.10
cam_data.clip_end = 200.0
cam = bpy.data.objects.new(CAM_NAME, cam_data)
scene.collection.objects.link(cam)
cam.location = (4.60, 1.90, 30.0)
cam.rotation_euler = (0.0, 0.0, 0.0)   # 預設 -Z 朝下 → 螢幕上 = +Y（往坡側）、右 = +X（往里程增加）
scene.camera = cam

# ------------------------------------------------------------ 渲染設定
scene.render.resolution_x = 1600
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
try:
    scene.cycles.samples = 96
    scene.cycles.time_limit = 220.0
    scene.cycles.use_denoising = True
    scene.cycles.adaptive_threshold = 0.015
    scene.render.use_persistent_data = True
except Exception as exc:
    print("cycles 參數略過：", exc)

path = os.path.join(OUT, "路旁避車彎_3D_俯視平面.png")
scene.render.filepath = path
bpy.ops.render.render(write_still=True)

# ------------------------------------------------------------ 機讀結果
ARTIFACTS = [path] if os.path.exists(path) else []
RESULT = {
    "path": path,
    "bytes": os.path.getsize(path) if os.path.exists(path) else -1,
    "ortho_scale": cam_data.ortho_scale,
    "cam_loc": [round(v, 3) for v in cam.location],
    "objects_in_scene": _n_obj,
}
print("RESULT:", RESULT)
