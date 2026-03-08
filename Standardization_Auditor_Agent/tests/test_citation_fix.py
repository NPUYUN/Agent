
import unittest
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.semantic_check import SemanticChecker

class TestCitationFix(unittest.TestCase):
    def setUp(self):
        self.checker = SemanticChecker()
        
    def test_isolated_citation_downgrade(self):
        # Simulate LLM response with "Citation_Placeholder" issues
        llm_response = json.dumps({
            "issues": [
                {
                    "issue_type": "Citation_Placeholder",
                    "severity": "Critical",
                    "evidence": "[12]",
                    "message": "孤立的引用编号"
                },
                {
                    "issue_type": "Citation_Placeholder",
                    "severity": "Critical",
                    "evidence": "[21,23]",
                    "message": "单独成行的引用"
                },
                {
                    "issue_type": "Citation_Placeholder",
                    "severity": "Critical",
                    "evidence": "[12], [13]",
                    "message": "单独成行的引用 [12], [13]"
                },
                {
                    "issue_type": "Citation_Placeholder",
                    "severity": "Critical",
                    "evidence": "[?]",
                    "message": "引用占位符"
                },
                {
                    "issue_type": "Other_Issue",
                    "severity": "Warning",
                    "evidence": "something else",
                    "message": "其他问题"
                }
            ],
            "summary": "测试摘要"
        })
        
        issues, summary = self.checker._parse_llm_response(llm_response)
        
        # Check issues
        self.assertEqual(len(issues), 5)
        
        # Issue 1: [12] -> Should be downgraded
        self.assertEqual(issues[0]["issue_type"], "Citation_Layout_Check")
        self.assertEqual(issues[0]["severity"], "Info")
        self.assertIn("疑似排版", issues[0]["message"])
        
        # Issue 2: [21,23] -> Should be downgraded
        self.assertEqual(issues[1]["issue_type"], "Citation_Layout_Check")
        self.assertEqual(issues[1]["severity"], "Info")
        
        # Issue 3: [12], [13] -> Should be downgraded (condition 2)
        self.assertEqual(issues[2]["issue_type"], "Citation_Layout_Check")
        self.assertEqual(issues[2]["severity"], "Info")
        
        # Issue 4: [?] -> Should remain Critical (not valid citation pattern)
        # Regex ^\[[\d,\s-]+\]$ does not match [?]
        self.assertEqual(issues[3]["issue_type"], "Citation_Placeholder")
        self.assertEqual(issues[3]["severity"], "Critical")
        
        # Issue 5: Other -> Unchanged
        self.assertEqual(issues[4]["issue_type"], "Other_Issue")
        self.assertEqual(issues[4]["severity"], "Warning")

if __name__ == '__main__':
    unittest.main()
