import os
import sys
import json
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.rule_engine import RuleEngine
from core.layout_analysis import LayoutAnalyzer
from core.semantic_check import SemanticChecker


async def run(pdf_path: str):
    rule_engine = RuleEngine(config_path=os.path.join(os.getcwd(), "rules.yaml"))
    try:
        await rule_engine.load_rules_from_db()
    except Exception:
        pass

    layout_analyzer = LayoutAnalyzer()
    semantic_checker = SemanticChecker()
    layout_analyzer.update_rules(rule_engine.rules)
    semantic_checker.update_rules(rule_engine.rules)

    layout_data = await layout_analyzer.analyze(pdf_path)

    # Extract text from layout elements to avoid re-opening PDF
    elements = layout_data.get("elements", [])
    text_content = "\n".join([str(e.content) for e in elements if getattr(e, "content", None)])

    semantic_result = await semantic_checker.check(text_content, layout_data)

    layout_issues = layout_data.get("layout_result", {}).get("layout_issues", [])
    semantic_issues = semantic_result.get("semantic_issues", [])
    all_issues = layout_issues + semantic_issues
    score = semantic_result.get("score")

    result = {
        "score": score,
        "counts": {
            "Critical": sum(1 for i in all_issues if (i.get("severity") or i.get("level")) == "Critical"),
            "Warning": sum(1 for i in all_issues if (i.get("severity") or i.get("level")) == "Warning"),
            "Info": sum(1 for i in all_issues if (i.get("severity") or i.get("level")) == "Info"),
        },
        "total_issues": len(all_issues),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/cli_probe.py <pdf_path>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
