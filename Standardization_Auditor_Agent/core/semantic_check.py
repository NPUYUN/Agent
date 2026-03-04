from typing import List, Dict, Any, Optional
import asyncio
import base64
import math
import re
import difflib
from collections import Counter
from config import LLM_TIMEOUT_SEC
from .llm_client import LLMClient
from .rule_engine import RuleEngine


def _element_get(element: Any, key: str) -> Any:
    if isinstance(element, dict):
        return element.get(key)
    return getattr(element, key, None)


def _extract_text_from_layout(layout_data: Dict[str, Any]) -> str:
    elements = layout_data.get("elements", []) if isinstance(layout_data, dict) else []
    texts = []
    for e in elements:
        text = _element_get(e, "content")
        if text:
            texts.append(str(text))
    return "\n".join(texts)


def _is_pdf_base64(content: str) -> bool:
    try:
        decoded = base64.b64decode(content, validate=True)
    except Exception:
        return False
    return b"%PDF" in decoded[:1024]


def _resolve_text_content(content: Any, layout_data: Dict[str, Any]) -> str:
    if isinstance(content, str):
        if _is_pdf_base64(content):
            layout_text = _extract_text_from_layout(layout_data)
            return layout_text
        return content
    return _extract_text_from_layout(layout_data)


def _term_found(content: str, term: str) -> bool:
    if not term:
        return False
    if re.search(r"[A-Za-z]", term):
        pattern = r"\b" + re.escape(term) + r"\b"
        return re.search(pattern, content, flags=re.IGNORECASE) is not None
    return term in content


def _normalize_term_key(term: str) -> str:
    if re.search(r"[A-Za-z]", term):
        return term.lower()
    return term


def _extract_reference_numbers(reference_texts: List[str]) -> List[str]:
    nums = []
    for line in reference_texts:
        m = re.match(r"^\s*\[(\d+)\]", line)
        if m:
            nums.append(m.group(1))
            continue
        m = re.match(r"^\s*(\d+)[.)]", line)
        if m:
            nums.append(m.group(1))
    return nums


def _extract_numeric_citations(content: str) -> List[str]:
    return re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", content)


def _extract_author_year_citations(content: str) -> List[str]:
    results = []
    for m in re.finditer(r"\(([^()]*\d{4}[a-z]?[^()]*)\)", content):
        value = m.group(1)
        if re.search(r"[A-Za-z]", value):
            results.append(value)
    return results


