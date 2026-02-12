# CV/布局开发其它模块实现代码

以下为除 `core/layout_analysis.py` 之外的模块实现代码，按现有项目结构拆分为可直接落地的文件内容。

## 1) core/layout_schema.py
```python
from typing import List, Optional
from pydantic import BaseModel


class LayoutIssue(BaseModel):
    issue_type: str
    severity: str
    page_num: int
    bbox: List[float]
    evidence: Optional[str] = None
    message: Optional[str] = None
    anchor_id: Optional[str] = None
    highlight: Optional[List[float]] = None


class Anchor(BaseModel):
    anchor_id: str
    page_num: int
    bbox: List[float]
    highlight: List[float]
```

## 2) core/pdf_utils.py
```python
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
    return page.get_text("dict").get("blocks", [])


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
```

## 3) core/vision_utils.py
```python
from typing import List, Tuple
import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15)


def find_contours(binary: np.ndarray) -> List[np.ndarray]:
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def contour_bboxes(contours: List[np.ndarray], min_area: int = 200) -> List[Tuple[int, int, int, int]]:
    bboxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h >= min_area:
            bboxes.append((x, y, x + w, y + h))
    return bboxes


def detect_text_lines(gray: np.ndarray) -> List[Tuple[int, int, int, int]]:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    morph = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    _, th = cv2.threshold(morph, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours = find_contours(th)
    return contour_bboxes(contours, min_area=300)
```

## 4) core/layout_adapter.py
```python
from typing import Dict, Any, List
import hashlib
from .layout_schema import LayoutIssue


def with_anchor(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output = []
    for issue in issues:
        page_num = issue.get("page_num", 0)
        bbox = issue.get("bbox", [0, 0, 0, 0])
        issue_type = issue.get("issue_type", "issue")
        raw = f"{issue_type}-{page_num}-{bbox}"
        anchor_id = hashlib.md5(raw.encode("utf-8")).hexdigest()
        issue["anchor_id"] = anchor_id
        issue["highlight"] = bbox
        output.append(issue)
    return output


def normalize_issues(raw_issues: List[Dict[str, Any]]) -> List[LayoutIssue]:
    return [LayoutIssue(**i) for i in raw_issues]
```

## 5) core/layout_rules.py
```python
from typing import List
import re
from .layout_schema import LayoutIssue
from .layout_analysis import VisualElement


def check_citation_reference_match(citations: List[VisualElement], references: List[VisualElement]) -> List[LayoutIssue]:
    ref_nums = set()
    for r in references:
        m = re.match(r"^\\[(\\d+)\\]|^(\\d+)\\.", r.content)
        if m:
            num = m.group(1) or m.group(2)
            if num:
                ref_nums.add(num)
    issues: List[LayoutIssue] = []
    for c in citations:
        m = re.search(r"\\[(\\d+)", c.content)
        if m and m.group(1) not in ref_nums:
            issues.append(
                LayoutIssue(
                    issue_type="Citation_Visual_Fault",
                    severity="Warning",
                    page_num=c.page_num,
                    bbox=c.bbox,
                    evidence=c.content,
                    message="引用标注在参考文献区未找到对应条目",
                )
            )
    return issues
```

## 6) core/layout_perf.py
```python
from typing import Dict, Any
import time


class PerfTimer:
    def __init__(self):
        self.records: Dict[str, int] = {}

    def measure(self, key: str, start: float, end: float):
        self.records[key] = int((end - start) * 1000)

    def total(self) -> int:
        return sum(self.records.values())


def timing_guard(fn, *args, **kwargs) -> Dict[str, Any]:
    start = time.time()
    result = fn(*args, **kwargs)
    end = time.time()
    return {"result": result, "latency_ms": int((end - start) * 1000)}
```
