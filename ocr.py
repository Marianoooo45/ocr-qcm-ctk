from __future__ import annotations
import io
import os
from typing import Tuple
from PIL import Image
import mss
import pytesseract

def set_tesseract_cmd(path: str):
    if path:
        pytesseract.pytesseract.tesseract_cmd = path

def grab_image(left: int, top: int, width: int, height: int) -> Image.Image:
    with mss.mss() as sct:
        bbox = {"left": left, "top": top, "width": width, "height": height}
        shot = sct.grab(bbox)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        return img

def ocr_image(img: Image.Image, lang: str = "fra", oem: str = "3", psm: str = "6") -> str:
    cfg = f"--oem {oem} --psm {psm}"
    return pytesseract.image_to_string(img, lang=lang, config=cfg)
