import pytest
import sys
import os

# Ensure we can import from core
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.layout_analysis import VisualValidator, VisualElement
from core.layout_rules import load_rules

@pytest.mark.asyncio
async def test_heading_hierarchy_rule():
    """Test dynamic heading hierarchy rule (max depth)."""
    validator = VisualValidator()
    # Mock rule: max_depth=4 (default)
    
    elements = [
        VisualElement(type="title", content="1. Introduction", bbox=[0,0,100,20], page_num=1, region="title"),
        VisualElement(type="title", content="1.1 Background", bbox=[0,30,100,50], page_num=1, region="title"),
        VisualElement(type="title", content="1.1.1.1.1 Deepest Level", bbox=[0,60,100,80], page_num=1, region="title")
    ]
    
    result = await validator.validate(elements)
    issues = result["layout_issues"]
    
    hierarchy_faults = [i for i in issues if i["issue_type"] == "Hierarchy_Fault"]
    
    # Expect fault for 1.1.1.1.1 (depth 5 > 4)
    found = False
    for fault in hierarchy_faults:
        if "标题层级过深" in fault["message"]:
            found = True
            assert "location" in fault
            assert fault["location"]["page"] == 1
            assert fault["evidence"] == "1.1.1.1.1 Deepest Level"
    
    assert found, "Should detect max depth violation"

@pytest.mark.asyncio
async def test_figure_position_rule():
    """Test dynamic figure position rule (caption below)."""
    validator = VisualValidator()
    # Mock rule: caption_requirement="bottom" (default)
    
    # Case 1: Caption ABOVE Image (Wrong)
    elements_wrong = [
        VisualElement(type="title", content="图1 架构图", bbox=[100, 100, 200, 120], page_num=1, region="chart"),
        VisualElement(type="image", content="", bbox=[100, 130, 200, 300], page_num=1, region="chart")
    ]
    
    result = await validator.validate(elements_wrong)
    issues = [i for i in result["layout_issues"] if i["issue_type"] == "Label_Missing"]
    
    found_wrong = False
    for issue in issues:
        if "图标题应位于图下方" in issue["message"]:
            found_wrong = True
            assert "location" in issue
            assert issue["evidence"] == "图1 架构图"
            
    assert found_wrong, "Should detect caption above figure when rule requires bottom"

    # Case 2: Caption BELOW Image (Correct)
    elements_correct = [
        VisualElement(type="image", content="", bbox=[100, 100, 200, 200], page_num=2, region="chart"),
        VisualElement(type="title", content="图2 流程图", bbox=[100, 210, 200, 230], page_num=2, region="chart")
    ]
    
    result_correct = await validator.validate(elements_correct)
    issues_correct = [i for i in result_correct["layout_issues"] if "图标题应位于图下方" in i["message"]]
    assert len(issues_correct) == 0, "Should not detect issue for correct positioning"

@pytest.mark.asyncio
async def test_formula_alignment_rule():
    """Test dynamic formula alignment rule."""
    validator = VisualValidator()
    # Mock rule: numbering="right"
    
    # Page width assumed to be somewhat large, let's say max_x detected is 600
    # Formula numbering at x=550 (Right aligned) -> OK
    # Formula numbering at x=100 (Left aligned) -> Fail
    
    elements = [
        # This element defines the page width implicitly
        VisualElement(type="text", content="Page boundary", bbox=[0, 0, 600, 800], page_num=1, region="main"),
        
        # Misaligned formula number
        VisualElement(type="formula", content="(1)", bbox=[50, 100, 80, 120], page_num=1, region="formula"),
        
        # Correctly aligned formula number
        VisualElement(type="formula", content="(2)", bbox=[550, 150, 580, 170], page_num=1, region="formula")
    ]
    
    result = await validator.validate(elements)
    issues = [i for i in result["layout_issues"] if i["issue_type"] == "Formula_Misaligned"]
    
    assert len(issues) == 1
    assert "公式编号疑似未右对齐" in issues[0]["message"]
    assert issues[0]["evidence"] == "(1)"
    assert "location" in issues[0]
    assert "location" in issues[0]

