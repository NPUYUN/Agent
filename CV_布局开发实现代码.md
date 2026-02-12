# CV/布局开发模块实现代码

下列代码为 `Standardization_Auditor_Agent/core/layout_analysis.py` 的完整实现版本，可直接替换原文件内容使用。

```python
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
import fitz
import cv2
import numpy as np
import os
import base64
import hashlib
import re
import statistics


class VisualElement(BaseModel):
    type: str
    content: str
    bbox: List[float]
    page_num: int
    region: str
    paper_id: Optional[str] = None
    chunk_id: Optional[str] = None


def _safe_median(values: List[float], default: float = 10.0) -> float:
    if not values:
        return default
    return float(statistics.median(values))


def _open_pdf(content: Any) -> fitz.Document:
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


def _bbox_from_rect(rect: Tuple[float, float, float, float]) -> List[float]:
    return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]


def _extract_text_blocks(page: fitz.Page) -> List[Dict[str, Any]]:
    page_dict = page.get_text("dict")
    return page_dict.get("blocks", [])


def _text_from_line(line: Dict[str, Any]) -> str:
    spans = line.get("spans", [])
    return "".join([s.get("text", "") for s in spans]).strip()


def _max_font_size(line: Dict[str, Any]) -> float:
    spans = line.get("spans", [])
    sizes = [s.get("size", 0) for s in spans if s.get("size") is not None]
    return float(max(sizes)) if sizes else 0.0


def _is_heading(text: str) -> bool:
    if re.match(r"^(\d+(?:\.\d+)*)[.\s、]", text):
        return True
    if re.match(r"^第[一二三四五六七八九十百]+[章节]", text):
        return True
    return False


def _is_caption(text: str) -> bool:
    return re.match(r"^(图|表)\s*\d+", text) is not None


def _find_citations(text: str) -> List[str]:
    matches = []
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        matches.append(m.group(0))
    for m in re.finditer(r"\(([A-Za-z][^)]{0,40}\d{4}[^)]*)\)", text):
        matches.append(m.group(0))
    return matches


def _is_formula_text(text: str) -> bool:
    if re.search(r"[=∑∫√≈≠≤≥]", text):
        return True
    if re.search(r"(（\d+）|\(\d+\))$", text):
        return True
    return False


class PDFParser:
    def __init__(self):
        pass

    async def parse(self, content: Any) -> List[VisualElement]:
        doc = _open_pdf(content)
        elements: List[VisualElement] = []
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_num = page_index + 1
            page_rect = page.rect
            blocks = _extract_text_blocks(page)
            font_sizes = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    size = _max_font_size(line)
                    if size > 0:
                        font_sizes.append(size)
            body_size = _safe_median(font_sizes, default=10.0)
            reference_mode = False
            text_blocks = [b for b in blocks if b.get("type") == 0]
            if not text_blocks:
                elements.append(
                    VisualElement(
                        type="image",
                        content="",
                        bbox=[0.0, 0.0, page_rect.width, page_rect.height],
                        page_num=page_num,
                        region="main",
                    )
                )
                continue
            for block in text_blocks:
                block_bbox = _bbox_from_rect(block.get("bbox", (0, 0, 0, 0)))
                for line in block.get("lines", []):
                    text = _text_from_line(line)
                    if not text:
                        continue
                    line_bbox = _bbox_from_rect(line.get("bbox", block_bbox))
                    max_size = _max_font_size(line)
                    if text.strip() in ["参考文献", "参考文献："]:
                        reference_mode = True
                        elements.append(
                            VisualElement(
                                type="title",
                                content=text,
                                bbox=line_bbox,
                                page_num=page_num,
                                region="reference",
                            )
                        )
                        continue
                    if _is_caption(text):
                        elements.append(
                            VisualElement(
                                type="title",
                                content=text,
                                bbox=line_bbox,
                                page_num=page_num,
                                region="chart",
                            )
                        )
                        continue
                    if _is_formula_text(text):
                        elements.append(
                            VisualElement(
                                type="formula",
                                content=text,
                                bbox=line_bbox,
                                page_num=page_num,
                                region="formula",
                            )
                        )
                        continue
                    citations = _find_citations(text)
                    if citations:
                        for c in citations:
                            elements.append(
                                VisualElement(
                                    type="citation",
                                    content=c,
                                    bbox=line_bbox,
                                    page_num=page_num,
                                    region="citation",
                                )
                            )
                    is_heading = max_size >= body_size * 1.3 or _is_heading(text)
                    if is_heading:
                        elements.append(
                            VisualElement(
                                type="title",
                                content=text,
                                bbox=line_bbox,
                                page_num=page_num,
                                region="title",
                            )
                        )
                        continue
                    region = "reference" if reference_mode else "main"
                    elements.append(
                        VisualElement(
                            type="text",
                            content=text,
                            bbox=line_bbox,
                            page_num=page_num,
                            region=region,
                        )
                    )
            for block in blocks:
                if block.get("type") == 1:
                    image_bbox = _bbox_from_rect(block.get("bbox", (0, 0, 0, 0)))
                    elements.append(
                        VisualElement(
                            type="image",
                            content="",
                            bbox=image_bbox,
                            page_num=page_num,
                            region="chart",
                        )
                    )
        return elements

    def _identify_zones(self, page_obj):
        return None

    def _extract_elements(self, zone_info) -> List[VisualElement]:
        return []


class VisualValidator:
    def __init__(self):
        pass

    async def validate(self, elements: List[VisualElement]) -> Dict[str, Any]:
        issues = []
        issues.extend(self._check_charts(elements))
        issues.extend(self._check_formulas(elements))
        issues.extend(self._check_titles(elements))
        issues.extend(self._check_citations(elements))
        return {"layout_issues": issues}

    def _check_charts(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        captions = [e for e in elements if e.type == "title" and _is_caption(e.content)]
        images = [e for e in elements if e.type == "image"]
        text_refs = [e for e in elements if e.type == "text"]
        caption_nums = set()
        for c in captions:
            m = re.match(r"^(图|表)\s*(\d+)", c.content)
            if m:
                caption_nums.add(m.group(2))
        for t in text_refs:
            for m in re.finditer(r"见(?:图|表)\s*(\d+)", t.content):
                if m.group(1) not in caption_nums:
                    issues.append(
                        {
                            "issue_type": "Label_Missing",
                            "severity": "Warning",
                            "page_num": t.page_num,
                            "bbox": t.bbox,
                            "evidence": t.content,
                            "message": "正文引用的图表编号未在图表标题中找到",
                        }
                    )
        for c in captions:
            same_page_images = [i for i in images if i.page_num == c.page_num]
            if not same_page_images:
                issues.append(
                    {
                        "issue_type": "Label_Missing",
                        "severity": "Warning",
                        "page_num": c.page_num,
                        "bbox": c.bbox,
                        "evidence": c.content,
                        "message": "图表标题未匹配到图像区域",
                    }
                )
                continue
            nearest = min(
                same_page_images,
                key=lambda i: abs(i.bbox[1] - c.bbox[1]),
            )
            if c.content.startswith("图") and c.bbox[1] < nearest.bbox[1]:
                issues.append(
                    {
                        "issue_type": "Label_Missing",
                        "severity": "Warning",
                        "page_num": c.page_num,
                        "bbox": c.bbox,
                        "evidence": c.content,
                        "message": "图标题应位于图下方",
                    }
                )
            if c.content.startswith("表") and c.bbox[1] > nearest.bbox[1]:
                issues.append(
                    {
                        "issue_type": "Label_Missing",
                        "severity": "Warning",
                        "page_num": c.page_num,
                        "bbox": c.bbox,
                        "evidence": c.content,
                        "message": "表标题应位于表上方",
                    }
                )
        return issues

    def _check_formulas(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        formulas = [e for e in elements if e.type == "formula"]
        if not formulas:
            return issues
        page_max_x = {}
        for e in elements:
            page_max_x[e.page_num] = max(page_max_x.get(e.page_num, 0), e.bbox[2])
        text_refs = [e for e in elements if e.type == "text"]
        ref_nums = set()
        for t in text_refs:
            for m in re.finditer(r"(式|公式)\s*(\d+)", t.content):
                ref_nums.add(m.group(2))
        for f in formulas:
            num_match = re.search(r"(（|\\()(\d+)(）|\\))$", f.content)
            if not num_match:
                issues.append(
                    {
                        "issue_type": "Formula_Missing",
                        "severity": "Warning",
                        "page_num": f.page_num,
                        "bbox": f.bbox,
                        "evidence": f.content,
                        "message": "公式未检测到编号",
                    }
                )
                continue
            num = num_match.group(2)
            if num not in ref_nums:
                issues.append(
                    {
                        "issue_type": "Formula_Ref_Missing",
                        "severity": "Info",
                        "page_num": f.page_num,
                        "bbox": f.bbox,
                        "evidence": f.content,
                        "message": "公式编号未在正文引用中出现",
                    }
                )
            max_x = page_max_x.get(f.page_num, f.bbox[2])
            if f.bbox[2] < max_x * 0.85:
                issues.append(
                    {
                        "issue_type": "Formula_Misaligned",
                        "severity": "Warning",
                        "page_num": f.page_num,
                        "bbox": f.bbox,
                        "evidence": f.content,
                        "message": "公式编号疑似未右对齐",
                    }
                )
        return issues

    def _check_titles(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        titles = [e for e in elements if e.type == "title" and e.region == "title"]
        numbered = []
        for t in titles:
            m = re.match(r"^(\d+(?:\.\d+)*)[.\s、]", t.content)
            if not m:
                continue
            parts = [int(x) for x in m.group(1).split(".")]
            numbered.append((t, parts))
        for i in range(1, len(numbered)):
            prev, prev_parts = numbered[i - 1]
            curr, curr_parts = numbered[i]
            if len(curr_parts) > len(prev_parts) + 1:
                issues.append(
                    {
                        "issue_type": "Hierarchy_Fault",
                        "severity": "Warning",
                        "page_num": curr.page_num,
                        "bbox": curr.bbox,
                        "evidence": curr.content,
                        "message": "标题层级跳跃",
                    }
                )
                continue
            if len(curr_parts) == len(prev_parts) and curr_parts[:-1] == prev_parts[:-1]:
                if curr_parts[-1] - prev_parts[-1] > 1:
                    issues.append(
                        {
                            "issue_type": "Hierarchy_Fault",
                            "severity": "Warning",
                            "page_num": curr.page_num,
                            "bbox": curr.bbox,
                            "evidence": curr.content,
                            "message": "标题序号不连续",
                        }
                    )
        return issues

    def _check_citations(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        citations = [e for e in elements if e.type == "citation"]
        references = [e for e in elements if e.region == "reference"]
        ref_nums = set()
        for r in references:
            m = re.match(r"^\\[(\\d+)\\]|^(\\d+)\\.", r.content)
            if m:
                num = m.group(1) or m.group(2)
                if num:
                    ref_nums.add(num)
        for c in citations:
            m = re.search(r"\\[(\\d+)", c.content)
            if m and m.group(1) not in ref_nums:
                issues.append(
                    {
                        "issue_type": "Citation_Visual_Fault",
                        "severity": "Warning",
                        "page_num": c.page_num,
                        "bbox": c.bbox,
                        "evidence": c.content,
                        "message": "引用标注在参考文献区未找到对应条目",
                    }
                )
        return issues


class AnchorGenerator:
    def generate_anchors(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        output = []
        for issue in issues:
            page_num = issue.get("page_num", 0)
            bbox = issue.get("bbox", [0, 0, 0, 0])
            issue_type = issue.get("issue_type", "issue")
            anchor_raw = f"{issue_type}-{page_num}-{bbox}"
            anchor_id = hashlib.md5(anchor_raw.encode("utf-8")).hexdigest()
            issue["anchor_id"] = anchor_id
            issue["highlight"] = bbox
            output.append(issue)
        return output


class LayoutAnalyzer:
    def __init__(self):
        self.parser = PDFParser()
        self.validator = VisualValidator()
        self.anchor_gen = AnchorGenerator()

    async def analyze(self, content: Any) -> Dict[str, Any]:
        elements = await self.parser.parse(content)
        validation_result = await self.validator.validate(elements)
        validation_result["layout_issues"] = self.anchor_gen.generate_anchors(
            validation_result.get("layout_issues", [])
        )
        return {"elements": elements, "layout_result": validation_result}
```
