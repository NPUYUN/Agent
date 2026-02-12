# CV/布局开发补完代码

以下补完代码覆盖框架文档中尚未落地的部分：区域划分、异常PDF兼容、对接接口数据封装、前端高亮数据输出。保持与现有项目结构一致，便于直接集成。

## 1) core/layout_zones.py
```python
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
```

## 2) core/layout_exceptions.py
```python
from typing import Optional
from pydantic import BaseModel


class ParseError(BaseModel):
    error_type: str
    message: str
    page_num: Optional[int] = None


class ParseReport(BaseModel):
    encrypted: bool = False
    scanned_pages: int = 0
    multi_column_pages: int = 0
```

## 3) core/layout_payload.py
```python
from typing import Any, Dict, List
from pydantic import BaseModel, Field


class LayoutPayload(BaseModel):
    elements: List[Dict[str, Any]] = Field(default_factory=list)
    layout_issues: List[Dict[str, Any]] = Field(default_factory=list)
    anchors: List[Dict[str, Any]] = Field(default_factory=list)
    parse_errors: List[Dict[str, Any]] = Field(default_factory=list)
    parse_report: Dict[str, Any] = Field(default_factory=dict)


def build_layout_payload(elements, layout_issues, anchors, parse_errors=None, parse_report=None) -> LayoutPayload:
    return LayoutPayload(
        elements=[e.model_dump() for e in elements],
        layout_issues=layout_issues,
        anchors=anchors,
        parse_errors=parse_errors or [],
        parse_report=parse_report or {},
    )
```

## 4) core/layout_frontend_adapter.py
```python
from typing import Dict, Any, List


def issues_to_frontend_payload(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    highlights = []
    for issue in issues:
        highlights.append(
            {
                "anchor_id": issue.get("anchor_id"),
                "page_num": issue.get("page_num"),
                "bbox": issue.get("bbox"),
                "highlight": issue.get("highlight", issue.get("bbox")),
                "severity": issue.get("severity"),
                "issue_type": issue.get("issue_type"),
                "message": issue.get("message"),
                "evidence": issue.get("evidence"),
            }
        )
    return {"highlights": highlights}
```

## 5) api/layout_routes.py
```python
from fastapi import APIRouter
from core.layout_analysis import LayoutAnalyzer
from core.layout_payload import build_layout_payload


router = APIRouter()
layout_analyzer = LayoutAnalyzer()


@router.post("/layout/analyze")
async def analyze_layout(payload: dict):
    content = payload.get("content")
    result = await layout_analyzer.analyze(content)
    elements = result.get("elements", [])
    issues = result.get("layout_result", {}).get("layout_issues", [])
    anchors = issues
    return build_layout_payload(elements, issues, anchors).model_dump()
```

## 6) core/layout_integration.py
```python
from typing import Dict, Any
from core.layout_frontend_adapter import issues_to_frontend_payload


def merge_layout_to_response(layout_result: Dict[str, Any]) -> Dict[str, Any]:
    issues = layout_result.get("layout_issues", [])
    frontend_payload = issues_to_frontend_payload(issues)
    return {
        "layout_issues": issues,
        "frontend": frontend_payload,
    }
```
