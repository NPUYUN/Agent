import yaml
import os
from typing import Dict, Any

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rules.yaml")

def load_rules() -> Dict[str, Any]:
    if not os.path.exists(RULES_PATH):
        return {}
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

from typing import List, Any
import re
from .layout_schema import LayoutIssue


def check_citation_reference_match(citations: List[Any], references: List[Any]) -> List[LayoutIssue]:
    ref_nums = set()
    for r in references:
        # Support [1], (1), 1., 1 (space)
        m = re.match(r"^\s*(?:\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\)|(\d+)\.|(\d+)\s)", r.content)
        if m:
            num = next((g for g in m.groups() if g is not None), None)
            if num:
                ref_nums.add(num)
    issues: List[LayoutIssue] = []
    for c in citations:
        m = re.search(r"\[(\d+)", c.content)
        if m and m.group(1) not in ref_nums:
            issues.append(
                LayoutIssue(
                    issue_type="Citation_Visual_Fault",
                    severity="Warning",
                    page_num=c.page_num,
                    bbox=c.bbox,
                    evidence=c.content,
                    message="引用标注在参考文献区未找到对应条目",
                    location={"section": "unknown", "line_start": 0} # Placeholder
                )
            )
    return issues
