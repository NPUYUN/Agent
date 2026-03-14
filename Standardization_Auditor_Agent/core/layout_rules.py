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
        m = re.match(r"^\s*(?:\[\s*(\d+)\s*\]|［\s*(\d+)\s*］|\(\s*(\d+)\s*\)|（\s*(\d+)\s*）|(\d+)\.|(\d+)\s)", r.content)
        if m:
            num = next((g for g in m.groups() if g is not None), None)
            if num:
                ref_nums.add(num)
    issues: List[LayoutIssue] = []
    for c in citations:
        nums: List[str] = []
        for inner in re.findall(r"[\[［]([^\]］]{1,50})[\]］]", c.content or ""):
            parts = [p for p in re.split(r"[,\s;，；]+", inner.strip()) if p]
            for p in parts:
                m_range = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", p)
                if m_range:
                    start = int(m_range.group(1))
                    end = int(m_range.group(2))
                    if 0 < start <= end and (end - start) <= 50:
                        nums.extend([str(n) for n in range(start, end + 1)])
                    continue
                if re.match(r"^\d+$", p):
                    if p != "0":
                        nums.append(p)
        if not nums:
            m = re.search(r"\b(\d+)\b", c.content or "")
            if m:
                if m.group(1) != "0":
                    nums = [m.group(1)]
        missing = sorted({n for n in nums if n not in ref_nums}, key=lambda x: int(x))
        if missing:
            issues.append(
                LayoutIssue(
                    issue_type="Citation_Visual_Fault",
                    severity="Warning",
                    page_num=c.page_num,
                    bbox=c.bbox,
                    evidence=c.content,
                    message=f"引用标注在参考文献区未找到对应条目: {', '.join(missing)}",
                    location={"section": "unknown", "line_start": 0}
                )
            )
    return issues
