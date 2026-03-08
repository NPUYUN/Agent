
import unittest
import sys
import os
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.layout_analysis import VisualValidator, VisualElement
from core.layout_zones import is_reference_title, is_caption, detect_reference_mode, classify_line_region

class TestFixesV2(unittest.TestCase):
    def test_label_missing_table(self):
        # Scenario: Table caption exists, but no image element (common for tables)
        validator = VisualValidator()
        elements = [
            VisualElement(page_num=1, bbox=[10, 10, 100, 20], type="title", content="表1-1 数据统计表", region="main"),
            VisualElement(page_num=1, bbox=[10, 30, 100, 100], type="text", content="Header\nRow1", region="main"),
        ]
        # Mock rules to avoid errors if rules file is missing
        validator.rules = {}
        
        issues = validator._check_charts(elements)
        # Should NOT have Label_Missing for table
        label_missing = [i for i in issues if i["issue_type"] == "Label_Missing"]
        self.assertEqual(len(label_missing), 0, "Table caption should not trigger Label_Missing if no image is found")

    def test_label_missing_figure_relaxed(self):
        # Scenario: Figure caption exists, but no image element
        validator = VisualValidator()
        elements = [
            VisualElement(page_num=2, bbox=[10, 200, 100, 210], type="title", content="图2-1 架构图", region="main"),
        ]
        validator.rules = {}
        
        issues = validator._check_charts(elements)
        # Should have Label_Missing but severity Info
        label_missing = [i for i in issues if i["issue_type"] == "Label_Missing"]
        self.assertEqual(len(label_missing), 1)
        self.assertEqual(label_missing[0]["severity"], "Info", "Figure missing image should be Info severity")

    def test_formula_detection(self):
        # Scenario: Formula with (1-1) format and trailing space
        validator = VisualValidator()
        elements = [
            VisualElement(page_num=3, bbox=[10, 10, 100, 20], type="formula", content="E = mc^2 (1-1) ", region="main"),
        ]
        validator.rules = {}
        
        # Mock text refs to avoid errors in _check_formulas
        # It iterates over elements to find text refs
        
        issues = validator._check_formulas(elements)
        # Should NOT have Formula_Missing
        formula_missing = [i for i in issues if i["issue_type"] == "Formula_Missing"]
        self.assertEqual(len(formula_missing), 0, f"Formula (1-1) should be detected. Issues found: {formula_missing}")

    def test_reference_title_detection(self):
        self.assertTrue(is_reference_title("参考文献"))
        self.assertTrue(is_reference_title("参 考 文 献"))
        self.assertTrue(is_reference_title("References"))
        self.assertTrue(is_reference_title("Reference"))
        self.assertFalse(is_reference_title("Conclusion"))

    def test_citation_reference_match(self):
        validator = VisualValidator()
        elements = [
            # Citations
            VisualElement(page_num=1, bbox=[0,0,0,0], type="citation", content="[1]", region="citation"),
            VisualElement(page_num=1, bbox=[0,0,0,0], type="citation", content="[2]", region="citation"),
            VisualElement(page_num=1, bbox=[0,0,0,0], type="citation", content="[3]", region="citation"),
            # References
            VisualElement(page_num=5, bbox=[0,0,0,0], type="text", content="[1] Author A...", region="reference"),
            VisualElement(page_num=5, bbox=[0,0,0,0], type="text", content="2. Author B...", region="reference"),
            # This one currently fails with strict regex
            VisualElement(page_num=5, bbox=[0,0,0,0], type="text", content="(3) Author C...", region="reference"),
        ]
        validator.rules = {}
        issues = validator._check_citations(elements)
        
        # Check for Citation_Visual_Fault
        faults = [i for i in issues if i["issue_type"] == "Citation_Visual_Fault"]
        # Should be 0 now with relaxed regex
        self.assertEqual(len(faults), 0, f"Citation mismatch found: {faults}")
        
    def test_caption_detection(self):
        self.assertTrue(is_caption("图1 xxx"))
        self.assertTrue(is_caption("表2 xxx"))
        self.assertTrue(is_caption("Figure 3 xxx"))
        self.assertTrue(is_caption("Table 4 xxx"))
        self.assertTrue(is_caption("Fig. 5 xxx"))

if __name__ == '__main__':
    unittest.main()
