from typing import List, Dict, Any, Optional, Tuple
import asyncio
import base64
import math
import re
import json
from config import LLM_TIMEOUT_SEC
from .llm_client import LLMClient


def _element_get(element: Any, key: str) -> Any:
    if isinstance(element, dict):
        return element.get(key)
    return getattr(element, key, None)


def _is_likely_reference(element: Any) -> bool:
    """
    Check if an element is likely a reference item, either by region tag or heuristic content analysis.
    """
    region = _element_get(element, "region")
    if region == "reference":
        return True
    
    content = str(_element_get(element, "content") or "")
    if not content:
        return False
        
    # Heuristic: Starts with [N] or N. and contains reference keywords
    # Exclude typical section headers like "1. Introduction" (usually short, no vol/pp)
    
    # Special case: Isolated reference markers (e.g. "[14]") often found when layout analysis splits marker from text
    if re.match(r"^\s*\[\d+\]\s*$", content):
        return True

    if re.match(r"^\s*(\[\d+\]|\d+\.)", content):
        if len(content) > 20:
            # Common reference keywords (English & Chinese)
            # vol, pp, no, doi, http, isbn, issn, journal, conference, proceedings, trans, rev, arxiv
            # 卷, 期, 页, 学报, 会议, 论文集, 出版社
            # Standard GB/T 7714 type indicators: [J], [C], [D], [M], [EB/OL], etc.
            # Common abbreviations: et al., eds.
            # Added "Reference", "References" for title lines if they slip in
            pattern = r"(vol\.|pp\.|no\.|doi|http|isbn|issn|journal|conference|proceedings|trans\.|rev\.|arxiv|reference|references|学报|会议|论文集|出版社|pages|et al\.?|eds\.?|\[[A-Z]{1,2}(/[A-Z]+)?\])"
            if re.search(pattern, content, re.IGNORECASE):
                return True
            
            # Fallback: If no keywords, but looks like a standard reference (starts with [N] + space, long enough)
            # This catches references with just authors/titles and no "vol/pp" in the first block.
            # Require space after number to avoid [14]、 (enumeration without space)
            if len(content) > 40 and re.match(r"^\s*(\[\d+\]|\d+\.)\s", content):
                return True
    return False


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
    for text in reference_texts:
        # Handle multi-line elements (references might be merged in one block)
        for line in text.split('\n'):
            if not line.strip():
                continue
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


class TextPageMapper:
    """
    Helper class to map text indices back to page numbers.
    """
    def __init__(self, layout_data: Dict[str, Any]):
        self.elements = layout_data.get("elements", []) if isinstance(layout_data, dict) else []
        self.mapping = []  # List of (start_idx, end_idx, page_num)
        self.full_text = ""
        self._build()

    def _build(self):
        parts = []
        current_pos = 0
        for e in self.elements:
            text = _element_get(e, "content")
            pg = _element_get(e, "page_num")
            if text:
                text_str = str(text)
                length = len(text_str)
                # Map this segment to page
                self.mapping.append((current_pos, current_pos + length, pg))
                parts.append(text_str)
                current_pos += length + 1  # +1 for newline
        self.full_text = "\n".join(parts)

    def get_page_num(self, index: int) -> str:
        # Binary search could be better but linear is fine for now
        for start, end, pg in self.mapping:
            if start <= index < end:
                return str(pg) if pg is not None else "?"
        return "?"

    def get_page_range(self, start_idx: int, end_idx: int) -> str:
        pages = set()
        for start, end, pg in self.mapping:
            # Check overlap
            if max(start, start_idx) < min(end, end_idx):
                if pg is not None:
                    pages.add(str(pg))
        
        if not pages:
            return "?"
        
        # Try to sort numerically
        try:
            sorted_pages = sorted(list(pages), key=lambda x: int(x) if str(x).isdigit() else 9999)
        except:
            sorted_pages = sorted(list(pages))

        if not sorted_pages:
            return "?"
            
        if len(sorted_pages) == 1:
            return str(sorted_pages[0])
        else:
            return f"{sorted_pages[0]}-{sorted_pages[-1]}"


import difflib

