import pytest
from core.semantic_check import TypoChecker, PunctuationChecker, TerminologyChecker

# Mock Configs
TYPO_CONFIG = {
    "max_typos_total_warning": 2,
    "critical_keywords": ["TensorFlow", "Pydantic", "Python"]
}

PUNCT_CONFIG = {
    "allow_mixed_punctuation": False,
    "check_citation_position": True
}

TERM_CONFIG = {
    "terms": {
        "Deep Learning": ["深度学习"]
    },
    "forbidden_variants": {
        "Deep Learning": ["deep-learning"]
    }
}

def test_typo_checker_critical():
    checker = TypoChecker(TYPO_CONFIG)
    content = "We use TensorFlwo for training. Pydantci is great."
    issues = []
    checker.check(content, issues)
    
    assert len(issues) == 2
    assert issues[0]["issue_type"] == "Critical_Keyword_Typo"
    assert "TensorFlwo" in issues[0]["evidence"]
    assert "Pydantci" in issues[1]["evidence"]

def test_typo_checker_threshold():
    checker = TypoChecker(TYPO_CONFIG)
    # Simulate finding typos
    # Use clearly distinguishable typos to satisfy difflib cutoff=0.85
    # Pyhton (0.833) < 0.85. Use Pythonn (0.92) instead.
    content = "TensorFlwo Pydantci Pythonn" 
    issues = []
    checker.check(content, issues)
    
    # 3 Critical Typos + 1 Threshold Warning
    assert len(issues) == 4 
    assert issues[-1]["issue_type"] == "Typo_Limit_Exceeded"

def test_punctuation_checker_mixed():
    checker = PunctuationChecker(PUNCT_CONFIG)
    content = "这是一个测试." # Chinese followed by .
    issues = []
    checker.check(content, {}, issues)
    
    assert len(issues) >= 1
    assert issues[0]["issue_type"] == "Punctuation_Mixed"

def test_punctuation_checker_citation_position():
    checker = PunctuationChecker(PUNCT_CONFIG)
    content = "Reference.[1]" # Error
    issues = []
    checker.check(content, {}, issues)
    
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "Citation_Position_Inconsistent"

def test_punctuation_checker_citation_position_correct():
    checker = PunctuationChecker(PUNCT_CONFIG)
    content = "Reference[1]." # Correct
    issues = []
    checker.check(content, {}, issues)
    
    assert len(issues) == 0

def test_terminology_checker():
    checker = TerminologyChecker(TERM_CONFIG)
    content = "We use deep-learning in this paper."
    issues = []
    checker.check(content, issues)
    
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "Terminology_Forbidden"