def _parse_author_year(citation: str) -> Optional[Dict[str, str]]:
    year_match = re.search(r"\d{4}[a-z]?", citation)
    author_match = re.search(r"\b([A-Za-z][A-Za-z'\-]+)\b", citation)
    if not year_match or not author_match:
        return None
    return {"author": author_match.group(1).lower(), "year": year_match.group(0)}


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
        1. 集成中文分词/错别字检测工具 (简化实现: 基于关键术语和规则)
        2. 上下文语义纠错 (排除专业名词歧义)
        3. 红线触发逻辑: 全文>10个 -> Warning; 关键术语错字 -> Critical
        """
        if not content:
            return

        typo_count = 0
        
        # Check critical keywords for typos (fuzzy matching)
        # Simple tokenization for checking
        words = re.findall(r'\b\w+\b', content)
        
        # Optimization: only check unique words to save time
        unique_words = set(words)
        
        for keyword in self.critical_keywords:
            # Check for exact keyword presence (to ensure we don't flag the keyword itself as a typo of itself)
            # Actually we want to find *incorrect* versions.
            
            # Simple approach: find close matches in the text that are NOT the keyword itself
            # We look for words that are similar to the keyword but not identical.
            # Using difflib.get_close_matches
            
            # Note: This is computationally expensive for large texts. 
            # We restrict to words of similar length.
            
            # Filter candidates: words that start with the same letter and have similar length
            candidates = [
                w for w in unique_words 
                if abs(len(w) - len(keyword)) <= 2 and w.lower() != keyword.lower()
            ]
            
            matches = difflib.get_close_matches(keyword, candidates, n=3, cutoff=0.8)
            
            for match in matches:
                # Double check: if it's a valid variant (e.g. plural), maybe skip?
                # For now, treat as potential typo if it's a critical keyword.
                # To reduce false positives, we might need a whitelist, but let's stick to the prompt.
                
                issues.append({
                    "issue_type": "Critical_Keyword_Typo",
                    "severity": "Critical",
                    "evidence": match,
                    "message": f"关键术语 '{keyword}' 可能存在拼写错误: '{match}'",
                })
                typo_count += 1

        # Generic typo check (simulated / placeholder for integration with external tool)
        # Here we just check for a few common errors or repeated words
        repeated_words = re.findall(r'\b(\w+)\s+\1\b', content, flags=re.IGNORECASE)
        for word in repeated_words:
            issues.append({
                "issue_type": "Repeated_Word",
                "severity": "Warning",
                "evidence": f"{word} {word}",
                "message": f"发现重复单词: '{word}'",
            })
            typo_count += 1

        if typo_count > self.max_typos_total:
            issues.append({
                "issue_type": "Typo_Limit_Exceeded",
                "severity": "Warning",
                "evidence": f"Total count: {typo_count}",
                "message": f"全文错别字/疑似错误数量超过阈值 ({self.max_typos_total})",
            })


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
        if not content:
            return
        
        # Check for defined terms consistency
        for canonical, variants in self.terms.items():
            # Gather all occurrences of the term (canonical + variants)
            # We want to find *any* occurrence that looks like the term (case-insensitive)
            # and see if they are consistent with the canonical form.
            
            # Simple approach: find all case-insensitive matches of the canonical term
            # If we find matches that are NOT in the allowed variants list, flag them.
            
            # Regex for the term (case insensitive)
            escaped_term = re.escape(canonical)
            # Matches containing the term text, capturing the actual usage
            matches = re.findall(r'\b' + escaped_term + r'\b', content, flags=re.IGNORECASE)
            
            allowed_forms = {canonical}
            if variants:
                allowed_forms.update(variants)
            
            inconsistent_usages = set()
            for usage in matches:
                if usage not in allowed_forms:
                    inconsistent_usages.add(usage)
            
            if inconsistent_usages:
                 issues.append({
                    "issue_type": "Terminology_Inconsistent",
                    "severity": "Warning",
                    "evidence": ", ".join(inconsistent_usages),
                    "message": f"术语 '{canonical}' 写法不一致或不规范。发现: {', '.join(inconsistent_usages)}。建议统一为: {canonical}",
                })

        # Check for explicitly forbidden variants
        for canonical, forbidden in self.forbidden_variants.items():
            found_forbidden = []
            for form in forbidden or []:
                if _term_found(content, form):
                    found_forbidden.append(form)
            if found_forbidden:
                issues.append(
                    {
                        "issue_type": "Terminology_Forbidden",
                        "severity": "Warning",
                        "evidence": ", ".join(found_forbidden),
                        "message": f"检测到不规范术语写法 '{', '.join(found_forbidden)}'，建议使用：{canonical}",
                    }
                )


class PunctuationChecker:
    """
    语义判定 - 标点符号校验
    对应《分工明细》二、语义判定 - 阶段3
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.allow_mixed = config.get("allow_mixed_punctuation", False)
        self.check_citation_position = config.get("check_citation_position", True)

    def check(self, content: str, layout_data: Dict[str, Any], issues: List[Dict]):
        """
        1. 杜绝中英文标点混用
        2. 标点位置错误 (如引用标注在标点外)
        """
        if not content:
            return

        # 1. Mixed punctuation check
        if not self.allow_mixed:
            # Check for Chinese characters followed by English punctuation
            # Chinese char range: \u4e00-\u9fa5
            # English punctuation: , . ? ! : ; ( )
            chinese_with_eng_punct = re.findall(r'[\u4e00-\u9fa5][,.\?!:;]', content)
            if chinese_with_eng_punct:
                 issues.append({
                    "issue_type": "Punctuation_Mixed",
                    "severity": "Warning",
                    "evidence": ", ".join(chinese_with_eng_punct[:5]) + ("..." if len(chinese_with_eng_punct)>5 else ""),
                    "message": "检测到中文文本使用英文标点",
                })

            # Check for English words followed by Chinese punctuation
            # English word: [a-zA-Z0-9]+
            # Chinese punctuation: ， 。 ？ ！ ： ； （ ）
            eng_with_chinese_punct = re.findall(r'[a-zA-Z0-9]+[，。？！：；（）]', content)
            if eng_with_chinese_punct:
                issues.append({
                    "issue_type": "Punctuation_Mixed",
                    "severity": "Warning",
                    "evidence": ", ".join(eng_with_chinese_punct[:5]) + ("..." if len(eng_with_chinese_punct)>5 else ""),
                    "message": "检测到英文文本使用中文标点",
                })

        # 2. Citation position check
        # Check if citation [x] is AFTER the period/comma. 
        # IEEE usually prefers [x] before punctuation? Actually IEEE style manual says:
        # "Reference numbers are set flush left and form a column of their own, hanging out beyond the body of the reference. The reference numbers are on the line, enclosed in square brackets. In all text references to bibliography numbers, use the square brackets, e.g., '...as shown by [5], ...'"
        # "Grammatically, they may be treated as if they were footnote numbers, e.g., '...as shown by Brown [4], [5]; as mentioned earlier [2], [4]–[7], [9]...'"
        # "Punctuation follows the bracket [3]." -> So [1]. is correct.
        
        # However, some Chinese standards require [1] to be before punctuation if it cites the sentence.
        # Let's assume the rule is: Citation should be consistent.
        
        # Let's check for [x]. vs .[x]
        # Regex for [number]
        cit_pattern = r'\[\d+(?:[-,]\d+)*\]'
        
        # [x]. pattern
        cit_before_dot = re.findall(cit_pattern + r'[.。,，]', content)
        # .[x] pattern
        cit_after_dot = re.findall(r'[.。,，]' + cit_pattern, content)
        
        if cit_before_dot and cit_after_dot:
             issues.append({
                "issue_type": "Citation_Position_Inconsistent",
                "severity": "Warning",
                "evidence": f"Found both '[x].' ({len(cit_before_dot)}) and '.[x]' ({len(cit_after_dot)})",
                "message": "引用标注位置不一致 (部分在标点前，部分在标点后)",
            })

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
        if not content:
            return
        text = content
        elements = layout_data.get("elements", []) if isinstance(layout_data, dict) else []
        reference_texts = []
        for e in elements:
            region = _element_get(e, "region")
            text_value = _element_get(e, "content")
            if region == "reference" and text_value:
                reference_texts.append(str(text_value))
        ref_nums = set(_extract_reference_numbers(reference_texts))
        numeric_citations = _extract_numeric_citations(text)
        author_year_citations = _extract_author_year_citations(text)
        if numeric_citations and author_year_citations:
            issues.append(
                {
                    "issue_type": "Citation_Style_Inconsistent",
                    "severity": "Warning",
                    "evidence": "numeric + author-year",
                    "message": "正文引用风格不一致",
                }
            )
        style = (self.style or "").lower()
        if style in {"ieee", "numeric"} and author_year_citations:
            issues.append(
                {
                    "issue_type": "Citation_Style_Mismatch",
                    "severity": "Warning",
                    "evidence": "author-year",
                    "message": "引用风格与配置不一致，建议使用数字编号引用",
                }
            )
        if style in {"apa", "mla", "author-year"} and numeric_citations:
            issues.append(
                {
                    "issue_type": "Citation_Style_Mismatch",
                    "severity": "Warning",
                    "evidence": "numeric",
                    "message": "引用风格与配置不一致，建议使用作者-年份引用",
                }
            )
        if not self.config.get("check_reference_matching", True):
            return
        if not reference_texts and (numeric_citations or author_year_citations):
            issues.append(
                {
                    "issue_type": "Reference_List_Missing",
                    "severity": "Warning",
                    "evidence": "",
                    "message": "正文存在引用标注，但未检测到参考文献列表",
                }
            )
            return
        if numeric_citations:
            for group in numeric_citations:
                for num in re.findall(r"\d+", group):
                    if num not in ref_nums:
                        issues.append(
                            {
                                "issue_type": "Citation_Reference_Missing",
                                "severity": "Warning",
                                "evidence": f"[{num}]",
                                "message": "引用标注未在参考文献中找到对应编号",
                            }
                        )
        if author_year_citations and reference_texts:
            ref_lower = [r.lower() for r in reference_texts]
            for citation in author_year_citations:
                parsed = _parse_author_year(citation)
                if not parsed:
                    continue
                author = parsed["author"]
                year = parsed["year"]
                matched = False
                for line in ref_lower:
                    if year in line and author in line:
                        matched = True
                        break
                if not matched:
                    issues.append(
                        {
                            "issue_type": "Citation_Reference_Missing",
                            "severity": "Warning",
                            "evidence": citation,
                            "message": "作者-年份引用未在参考文献中找到对应条目",
                        }
                    )

