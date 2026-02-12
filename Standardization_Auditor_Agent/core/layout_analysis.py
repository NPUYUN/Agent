from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
import re
import statistics
from .pdf_utils import open_pdf, extract_blocks, is_encrypted, is_scanned_page, split_columns
from .layout_zones import is_reference_title, classify_line_region, is_caption
from .layout_exceptions import ParseError, ParseReport
from .layout_rules import check_citation_reference_match
from .layout_adapter import with_anchor


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


def _bbox_from_rect(rect: Tuple[float, float, float, float]) -> List[float]:
    return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]


def _text_from_line(line: Dict[str, Any]) -> str:
    spans = line.get("spans", [])
    return "".join([s.get("text", "") for s in spans]).strip()


def _max_font_size(line: Dict[str, Any]) -> float:
    spans = line.get("spans", [])
    sizes = [s.get("size", 0) for s in spans if s.get("size") is not None]
    return float(max(sizes)) if sizes else 0.0


def _find_citations(text: str) -> List[str]:
    matches = []
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        matches.append(m.group(0))
    for m in re.finditer(r"\(([A-Za-z][^)]{0,40}\d{4}[^)]*)\)", text):
        matches.append(m.group(0))
    return matches


class PDFParser:
    def __init__(self):
        pass

    async def parse(self, content: Any) -> Dict[str, Any]:
        parse_errors = []
        parse_report = ParseReport()
        try:
            doc = open_pdf(content)
        except Exception as exc:
            parse_errors.append(ParseError(error_type="invalid_pdf", message=str(exc)).model_dump())
            return {"elements": [], "parse_errors": parse_errors, "parse_report": parse_report.model_dump()}
        if is_encrypted(doc):
            parse_report.encrypted = True
            parse_errors.append(ParseError(error_type="encrypted_pdf", message="pdf is encrypted").model_dump())
            return {"elements": [], "parse_errors": parse_errors, "parse_report": parse_report.model_dump()}
        elements: List[VisualElement] = []
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_num = page_index + 1
            page_rect = page.rect
            if is_scanned_page(page):
                parse_report.scanned_pages += 1
            blocks = extract_blocks(page)
            columns = split_columns(blocks, page_rect.width)
            if len(columns) > 1:
                parse_report.multi_column_pages += 1
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
                    if is_reference_title(text):
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
                    if is_caption(text):
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
                    region = classify_line_region(text, max_size, body_size, reference_mode)
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
                    if region == "formula":
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
                    if region == "title":
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
        return {
            "elements": elements,
            "parse_errors": parse_errors,
            "parse_report": parse_report.model_dump(),
        }

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
            num_match = re.search(r"(（|\()(\d+)(）|\))$", f.content)
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
        citations = [e for e in elements if e.type == "citation"]
        references = [e for e in elements if e.region == "reference"]
        issues = check_citation_reference_match(citations, references)
        return [issue.model_dump() for issue in issues]


class LayoutAnalyzer:
    def __init__(self):
        self.parser = PDFParser()
        self.validator = VisualValidator()

    async def analyze(self, content: Any) -> Dict[str, Any]:
        parse_result = await self.parser.parse(content)
        elements = parse_result.get("elements", [])
        validation_result = await self.validator.validate(elements)
        validation_result["layout_issues"] = with_anchor(validation_result.get("layout_issues", []))
        return {
            "elements": elements,
            "layout_result": validation_result,
            "parse_errors": parse_result.get("parse_errors", []),
            "parse_report": parse_result.get("parse_report", {}),
        }