class TypoChecker:
    """
    语义判定 - 错别字红线判定
    对应《分工明细》二、语义判定 - 阶段2
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_typos_total = config.get("max_typos_total_warning", 10)
        self.critical_keywords = config.get("critical_keywords", [])

    def check(self, content: str, issues: List[Dict], mapper: Optional['TextPageMapper'] = None):
        """
        1. 集成中文分词/错别字检测工具
        2. 上下文语义纠错 (排除专业名词歧义)
        3. 红线触发逻辑: 全文>10个 -> Warning; 关键术语错字 -> Critical
        """
        if not content:
            return

        typo_count = 0
        found_typos = []

        # 1. Critical Keywords Check (Fuzzy Matching)
        # Find all word occurrences with their positions
        word_matches = list(re.finditer(r"\b\w+\b", content))
        words = [m.group() for m in word_matches]
        
        # 对每个关键术语，寻找文本中相似但不完全相同的词
        for keyword in self.critical_keywords:
            # 忽略大小写比较，如果 text 中有 deep learning 而 keyword 是 Deep Learning
            # 这其实由 TerminologyChecker 处理。
            # TypoChecker 处理的是拼写错误，如 "TensorFlow" 写成 "TensorFlwo"
            
            # 这里使用 difflib 查找相似词
            # 为了性能，只对长度相近的词进行比较
            candidates = [w for w in words if abs(len(w) - len(keyword)) <= 2]
            # 提高匹配阈值，避免将 "神经网络" 误判为 "卷积神经网络" 的错别字
            matches = difflib.get_close_matches(keyword, candidates, n=3, cutoff=0.85)
            
            for match in matches:
                if match != keyword:
                    # 排除掉仅仅是大小写不同的情况 (交给 TerminologyChecker)
                    if match.lower() == keyword.lower():
                        continue
                    
                    # 排除常见复数形式 (简单的 heuristic)
                    if match == keyword + "s" or match == keyword + "es":
                        continue
                    
                    # Find specific occurrences
                    instances = [m for m in word_matches if m.group() == match]
                    for instance in instances:
                        pg = "?"
                        if mapper:
                            pg = mapper.get_page_num(instance.start())
                            
                        issues.append({
                            "issue_type": "Critical_Keyword_Typo",
                            "severity": "Critical",
                            "evidence": match,
                            "page_num": pg,
                            "message": f"关键术语拼写错误: '{match}' 应为 '{keyword}'"
                        })
                        typo_count += 1
                        found_typos.append(match)

        # 2. 通用错别字检测 (模拟/占位)
        # 在没有 NLP 库的情况下，暂时只统计上述发现的 Critical Typos
        # 如果未来集成了 pycorrector，这里可以扩展
        
        # 3. 阈值检查
        if typo_count > self.max_typos_total:
            issues.append({
                "issue_type": "Typo_Limit_Exceeded",
                "severity": "Warning",
                "evidence": f"Found {typo_count} typos (including: {', '.join(found_typos[:3])}...)",
                "message": f"全文错别字数量超过红线 ({self.max_typos_total}个)"
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

    def check(self, content: str, issues: List[Dict], mapper: Optional['TextPageMapper'] = None):
        """
        1. 提取专有名词，建立临时术语库
        2. 检测写法不一致 (如 'Deep Learning' vs 'deep-learning')
        3. 生成统一建议
        """
        if not content:
            return
        
        # Check canonical terms consistency
        for canonical, variants in self.terms.items():
            allowed_forms = {canonical}
            if variants:
                allowed_forms.update(variants)
            
            # Escape regex characters in the term
            # Use \b boundaries for English words
            if re.search(r"[A-Za-z]", canonical):
                escaped_term = re.escape(canonical)
                # Replace escaped spaces with \s+ to match varying whitespace
                pattern = r"\b" + escaped_term.replace(r"\ ", r"\s+") + r"\b"
            else:
                pattern = re.escape(canonical)
                
            # Find ALL occurrences (case-insensitive)
            matches = re.finditer(pattern, content, flags=re.IGNORECASE)
            
            # Check if any found match is NOT in the allowed set
            inconsistent_usages = set()
            found_pages = set()
            for m in matches:
                usage = m.group()
                if usage not in allowed_forms:
                    inconsistent_usages.add(usage)
                    if mapper:
                        found_pages.add(mapper.get_page_num(m.start()))
            
            if inconsistent_usages:
                pg_str = "?"
                if found_pages:
                    sorted_pgs = sorted(list(found_pages), key=lambda x: int(x) if x.isdigit() else 999)
                    pg_str = ", ".join(sorted_pgs)
                    
                issues.append(
                    {
                        "issue_type": "Terminology_Inconsistent",
                        "severity": "Warning",
                        "evidence": ", ".join(inconsistent_usages),
                        "page_num": pg_str,
                        "message": f"术语写法不一致，建议统一为：{canonical}",
                    }
                )

        # Check forbidden variants
        for canonical, forbidden in self.forbidden_variants.items():
            found_forbidden = []
            found_pages = set()
            for form in forbidden or []:
                if re.search(r"[A-Za-z]", form):
                    pattern_str = r"\b" + re.escape(form) + r"\b"
                    matches = list(re.finditer(pattern_str, content, flags=re.IGNORECASE))
                else:
                    pattern_str = re.escape(form)
                    matches = list(re.finditer(pattern_str, content))
                
                if matches:
                    found_forbidden.append(form)
                    for m in matches:
                        if mapper:
                            found_pages.add(mapper.get_page_num(m.start()))
                            
            if found_forbidden:
                pg_str = "?"
                if found_pages:
                    sorted_pgs = sorted(list(found_pages), key=lambda x: int(x) if x.isdigit() else 999)
                    pg_str = ", ".join(sorted_pgs)
                    
                issues.append(
                    {
                        "issue_type": "Terminology_Forbidden",
                        "severity": "Warning",
                        "evidence": ", ".join(found_forbidden),
                        "page_num": pg_str,
                        "message": f"检测到不规范术语写法，建议使用：{canonical}",
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
        self.check_position = config.get("check_citation_position", True)

    def check(self, content: str, layout_data: Dict[str, Any], issues: List[Dict], mapper: Optional['TextPageMapper'] = None):
        """
        1. 杜绝中英文标点混用
        2. 标点位置错误 (如引用标注在标点外)
        """
        if not content:
            return

        # Use elements directly to get page numbers
        elements = layout_data.get("elements", []) if isinstance(layout_data, dict) else []

        # 1. Mixed Punctuation Check
        if not self.allow_mixed:
            # 1a. General punctuation (excluding .)
            cn_en_punct_pattern = re.compile(r"[\u4e00-\u9fff]\s*[,?!;:\(\)]")
            # 1b. Check for '.' specifically, avoiding TOC leaders
            cn_en_dot_pattern = re.compile(r"[\u4e00-\u9fff]\s*\.(?!\s*[\.\d])")
            # 1c. English text using Chinese punctuation
            en_cn_punct_pattern = re.compile(r"[a-zA-Z]\s*[，。？！；：]")
            
            for e in elements:
                if _is_likely_reference(e):
                    continue
                text_val = _element_get(e, "content")
                pg = _element_get(e, "page_num") or "?"
                region = _element_get(e, "region") or ""
                
                if text_val:
                    segment = str(text_val)
                    if region == "chart":
                        continue
                    if re.search(r"http[s]?://|@[A-Za-z0-9_.-]+", segment):
                        continue
                    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", segment))
                    en_count = len(re.findall(r"[A-Za-z]", segment))
                    num_count = len(re.findall(r"\d", segment))
                    total_alpha = cjk_count + en_count + num_count
                    cjk_ratio = cjk_count / total_alpha if total_alpha > 0 else 0.0
                    en_ratio = en_count / total_alpha if total_alpha > 0 else 0.0
                    for m in cn_en_punct_pattern.finditer(segment):
                        if cjk_ratio < 0.5:
                            continue
                        issues.append({
                            "issue_type": "Punctuation_Mixed",
                            "severity": "Info",
                            "evidence": m.group(),
                            "page_num": pg,
                            "message": "中文文本使用了英文标点",
                        })
                    
                    for m in cn_en_dot_pattern.finditer(segment):
                        if cjk_ratio < 0.5:
                            continue
                        issues.append({
                            "issue_type": "Punctuation_Mixed",
                            "severity": "Info",
                            "evidence": m.group(),
                            "page_num": pg,
                            "message": "中文文本使用了英文标点(.)",
                        })

                    for m in en_cn_punct_pattern.finditer(segment):
                        if en_ratio < 0.5:
                            continue
                        issues.append({
                            "issue_type": "Punctuation_Mixed",
                            "severity": "Info",
                            "evidence": m.group(),
                            "page_num": pg,
                            "message": "英文文本使用了中文标点",
                        })

        # 2. Citation Position Check
        if self.check_position:
            punct_cite_pattern = re.compile(r"([，。,\.])\s*(\[\d+\])")
            
            for e in elements:
                if _is_likely_reference(e):
                    continue
                text_val = _element_get(e, "content")
                pg = _element_get(e, "page_num") or "?"
                
                if text_val:
                    segment = str(text_val)
                    for m in punct_cite_pattern.finditer(segment):
                        issues.append({
                            "issue_type": "Citation_Position_Inconsistent",
                            "severity": "Info",
                            "evidence": m.group(),
                            "page_num": pg,
                            "message": "引用标注位置错误 (应置于标点符号之前)",
                        })


class CitationChecker:
    """
    语义判定 - 引用格式语义校验
    对应《分工明细》二、语义判定 - 阶段3
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.style = config.get("style", "IEEE")

    def check(self, content: str, layout_data: Dict[str, Any], issues: List[Dict], mapper: Optional['TextPageMapper'] = None):
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
            if _is_likely_reference(e):
                text_value = _element_get(e, "content")
                if text_value:
                    reference_texts.append(str(text_value))
        
        # Sort or process reference texts if needed (layout analysis might be out of order?)
        # For now, assume sequential.
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
            # Re-scan to find locations
            for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
                citation_text = m.group(0)
                nums_in_cite = re.findall(r"\d+", citation_text)
                missing_nums = [n for n in nums_in_cite if n not in ref_nums]
                
                if missing_nums:
                    pg = mapper.get_page_num(m.start()) if mapper else "?"
                    ref_pages = set()
                    for e in elements:
                        if _is_likely_reference(e):
                            p = _element_get(e, "page_num")
                            if p is not None:
                                ref_pages.add(p)
                    if pg in ref_pages:
                        continue
                    for missing in missing_nums:
                        issues.append({
                            "issue_type": "Citation_Reference_Missing",
                            "severity": "Info",
                            "evidence": f"[{missing}]",
                            "page_num": pg,
                            "message": "引用标注未在参考文献中找到对应编号",
                        })

        if author_year_citations and reference_texts:
            ref_lower = [r.lower() for r in reference_texts]
            
            # Re-scan to find locations
            for m in re.finditer(r"\(([^()]*\d{4}[a-z]?[^()]*)\)", text):
                citation_inner = m.group(1)
                if not re.search(r"[A-Za-z]", citation_inner):
                    continue
                    
                parsed = _parse_author_year(citation_inner)
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
                    pg = mapper.get_page_num(m.start()) if mapper else "?"
                    ref_pages = set()
                    for e in elements:
                        if _is_likely_reference(e):
                            p = _element_get(e, "page_num")
                            if p is not None:
                                ref_pages.add(p)
                    if pg in ref_pages:
                        continue
                    issues.append(
                        {
                            "issue_type": "Citation_Reference_Missing",
                            "severity": "Info",
                            "evidence": m.group(0),
                            "page_num": pg,
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
        self.rules = {}
        
        # Initialize sub-checkers with empty rules initially
        self.typo_checker = TypoChecker({})
        self.term_checker = TerminologyChecker({})
        self.punct_checker = PunctuationChecker({})
        self.cite_checker = CitationChecker({})

    def update_rules(self, rules: Dict[str, Any]):
        """
        Update rules for all sub-checkers
        """
        self.rules = rules
        # Update sub-checkers with specific rule sections
        # Assuming rules structure matches sub-checker expectations
        self.typo_checker.config = rules.get("typo_check", {})
        self.term_checker.config = rules.get("terminology_check", {})
        self.punct_checker.config = rules.get("punctuation_check", {})
        self.cite_checker.config = rules.get("citation_check", {})
        
        # Re-initialize or update internal config dependent logic if needed
        # For example, TypoChecker reads max_typos_total in __init__
        self.typo_checker = TypoChecker(self.typo_checker.config)
        self.term_checker = TerminologyChecker(self.term_checker.config)
        self.punct_checker = PunctuationChecker(self.punct_checker.config)
        self.cite_checker = CitationChecker(self.cite_checker.config)

    def _chunk_text(self, text: str, chunk_size: int = 5000, overlap: int = 500) -> List[str]:
        """
        Split text into chunks respecting paragraph boundaries.
        If a paragraph is too long, split it by character count.
        """
        if not text:
            return []
            
        paragraphs = text.split('\n')
        chunks = []
        
        start_idx = 0
        while start_idx < len(paragraphs):
            current_len = 0
            end_idx = start_idx
            
            # Expand end_idx until chunk_size is reached
            while end_idx < len(paragraphs):
                p_len = len(paragraphs[end_idx]) + 1 # +1 for newline
                
                # Check if adding this paragraph exceeds limit
                if current_len + p_len > chunk_size:
                    if current_len == 0:
                        # Single huge paragraph - split by character count
                        para = paragraphs[end_idx]
                        s = 0
                        while s < len(para):
                            e = s + chunk_size
                            chunks.append(para[s:e])
                            if e >= len(para):
                                break
                            s = e - overlap
                        
                        start_idx += 1
                        end_idx = start_idx # Signal processed
                        break 
                    else:
                        # Stop here, don't include this paragraph in current chunk
                        break
                
                current_len += p_len
                end_idx += 1
            
            # If we processed a huge paragraph (current_len == 0 but incremented start_idx), continue
            if current_len == 0:
                if start_idx < len(paragraphs):
                    continue
                else:
                    break
                 
            # If we formed a chunk
            if end_idx > start_idx:
                chunk_text = "\n".join(paragraphs[start_idx:end_idx])
                chunks.append(chunk_text)
            
            if end_idx == len(paragraphs):
                break
                
            # Calculate next start_idx based on overlap (backtrack from end_idx)
            overlap_len = 0
            next_start = end_idx
            # Try to keep at least 'overlap' characters from the end of current chunk
            while next_start > start_idx:
                p_len = len(paragraphs[next_start-1]) + 1
                if overlap_len + p_len > overlap:
                    break
                overlap_len += p_len
                next_start -= 1
            
            # Ensure progress
            if next_start == start_idx:
                next_start += 1
                
            start_idx = next_start
            
        return chunks

    async def check(self, content: str, layout_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行语义校验的主流程
        """
        # 支持规则热更新 (可选，每次请求检查更新)
        # self.rule_engine.reload() 
        
        issues = []
        
        # Initialize Mapper
        mapper = TextPageMapper(layout_data)
        # Use mapper's text to ensure consistency with indices
        text_content = mapper.full_text
        if not text_content:
            # Fallback if mapper produced empty text (e.g. no elements)
            text_content = _resolve_text_content(content, layout_data)
        
        print(f"DEBUG: text_content length: {len(text_content)}")
        
        # 1. 规则校验 (各模块独立执行)
        try:
            print("DEBUG: Running typo_checker...", flush=True)
            self.typo_checker.check(text_content, issues, mapper)
        except Exception as e:
            print(f"ERROR: typo_checker failed: {e}", flush=True)

        try:
            print("DEBUG: Running term_checker...", flush=True)
            self.term_checker.check(text_content, issues, mapper)
        except Exception as e:
            print(f"ERROR: term_checker failed: {e}", flush=True)

        try:
            print("DEBUG: Running punct_checker...", flush=True)
            self.punct_checker.check(text_content, layout_data, issues, mapper)
        except Exception as e:
            print(f"ERROR: punct_checker failed: {e}", flush=True)

        try:
            print("DEBUG: Running cite_checker...", flush=True)
            self.cite_checker.check(text_content, layout_data, issues, mapper)
            print("DEBUG: cite_checker finished.", flush=True)
        except Exception as e:
            print(f"ERROR: cite_checker failed: {e}", flush=True)
        
        # 2. LLM 辅助扫描 (Gemini 1.5 Flash / Qwen)
        # 利用长上下文能力辅助扫描复杂格式问题
        # Ref: 分工明细 - LLM Scanner
        if self.llm_client.provider == "none":
            print("WARNING: LLM provider not configured or API Key missing. Skipping LLM scan.", flush=True)
            llm_feedback = ""
            all_llm_issues = []
        else:
            print(f"DEBUG: Starting LLM scan with provider: {self.llm_client.provider}...", flush=True)
            llm_feedback = ""
            all_llm_issues = []
            
            try:
                # Process text in chunks for LLM
                # Increase chunk size to 15000 to reduce calls and preserve context (as requested by user)
                # Modern LLMs (Gemini/Qwen) handle large context well.
                chunks = self._chunk_text(text_content, chunk_size=15000, overlap=500)
                print(f"DEBUG: Chunks created: {len(chunks)}", flush=True)
                
                feedback_parts = []
                last_pos = 0
                
                for i, chunk in enumerate(chunks):
                    print(f"DEBUG: Processing chunk {i+1}/{len(chunks)}... Length: {len(chunk)}", flush=True)
                    
                    # Calculate page range for this chunk
                    page_range = "?"
                    start_pos = text_content.find(chunk, last_pos)
                    # If not found (shouldn't happen), try from 0
                    if start_pos == -1:
                        start_pos = text_content.find(chunk)
                    
                    if start_pos != -1:
                        end_pos = start_pos + len(chunk)
                        page_range = mapper.get_page_range(start_pos, end_pos)
                        # Advance last_pos, but allow for overlap (next chunk starts before this one ends)
                        # We just need to ensure we don't find the SAME chunk instance again if there are duplicates?
                        # Since chunks are sequential, simple find from last_pos is usually safe.
                        # Ideally last_pos should track 'processed up to'.
                        # But chunks overlap. Next chunk will start around 'end_pos - overlap'.
                        # So let's update last_pos to start_pos + 1 to be safe.
                        last_pos = start_pos + 1
                    
                    try:
                        chunk_feedback = await self.llm_client.scan_document(chunk)
                        if chunk_feedback:
                            # Parse issues from this chunk
                            chunk_issues, chunk_summary = self._parse_llm_response(chunk_feedback)
                            
                            # Use summary if available, otherwise raw feedback
                            if chunk_summary:
                                feedback_parts.append(chunk_summary)
                            else:
                                feedback_parts.append(chunk_feedback)
                                
                            # Tag issues as from LLM and add page range
                            for issue in chunk_issues:
                                issue["source"] = "LLM"
                                if "page_num" not in issue or issue["page_num"] == "?":
                                    issue["page_num"] = page_range
                                    
                            all_llm_issues.extend(chunk_issues)
                    except Exception as e:
                        print(f"ERROR: Chunk {i+1} processing failed: {e}", flush=True)
                        # Log error but continue with other chunks
                        pass


                
                # Aggregate results
                llm_feedback = "\n".join(feedback_parts)
                print("DEBUG: LLM scan completed.", flush=True)
            except Exception as e:
                print(f"ERROR: LLM scan failed: {e}", flush=True)
                import traceback
                traceback.print_exc()
        
        # Merge LLM issues into main issues list
        if all_llm_issues:
            issues.extend(all_llm_issues)
        
        # 3. 结果融合与去重
        # 避免视觉层和语义层对同一问题的重复标注
        # Ref: 分工明细 - 阶段4: 结果去重逻辑
        
        return {
            "semantic_issues": issues,
            "llm_feedback": llm_feedback,
            "score": self._calculate_score(issues)
        }

    def _parse_llm_response(self, response_text: str) -> Tuple[List[Dict], str]:
        """
        Parses the LLM response which is expected to be a JSON string.
        Returns a tuple of (issues found by LLM, summary string).
        """
        issues = []
        summary = ""
        try:
            # Clean response text
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            parsed = json.loads(cleaned)
            
            # Handle different response formats
            if isinstance(parsed, dict):
                issues = parsed.get("issues", [])
                summary = parsed.get("summary", "")
            elif isinstance(parsed, list):
                # If root is a list of issues
                issues = parsed
                
        except json.JSONDecodeError:
            # Fallback: try to find JSON object using regex if mixed with text
            try:
                match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        issues = parsed.get("issues", [])
                        summary = parsed.get("summary", "")
            except:
                pass
            
        # Ensure issues is a list of dicts
        if not isinstance(issues, list):
            issues = []
            
        # Post-process issues to handle false positives from LLM
        filtered_issues = []
        for issue in issues:
            # Fix for "Citation_Placeholder" being too aggressive on isolated lines
            # If evidence looks like a valid citation (e.g. [12], [21,23]), it's likely a layout/parsing artifact, not a missing placeholder.
            if issue.get("issue_type") == "Citation_Placeholder":
                evidence = issue.get("evidence", "").strip()
                msg = issue.get("message", "")
                
                # Condition 1: Evidence is a valid citation pattern
                is_valid_citation = bool(re.match(r"^\[[\d,\s-]+\]$", evidence))
                
                # Condition 2: Message explicitly mentions "isolated" or "single line" citations
                # and contains citation-like patterns
                is_isolated_msg = ("孤立" in msg or "单独成行" in msg) and re.search(r"\[\d+(?:,\s*\d+)*\]", msg)
                
                if is_valid_citation or is_isolated_msg:
                    issue["severity"] = "Info"
                    issue["message"] += " (疑似排版或解析造成的孤立行，非内容缺失)"
                    issue["issue_type"] = "Citation_Layout_Check"
            
            filtered_issues.append(issue)
            
        return filtered_issues, summary

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
        # Relaxed scoring: Reduced weights to avoid 0 scores for initial testing
        # Old: 15 * critical + 6 * sqrt(warning) + 2 * sqrt(info)
        deduction = 5 * critical + 2 * math.sqrt(warning) + 0.5 * math.sqrt(info)
        score = 100 - int(round(deduction))
        return max(0, min(100, score))
