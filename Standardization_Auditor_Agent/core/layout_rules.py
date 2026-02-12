from typing import List, Any
import re
from .layout_schema import LayoutIssue


def check_citation_reference_match(citations: List[Any], references: List[Any]) -> List[LayoutIssue]:
    ref_nums = set()
    for r in references:
        m = re.match(r"^\[(\d+)\]|^(\d+)\.", r.content)
        if m:
            num = m.group(1) or m.group(2)
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
                )
            )
    return issues
