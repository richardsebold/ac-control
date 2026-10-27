"""Gera models/yolo11n.onnx a partir dos pesos oficiais da Ultralytics.

Rode num venv separado (precisa de `pip install ultralytics onnx onnxslim`, que traz o torch); o app em si
só usa onnxruntime. Uso: python gen_model.py
"""
import shutil
import tempfile
from pathlib import Path

from ultralytics import YOLO

DEST = Path(__file__).parent / "models" / "yolo11n.onnx"

with tempfile.TemporaryDirectory() as tmp:
    pt = Path(tmp) / "yolo11n.pt"
    out = YOLO(str(pt)).export(format="onnx", imgsz=640, simplify=True)
    DEST.parent.mkdir(exist_ok=True)
    shutil.copy(out, DEST)
print("modelo salvo em", DEST)
