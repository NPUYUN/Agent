from typing import Any, Dict, List, Tuple
import base64
import os
import fitz
import numpy as np


def open_pdf(content: Any) -> fitz.Document:
    if isinstance(content, (bytes, bytearray)):
        return fitz.open(stream=content, filetype="pdf")
    if isinstance(content, str):
        if os.path.exists(content):
            return fitz.open(content)
        try:
            decoded = base64.b64decode(content, validate=True)
            if b"%PDF" in decoded[:1024]:
                return fitz.open(stream=decoded, filetype="pdf")
        except Exception:
            pass
    raise ValueError("invalid pdf content")


def is_encrypted(doc: fitz.Document) -> bool:
    return bool(getattr(doc, "is_encrypted", False))


def is_scanned_page(page: fitz.Page) -> bool:
    text = page.get_text("text").strip()
    return len(text) < 10


def page_to_image(page: fitz.Page, zoom: float = 2.0) -> np.ndarray:
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return img


def extract_blocks(page: fitz.Page) -> List[Dict[str, Any]]:
    try:
        return page.get_text("dict").get("blocks", [])
    except Exception:
        blocks = page.get_text("blocks")
        output: List[Dict[str, Any]] = []
        for b in blocks or []:
            if not b or len(b) < 5:
                continue
            x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
            text = b[4] if len(b) > 4 else ""
            block_type = b[6] if len(b) > 6 else 0
            if block_type == 0:
                lines = []
                for line_text in str(text or "").splitlines():
                    lt = line_text.strip()
                    if not lt:
                        continue
                    lines.append(
                        {
                            "bbox": (x0, y0, x1, y1),
                            "spans": [{"text": lt, "size": 0}],
                        }
                    )
                output.append({"type": 0, "bbox": (x0, y0, x1, y1), "lines": lines})
            else:
                output.append({"type": 1, "bbox": (x0, y0, x1, y1)})
        return output


def split_columns(blocks: List[Dict[str, Any]], page_width: float) -> List[List[Dict[str, Any]]]:
    text_blocks = [b for b in blocks if b.get("type") == 0]
    if not text_blocks:
        return []
    xs = [b.get("bbox", [0, 0, 0, 0])[0] for b in text_blocks]
    if not xs:
        return [text_blocks]
    mid = page_width * 0.5
    left = [b for b in text_blocks if b.get("bbox", [0, 0, 0, 0])[0] < mid]
    right = [b for b in text_blocks if b.get("bbox", [0, 0, 0, 0])[0] >= mid]
    if not left or not right:
        return [text_blocks]
    return [left, right]


def normalize_bbox(bbox: List[float], page_width: float, page_height: float) -> List[float]:
    x0, y0, x1, y1 = bbox
    return [x0 / page_width, y0 / page_height, x1 / page_width, y1 / page_height]
