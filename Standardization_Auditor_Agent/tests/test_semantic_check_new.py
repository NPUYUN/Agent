
import unittest
from typing import List, Dict, Any
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.semantic_check import TypoChecker, TerminologyChecker, PunctuationChecker

class TestSemanticCheckers(unittest.TestCase):

    def test_typo_checker(self):
        config = {
            "max_typos_total_warning": 2,
            "critical_keywords": ["TensorFlow", "Pytorch"]
        }
        checker = TypoChecker(config)
        issues = []
        
        # Test critical keyword typo
        content = "We use TensorFlw for deep learning. Also Pytorchh is good."
        checker.check(content, issues)
        
        # Expecting 2 critical typos (TensorFlw, Pytorchh) and maybe generic typos?
        # Actually my simple typo checker doesn't check generic words against a dictionary, 
        # only critical keywords fuzzy match.
        
        critical_issues = [i for i in issues if i["issue_type"] == "Critical_Keyword_Typo"]
        self.assertEqual(len(critical_issues), 2)
        self.assertIn("TensorFlow", critical_issues[0]["message"])
        self.assertIn("Pytorch", critical_issues[1]["message"])

    def test_terminology_checker(self):
        config = {
            "terms": {
                "Deep Learning": ["deep learning"], # canonical: [variants]
                "CNN": ["Convolutional Neural Network"]
            },
            "forbidden_variants": {
                "Deep Learning": ["deep-learning"]
            }
        }
        checker = TerminologyChecker(config)
        issues = []
        
        content = "Deep Learning is great. deep learning is also used. We also see deep-learning here."
        checker.check(content, issues)
        
        # "deep learning" is allowed variant, so no issue for it if it matches one of the variants?
        # Wait, my logic says:
        # "If we find matches that are NOT in the allowed variants list, flag them."
        # allowed_forms = {canonical} + variants
        # "Deep Learning" is canonical. "deep learning" is variant.
        # "deep-learning" is not in allowed forms.
        
        # However, the TerminologyChecker also checks for *consistency*.
        # "If len({_normalize_term_key(f) for f in found}) > 1" logic was replaced.
        # My new logic:
        # Check if any usage is NOT in allowed_forms.
        
        # Let's re-read my implementation of TerminologyChecker.
        # matches = re.findall(r'\b' + escaped_term + r'\b', content, flags=re.IGNORECASE)
        # allowed_forms = {canonical} + variants
        # inconsistent_usages = set()
        # for usage in matches: if usage not in allowed_forms: inconsistent_usages.add(usage)
        
        # "Deep Learning" -> allowed.
        # "deep learning" -> allowed.
        # "deep-learning" -> matches regex? regex uses escaped_term ("Deep\ Learning").
        # re.findall(r'\bDeep\ Learning\b', "deep-learning", re.I) -> usually doesn't match "deep-learning" because of hyphen?
        # \b matches boundary between \w and \W. hyphen is \W.
        # So "deep-learning" contains "deep" and "learning".
        # If I search for "Deep Learning" (space), it won't match "deep-learning" (hyphen).
        
        # So "deep-learning" will be caught by "forbidden_variants" check logic, not the first loop.
        
        # Let's test inconsistent casing that IS a match but not allowed.
        # e.g. "DEEP LEARNING" (if not in variants).
        
        content2 = "Deep Learning is good. DEEP LEARNING is loud."
        issues2 = []
        checker.check(content2, issues2)
        # DEEP LEARNING should be flagged.
        self.assertTrue(any(i["issue_type"] == "Terminology_Inconsistent" for i in issues2))
        
        # Test forbidden
        content3 = "We use deep-learning techniques."
        issues3 = []
        checker.check(content3, issues3)
        self.assertTrue(any(i["issue_type"] == "Terminology_Forbidden" for i in issues3))

    def test_punctuation_checker(self):
        config = {
            "allow_mixed_punctuation": False,
            "check_citation_position": True
        }
        checker = PunctuationChecker(config)
        issues = []
        
        content = "这是一个中文句子." # English period
        checker.check(content, {}, issues)
        self.assertTrue(any(i["issue_type"] == "Punctuation_Mixed" for i in issues))
        
        content2 = "This is English sentence。" # Chinese period
        issues2 = []
        checker.check(content2, {}, issues2)
        self.assertTrue(any(i["issue_type"] == "Punctuation_Mixed" for i in issues2))
        
        content3 = "Reference [1]. Another reference .[2]"
        issues3 = []
        checker.check(content3, {}, issues3)
        self.assertTrue(any(i["issue_type"] == "Citation_Position_Inconsistent" for i in issues3))

if __name__ == '__main__':
    unittest.main()
