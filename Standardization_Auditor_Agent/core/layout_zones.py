from typing import Dict, Any, List, Tuple
import re


def is_reference_title(text: str) -> bool:
    return text.strip() in {"参考文献", "参考文献："}


def is_caption(text: str) -> bool:
    return re.match(r"^(图|表)\s*\d+", text) is not None


def is_formula_text(text: str) -> bool:
    if re.search(r"[=∑∫√≈≠≤≥]", text):
        return True
    if re.search(r"(（\d+）|\(\d+\))$", text):
        return True
    return False


def is_heading_text(text: str) -> bool:
    if re.match(r"^(\d+(?:\.\d+)*)[.\s、]", text):
        return True
    if re.match(r"^第[一二三四五六七八九十百]+[章节]", text):
        return True
    return False


def classify_line_region(text: str, font_size: float, body_font: float, reference_mode: bool) -> str:
    if reference_mode:
        return "reference"
    if is_caption(text):
        return "chart"
    if is_formula_text(text):
        return "formula"
    if is_heading_text(text) or font_size >= body_font * 1.3:
        return "title"
    if re.search(r"\[\d+(?:,\s*\d+)*\]", text):
        return "citation"
    return "main"


def detect_reference_mode(lines: List[Dict[str, Any]]) -> bool:
    for line in lines:
        if is_reference_title(line.get("text", "")):
            return True
    return False


def assign_columns(blocks: List[Dict[str, Any]], page_width: float) -> List[List[Dict[str, Any]]]:
    if not blocks:
        return []
    mid = page_width * 0.5
    left = [b for b in blocks if b.get("bbox", [0, 0, 0, 0])[0] < mid]
    right = [b for b in blocks if b.get("bbox", [0, 0, 0, 0])[0] >= mid]
    if not left or not right:
        return [blocks]
    return [left, right]