class SemanticChecker:
    """
    语义判定总入口
    负责规则层面的格式校验，并与CV层结果融合
    """
    def __init__(self):
        self.llm_client = LLMClient()
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
        text_content = _resolve_text_content(content, layout_data)
        
        # 1. 规则校验 (各模块独立执行)
        self.typo_checker.check(text_content, issues)
        self.term_checker.check(text_content, issues)
        self.punct_checker.check(text_content, layout_data, issues)
        self.cite_checker.check(text_content, layout_data, issues)
        
        # 2. LLM 辅助扫描 (Gemini 1.5 Flash)
        # 利用长上下文能力辅助扫描复杂格式问题
        # Ref: 分工明细 - LLM Scanner
        try:
            llm_feedback = await asyncio.wait_for(
                self.llm_client.scan_document(text_content),
                timeout=LLM_TIMEOUT_SEC
            )
        except Exception:
            llm_feedback = ""
        
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
        counts = {"Critical": 0, "Warning": 0, "Info": 0}
        for issue in issues:
            level = issue.get("severity") or issue.get("level") or "Info"
            if level not in counts:
                level = "Info"
            counts[level] += 1
        critical = counts["Critical"]
        warning = counts["Warning"]
        info = counts["Info"]
        deduction = 15 * critical + 6 * math.sqrt(warning) + 2 * math.sqrt(info)
        score = 100 - int(round(deduction))
        return max(0, min(100, score))
