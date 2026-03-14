from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
import asyncio
import re
import statistics
from .pdf_utils import open_pdf, extract_blocks, is_encrypted, is_scanned_page, split_columns, page_to_image
from .layout_zones import is_reference_title, classify_line_region, is_caption, is_heading_text
from .layout_exceptions import ParseError, ParseReport
from .layout_rules import check_citation_reference_match, load_rules
from .layout_adapter import with_anchor
from .vision_utils import detect_text_lines, to_gray


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


def _sort_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(blocks, key=lambda b: (b.get("bbox", [0, 0, 0, 0])[1], b.get("bbox", [0, 0, 0, 0])[0]))


def _text_from_line(line: Dict[str, Any]) -> str:
    spans = line.get("spans", [])
    return "".join([s.get("text", "") for s in spans]).strip()


def _max_font_size(line: Dict[str, Any]) -> float:
    spans = line.get("spans", [])
    sizes = [s.get("size", 0) for s in spans if s.get("size") is not None]
    return float(max(sizes)) if sizes else 0.0


def _find_citations(text: str) -> List[str]:
    matches = []
    t = text or ""
    code_like = bool(
        re.search(
            r"(?:\w+\s*:=|\breturn\b|\bfor\b|\bwhile\b|\bif\b|==|!=|->|=>|;|\{|\}|\w+\[[^\]]+\]|\w+\s*=\s*\w+\s*\()",
            t,
        )
    )
    if not code_like:
        for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", t):
            nums = [int(x) for x in re.findall(r"\d+", m.group(1) or "") if x.isdigit()]
            if nums and any(n == 0 for n in nums):
                continue
            matches.append(m.group(0))
    for m in re.finditer(r"\(([A-Za-z][^)]{0,40}\d{4}[^)]*)\)", text):
        matches.append(m.group(0))
    return matches


