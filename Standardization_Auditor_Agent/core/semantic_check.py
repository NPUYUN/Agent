from typing import List, Dict, Any, Optional
from .llm_client import GeminiClient
from .rule_engine import RuleEngine

class TypoChecker:
    """
    语义判定 - 错别字红线判定
    对应《分工明细》二、语义判定 - 阶段2
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_typos_total = config.get("max_typos_total_warning", 10)
        self.critical_keywords = config.get("critical_keywords", [])

    def check(self, content: str, issues: List[Dict]):
        """
        1. 集成中文分词/错别字检测工具
        2. 上下文语义纠错 (排除专业名词歧义)
        3. 红线触发逻辑: 全文>10个 -> Warning; 关键术语错字 -> Critical
        """
        # 模拟检测逻辑
        # if typo_count > self.max_typos_total:
        #     issues.append({...})
        pass

class TerminologyChecker:
    """
    语义判定 - 术语一致性校验
    对应《分工明细》二、语义判定 - 阶段3
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.terms = config.get("terms", {})
        self.forbidden_variants = config.get("forbidden_variants", {})

    def check(self, content: str, issues: List[Dict]):
        """
        1. 提取专有名词，建立临时术语库
        2. 检测写法不一致 (如 'Deep Learning' vs 'deep-learning')
        3. 生成统一建议
        """
        pass

class PunctuationChecker:
    """
    语义判定 - 标点符号校验
    对应《分工明细》二、语义判定 - 阶段3
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.allow_mixed = config.get("allow_mixed_punctuation", False)

    def check(self, content: str, layout_data: Dict[str, Any], issues: List[Dict]):
        """
        1. 杜绝中英文标点混用
        2. 标点位置错误 (如引用标注在标点外)
        """
        pass

class CitationChecker:
    """
    语义判定 - 引用格式语义校验
    对应《分工明细》二、语义判定 - 阶段3
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.style = config.get("style", "IEEE")

    def check(self, content: str, layout_data: Dict[str, Any], issues: List[Dict]):
        """
        1. 引用风格一致性 (IEEE vs APA)
        2. 引用标注与参考文献条目匹配 (语义匹配)
        """
        pass

class SemanticChecker:
    """
    语义判定总入口
    负责规则层面的格式校验，并与CV层结果融合
    """
    def __init__(self):
        self.llm_client = GeminiClient()
        self.rule_engine = RuleEngine() # 动态规则引擎
        
        # 初始化子模块并注入规则
        self.typo_checker = TypoChecker(self.rule_engine.get_rule("typo_check"))
        self.term_checker = TerminologyChecker(self.rule_engine.get_rule("terminology_check"))
        self.punct_checker = PunctuationChecker(self.rule_engine.get_rule("punctuation_check"))
        self.cite_checker = CitationChecker(self.rule_engine.get_rule("citation_check"))

    async def check(self, content: str, layout_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行语义校验的主流程
        """
        # 支持规则热更新 (可选，每次请求检查更新)
        # self.rule_engine.reload() 
        
        issues = []
        
        # 1. 规则校验 (各模块独立执行)
        self.typo_checker.check(content, issues)
        self.term_checker.check(content, issues)
        self.punct_checker.check(content, layout_data, issues)
        self.cite_checker.check(content, layout_data, issues)
        
        # 2. LLM 辅助扫描 (Gemini 1.5 Flash)
        # 利用长上下文能力辅助扫描复杂格式问题
        # Ref: 分工明细 - LLM Scanner
        llm_feedback = await self.llm_client.scan_document(content)
        
        # 3. 结果融合与去重
        # 避免视觉层和语义层对同一问题的重复标注
        # Ref: 分工明细 - 阶段4: 结果去重逻辑
        
        return {
            "semantic_issues": issues,
            "llm_feedback": llm_feedback,
            "score": self._calculate_score(issues)
        }

    def _calculate_score(self, issues: List[Dict]) -> int:
        """
        基于问题数量和严重程度计算扣分
        """
        score = 100
        # 简单扣分逻辑示例
        for issue in issues:
            level = issue.get("level", "Info")
            if level == "Critical":
                score -= 10
            elif level == "Warning":
                score -= 5
            else:
                score -= 1
        return max(0, score)
