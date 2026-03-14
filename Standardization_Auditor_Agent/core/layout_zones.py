from typing import Dict, Any, List, Tuple
import re


def is_reference_title(text: str) -> bool:
    t = re.sub(r"\s+", "", (text or "").strip())
    t = t.rstrip("：:")
    return t in {"参考文献", "Reference", "References"}


def is_caption(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"[\.·…]{5,}\s*\d+\s*$", t):
        return False
    if re.search(r"\s{5,}\d+\s*$", t):
        return False
    # Relaxed rule: Allow standalone caption numbers (e.g. "图 2.2")
    # if re.fullmatch(r"(图|表|Figure|Fig\.|Table)\s*\d+(?:[.-]\d+)*\.?", t, re.IGNORECASE):
    #     return False
    m = re.match(r"^(图|表|Figure|Fig\.|Table)\s*\d+(?:[.-]\d+)*", t, re.IGNORECASE)
    if not m:
        return False
    rest = t[m.end():].strip()
    # Relaxed rule: Allow standalone caption numbers
    # if not rest:
    #     return False
    if re.search(r"[。！？]", t):
        return False
    if re.match(r"^(中|的)", rest):
        return False
    if re.search(r"(展示|所示|如图|见图|如表|见表)", t):
        if len(t) >= 20:
            return False
    if re.match(r"^(shows?|illustrates?)\\b", rest, re.IGNORECASE):
        return False
    return True


def is_formula_text(text: str) -> bool:
    # 1. Negative checks: Exclude common code patterns and text
    stripped = text.strip()
    if len(stripped) > 160:
        return False
    if re.search(r"[\.·…]{5,}\s*\d+\s*$", stripped):
        return False
    
    # Exclude C-style code endings or block starts
    if re.search(r"[;{}]$", stripped):
        return False
        
    # Exclude code keywords at start
    if re.match(r"^\s*(def|class|import|return|if|else|elif|for|while|try|except|finally|public|private|protected|void|int|float|double|char|bool|var|let|const|function|switch|case)\b", text):
        return False
        
    # Exclude comments
    if re.search(r"(//|/\*|#\s)", text):
        return False
        
    # Exclude snake_case variables (code style), but allow LaTeX like x_i, y_{max}
    # Only ban if both sides are multi-letter: my_var, max_len
    if re.search(r"\b[a-zA-Z]{2,}_[a-zA-Z]{2,}\b", text):
        return False

    if re.search(r"\b\w+\s*=\s*\w+\s*\(", stripped) and re.search(r"\w+\[[^\]]+\]", stripped):
        return False
    if re.search(r"\w+\[[^\]]+\]", stripped) and re.search(r"(?:==|!=|:=)", stripped):
        return False
    if "grid[" in stripped or "grid [" in stripped:
        return False
        
    # Exclude list items / bullets
    if re.match(r"^\s*(•|o|\*|-|\d+\.)\s", text):
        return False

    if ":=" in stripped and re.search(r"[A-Za-z]", stripped) and not re.search(r"[∑∫√≈≠≤≥±×÷α-ωΑ-Ω∂∇∞]", stripped):
        return False
        
    # Exclude URL / Email
    if re.search(r"(http[s]?://|@[\w.]+)", text):
        return False

    # Exclude lines with common text words (likely narrative text, not standalone formula)
    # Be careful not to ban variables like 'sin', 'cos', 'max', 'min', 'log', 'ln'
    # Common English stopwords: the, is, are, where, which, with, for, and, that, this, in, on, at, to, of, we, set, let, then, if, assume, given
    stopwords = r"\b(the|is|are|where|which|with|and|that|this|in|on|at|to|of|we|set|let|then|if|assume|given|step|note|figure|table|data|value|width|height|size|parameter)\b"
    if re.search(stopwords, text, re.IGNORECASE):
        # Exception: "Let x = 1" -> Text. "where x is..." -> Text.
        return False

    # Exclude Key-Value pairs with simple numbers (e.g. "Width = 100")
    # Matches "Word = Number [Unit]"
    if re.match(r"^[A-Za-z\s]+=\s*\d+(\.\d+)?\s*[a-zA-Z%]*$", stripped):
        return False

    # 2. Positive checks: Formula indicators
    # Greek letters, math operators (excluding standard keyboard ones like +, -, *, / which are ambiguous)
    # ≤, ≥, ≠, ≈, ±, ×, ÷, ∑, ∫, √, α-ω, ∂, ∇, ∞
    if re.search(r"[∑∫√≈≠≤≥±×÷α-ωΑ-Ω∂∇∞]", text):
        cn = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cn / max(len(stripped), 1) > 0.2 and not re.search(r"[=<>≤≥±×÷*/+\-≈≠]", text):
            return False
        return True
    
    # Standard formula numbering at end
    if re.fullmatch(r"(（\d+(?:[-.]\d+)*）|\(\d+(?:[-.]\d+)*\))", stripped):
        return False
    if re.search(r"(（\d+(?:[-.]\d+)*）|\(\d+(?:[-.]\d+)*\))$", stripped):
        return True
        
    # LaTeX syntax indicators
    if re.search(r"(\\[a-zA-Z]+|\^|\{.*\})", text):
        # \frac, \alpha, x^2, x_{i}
        return True

    # 3. Ambiguous symbols (=, <, >)
    # Only treat as formula if not looking like code
    if re.search(r"[=<>≈]", text):
        # If it has logical operators (==, !=, <=, >=, &&, ||, ->, =>), it's likely code or logic text
        if re.search(r"(==|!=|&&|\|\||->|=>)", text):
            return False
        if re.search(r"\w+\[[^\]]+\]", stripped) and re.search(r"\w+\s*=", stripped):
            return False
        cn = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cn / max(len(stripped), 1) > 0.2:
            return False
        if len(stripped) > 120:
            return False
        if not re.search(r"[\dA-Za-zα-ωΑ-Ω]", text):
            return False
        return True
    
    return False


def is_heading_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.match(r"^\d{2,4}\s*年(\s*\d{1,2}\s*月)?(\s*\d{1,2}\s*日)?", t):
        return False
    m = re.match(r"^(\d+(?:\.\d+)*)(?:[.、]|\s+)(.+)$", t)
    if m:
        rest = (m.group(2) or "").strip()
        if len(rest) < 2:
            return False
        if re.match(r"^(年|月|日)$", rest):
            return False
        return True
    if re.match(r"^第[一二三四五六七八九十百]+[章节]", t):
        return True
    return False


def classify_line_region(text: str, font_size: float, body_font: float, reference_mode: bool) -> str:
    if reference_mode:
        return "reference"
    if is_caption(text):
        return "chart"
    if is_formula_text(text):
        return "formula"
    if is_heading_text(text) or font_size >= body_font * 1.3:
        return "title"
    if re.search(r"\[\d+(?:,\s*\d+)*\]", text) and (len(text) < 100 or re.match(r"^\s*\[\d+\]", text)):
        return "citation"
    return "main"


def detect_reference_mode(lines: List[Dict[str, Any]]) -> bool:
    for line in lines:
        if is_reference_title(line.get("text", "")):
            return True
    return False


def assign_columns(blocks: List[Dict[str, Any]], page_width: float) -> List[List[Dict[str, Any]]]:
    if not blocks:
        return []
    mid = page_width * 0.5
    left = [b for b in blocks if b.get("bbox", [0, 0, 0, 0])[0] < mid]
    right = [b for b in blocks if b.get("bbox", [0, 0, 0, 0])[0] >= mid]
    if not left or not right:
        return [blocks]
    return [left, right]