class PDFParser:
    def __init__(self):
        pass

    async def parse(self, content: Any) -> Dict[str, Any]:
        return await asyncio.to_thread(self._parse_sync, content)

    def _parse_sync(self, content: Any) -> Dict[str, Any]:
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
        reference_mode_global = False
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_num = page_index + 1
            page_rect = page.rect
            scanned = is_scanned_page(page)
            if scanned:
                parse_report.scanned_pages += 1
            blocks = extract_blocks(page)
            columns = split_columns(blocks, page_rect.width)
            if len(columns) > 1:
                parse_report.multi_column_pages += 1

            # CV Analysis Integration
            visual_lines = []
            if scanned:
                try:
                    img = page_to_image(page)
                    gray = to_gray(img)
                    visual_lines = detect_text_lines(gray)
                    parse_report.visual_elements_count += len(visual_lines)
                except Exception:
                    pass

            font_sizes = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    size = _max_font_size(line)
                    if size > 0:
                        font_sizes.append(size)
            body_size = _safe_median(font_sizes, default=10.0)
            reference_mode = reference_mode_global
            if columns:
                if len(columns) > 1:
                    text_blocks = _sort_blocks(columns[0]) + _sort_blocks(columns[1])
                else:
                    text_blocks = _sort_blocks(columns[0])
            else:
                text_blocks = _sort_blocks([b for b in blocks if b.get("type") == 0])
            if not text_blocks:
                # Use CV to check for scanned content
                if visual_lines and len(visual_lines) > 5:
                    elements.append(
                        VisualElement(
                            type="scanned_content",
                            content="[SCANNED_CONTENT_DETECTED]",
                            bbox=[0.0, 0.0, 1.0, 1.0],
                            page_num=page_num,
                            region="main",
                        )
                    )
                else:
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
                        reference_mode_global = True
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
        self.rules = {}

    def update_rules(self, rules: Dict[str, Any]):
        self.rules = rules

    async def validate(self, elements: List[VisualElement]) -> Dict[str, Any]:
        return await asyncio.to_thread(self._validate_sync, elements)

    def _validate_sync(self, elements: List[VisualElement]) -> Dict[str, Any]:
        issues = []
        issues.extend(self._check_charts(elements))
        issues.extend(self._check_formulas(elements))
        issues.extend(self._check_titles(elements))
        issues.extend(self._check_citations(elements))
        return {"layout_issues": issues}

    def _check_charts(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        rule_config = self.rules.get("figure_table_check", {})
        fig_caption_pos = rule_config.get("caption_requirement", "bottom")
        table_caption_pos = rule_config.get("table_caption_requirement", "top")

        # Collect captions from both 'chart' type elements and 'title' elements that look like captions
        captions = [e for e in elements if (e.type == "chart") or (e.type == "title" and is_caption(e.content))]
        images = [e for e in elements if e.type == "image"]
        text_refs = [e for e in elements if e.type == "text"]
        caption_nums = set()
        for c in captions:
            m = re.match(r"^(图|表)\s*(\d+(?:[.-]\d+)*)", c.content)
            if m:
                caption_nums.add(m.group(2))
        for t in text_refs:
            for m in re.finditer(r"见(?:图|表)\s*(\d+(?:[.-]\d+)*)", t.content):
                if m.group(1) not in caption_nums:
                    issues.append(
                        {
                            "issue_type": "Label_Missing",
                            "severity": "Info",
                            "page_num": t.page_num,
                            "bbox": t.bbox,
                            "evidence": t.content,
                            "message": "正文引用的图表编号未在图表标题中找到",
                            "location": {"page": t.page_num, "bbox": t.bbox}
                        }
                    )
        for c in captions:
            # Skip check for Tables if they are not represented as images
            is_figure = bool(re.match(r"^(图|Figure|Fig\.)", c.content, re.IGNORECASE))
            is_table = bool(re.match(r"^(表|Table)", c.content, re.IGNORECASE))
            
            same_page_images = [i for i in images if i.page_num == c.page_num]
            
            # For figures, we expect an image nearby.
            if is_figure:
                # Disabled image check because PyMuPDF often misses vector graphics (drawings),
                # leading to false positives "Image not found".
                if not same_page_images:
                    continue
                
                nearest = min(
                    same_page_images,
                    key=lambda i: abs(i.bbox[1] - c.bbox[1]),
                )
                
                # Check distance: If nearest image is too far (e.g., > 1/3 page height), 
                # assume the actual image was not detected (Info) instead of Warning about position.
                # Estimate page height from max y on page (default A4 height ~842)
                page_elements = [e for e in elements if e.page_num == c.page_num]
                max_y = max((e.bbox[3] for e in page_elements), default=842.0)
                
                if abs(nearest.bbox[1] - c.bbox[1]) > max_y * 0.33:
                    # Skip reporting if too far, assuming unrelated image
                    continue
                
                overlap = min(c.bbox[2], nearest.bbox[2]) - max(c.bbox[0], nearest.bbox[0])
                c_w = max(0.0, c.bbox[2] - c.bbox[0])
                i_w = max(0.0, nearest.bbox[2] - nearest.bbox[0])
                min_w = min(c_w, i_w) if min(c_w, i_w) > 0 else 1.0
                if overlap < min_w * 0.25:
                    continue

                # Check position (Bottom) with tolerance
                # Tolerance allows for slight overlaps or bounding box inaccuracies
                tolerance = 5.0
                if fig_caption_pos == "bottom" and c.bbox[1] < nearest.bbox[1] - tolerance:
                     issues.append({
                        "issue_type": "Label_Missing",
                        "severity": "Info",
                        "page_num": c.page_num,
                        "bbox": c.bbox,
                        "evidence": c.content,
                        "message": f"图标题应位于图下方 (规则要求: {fig_caption_pos})",
                        "location": {"page": c.page_num, "bbox": c.bbox}
                    })
                elif fig_caption_pos == "top" and c.bbox[1] > nearest.bbox[1] + tolerance:
                     issues.append({
                        "issue_type": "Label_Missing",
                        "severity": "Info",
                        "page_num": c.page_num,
                        "bbox": c.bbox,
                        "evidence": c.content,
                        "message": f"图标题应位于图上方 (规则要求: {fig_caption_pos})",
                        "location": {"page": c.page_num, "bbox": c.bbox}
                    })

            # For tables, we usually don't have "image" objects for them, so we skip image matching.
            # Only check position if we can identify table body (not implemented yet), so just skip Label_Missing for tables.
            if is_table:
                pass # TODO: Implement table body detection for position check
        return issues

    def _check_formulas(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        rule_config = self.rules.get("formula_check", {})
        numbering_pos = rule_config.get("numbering", "right")
        require_numbering = bool(rule_config.get("require_numbering", False))
        check_reference = bool(rule_config.get("check_reference", False))

        def _is_display_formula(text: str) -> bool:
            s = (text or "").strip()
            if not s:
                return False
            if re.search(r"(（|\()(\d+(?:[.-]\d+)*)(）|\))\s*$", s):
                return True
            # Exclude likely code patterns
            if re.search(r"(\[\]|\{\}|return\s|def\s|class\s|import\s|print\()", s):
                return False
            if re.search(r"[=<>≤≥±×÷*/+\-≈≠]\s*$", s):
                return False
            if re.fullmatch(r"[A-Za-zα-ωΑ-Ω]\w{0,2}", s):
                return False
            if re.fullmatch(r"[∑∫√α-ωΑ-Ω∂∇∞≈≠≤≥±×÷]", s):
                return False
            if len(s) <= 4 and not re.search(r"[=<>≤≥±×÷*/+\-≈≠]", s):
                return False
            if re.search(r"[=<>≤≥±×÷*/+\-≈≠]", s):
                return True
            if len(s) >= 12 and re.search(r"[\dA-Za-zα-ωΑ-Ω]", s):
                return True
            return False

        formulas = [e for e in elements if e.type == "formula" and _is_display_formula(e.content)]
        if not formulas:
            return issues
        page_max_x = {}
        for e in elements:
            page_max_x[e.page_num] = max(page_max_x.get(e.page_num, 0), e.bbox[2])
        text_refs = [e for e in elements if e.type == "text"]
        ref_nums = set()
        for t in text_refs:
            for m in re.finditer(r"(?:式|公式)\s*(?:（|\()?\s*(\d+(?:[.-]\d+)*)\s*(?:）|\))?", t.content):
                ref_nums.add(m.group(1))
            for m in re.finditer(r"(?:Eq\.?|Equation)\s*(?:\(|（)?\s*(\d+(?:[.-]\d+)*)\s*(?:\)|）)?", t.content, flags=re.IGNORECASE):
                ref_nums.add(m.group(1))
        num_only_pat = re.compile(r"^\s*(?:（|\()(\d+(?:[.-]\d+)*)(?:）|\))\s*$")
        page_num_only = {}
        for e in elements:
            if e.type not in {"text", "title", "formula"}:
                continue
            m = num_only_pat.match(e.content or "")
            if not m:
                continue
            page_num_only.setdefault(e.page_num, []).append((e, m.group(1)))
        for f in formulas:
            num = None
            num_bbox: Optional[List[float]] = None
            m_end = re.search(r"(（|\()(\d+(?:[.-]\d+)*)(）|\))\s*$", f.content)
            if m_end:
                num = m_end.group(2)
                num_bbox = f.bbox
            else:
                # Fallback: check if the number is at the beginning (left-aligned case) or just separated
                # Some PDFs might have "(1) formula" or "formula (1)"
                # But here we stick to the end for standard cases, but relax regex
                candidates = page_num_only.get(f.page_num, [])
                if candidates:
                    fcy = (f.bbox[1] + f.bbox[3]) / 2.0
                    fh = max(1.0, f.bbox[3] - f.bbox[1])
                    max_x = page_max_x.get(f.page_num, f.bbox[2])
                    best = None
                    best_bbox = None
                    best_score = None
                    for e, num in candidates:
                        ecy = (e.bbox[1] + e.bbox[3]) / 2.0
                        if abs(ecy - fcy) > max(3.5, fh * 0.8):
                            continue
                        if (e.bbox[2] - e.bbox[0]) > 120:
                            continue
                        if numbering_pos == "right":
                            if e.bbox[0] < f.bbox[2] - 4:
                                continue
                            if e.bbox[2] < max_x * 0.75:
                                continue
                        elif numbering_pos == "left":
                            if e.bbox[2] > f.bbox[0] + 4:
                                continue
                        score = abs(ecy - fcy) * 1000.0 + abs(e.bbox[0] - f.bbox[2])
                        if best_score is None or score < best_score:
                            best_score = score
                            best = num
                            best_bbox = e.bbox
                    if best is not None:
                        num = best
                        num_bbox = best_bbox
            
            if not num:
                if require_numbering:
                    issues.append(
                        {
                            "issue_type": "Formula_Missing",
                            "severity": "Warning",
                            "page_num": f.page_num,
                            "bbox": f.bbox,
                            "evidence": f.content,
                            "message": "公式未检测到编号",
                            "location": {"page": f.page_num, "bbox": f.bbox}
                        }
                    )
                continue
            if check_reference and num not in ref_nums:
                issues.append(
                    {
                        "issue_type": "Formula_Ref_Missing",
                        "severity": "Info",
                        "page_num": f.page_num,
                        "bbox": f.bbox,
                        "evidence": f.content,
                        "message": "公式编号未在正文引用中出现",
                        "location": {"page": f.page_num, "bbox": f.bbox}
                    }
                )
            max_x = page_max_x.get(f.page_num, f.bbox[2])
            
            # Dynamic Rule Check: Formula Numbering
            if numbering_pos == "right":
                check_bbox = num_bbox or f.bbox
                if check_bbox[2] < max_x * 0.6:
                    issues.append(
                        {
                            "issue_type": "Formula_Misaligned",
                            "severity": "Warning",
                            "page_num": f.page_num,
                            "bbox": f.bbox,
                            "evidence": f.content,
                            "message": "公式编号疑似未右对齐",
                            "location": {"page": f.page_num, "bbox": f.bbox}
                        }
                    )
            elif numbering_pos == "left":
                # Assuming left margin is near 0
                 check_bbox = num_bbox or f.bbox
                 if check_bbox[0] > max_x * 0.15: # Simple heuristic
                    issues.append(
                        {
                            "issue_type": "Formula_Misaligned",
                            "severity": "Warning",
                            "page_num": f.page_num,
                            "bbox": f.bbox,
                            "evidence": f.content,
                            "message": "公式编号疑似未左对齐",
                            "location": {"page": f.page_num, "bbox": f.bbox}
                        }
                    )
        return issues

    def _check_titles(self, elements: List[VisualElement]) -> List[Dict[str, Any]]:
        issues = []
        rule_config = self.rules.get("heading_check", {})
        max_depth = rule_config.get("max_depth", 4)
        continuity_check = bool(rule_config.get("continuity_check", False))
        continuity_severity = rule_config.get("continuity_severity", "Info")
        column_threshold = float(rule_config.get("column_threshold", 200.0))

        titles = [e for e in elements if e.type == "title" and e.region == "title"]
        numbered = []
        for t in titles:
            if not is_heading_text(t.content):
                continue
            m = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[.、]|\s+)", t.content.strip())
            if not m:
                continue
            parts = [int(x) for x in m.group(1).split(".")]
            
            # Dynamic Rule Check: Max Depth
            if len(parts) > max_depth:
                 issues.append(
                    {
                        "issue_type": "Hierarchy_Fault",
                        "severity": "Warning",
                        "page_num": t.page_num,
                        "bbox": t.bbox,
                        "evidence": t.content,
                        "message": f"标题层级过深 (最大允许: {max_depth})",
                        "location": {"page": t.page_num, "bbox": t.bbox}
                    }
                )

            numbered.append((t, parts))
        if continuity_check:
            for i in range(1, len(numbered)):
                prev, prev_parts = numbered[i - 1]
                curr, curr_parts = numbered[i]
                same_page = curr.page_num == prev.page_num
                prev_cx = (prev.bbox[0] + prev.bbox[2]) / 2.0
                curr_cx = (curr.bbox[0] + curr.bbox[2]) / 2.0
                same_column = abs(curr_cx - prev_cx) < column_threshold
                if not (same_page and same_column):
                    continue
                if len(curr_parts) > len(prev_parts) + 1:
                    issues.append(
                        {
                            "issue_type": "Hierarchy_Fault",
                            "severity": continuity_severity,
                            "page_num": curr.page_num,
                            "bbox": curr.bbox,
                            "evidence": curr.content,
                            "message": "标题层级跳跃",
                            "location": {"page": curr.page_num, "bbox": curr.bbox}
                        }
                    )
                    continue
                if len(curr_parts) == len(prev_parts) and curr_parts[:-1] == prev_parts[:-1]:
                    if curr_parts[-1] - prev_parts[-1] > 1:
                        issues.append(
                            {
                                "issue_type": "Hierarchy_Fault",
                                "severity": continuity_severity,
                                "page_num": curr.page_num,
                                "bbox": curr.bbox,
                                "evidence": curr.content,
                                "message": "标题序号不连续",
                                "location": {"page": curr.page_num, "bbox": curr.bbox}
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

    def update_rules(self, rules: Dict[str, Any]):
        self.validator.update_rules(rules)

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
