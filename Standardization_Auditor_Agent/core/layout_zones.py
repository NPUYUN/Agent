from typing import Dict, Any, List, Tuple
import re


def is_reference_title(text: str) -> bool:
    t = text.strip().replace(" ", "")
    return t in {"参考文献", "参考文献：", "Reference", "References"}


def is_caption(text: str) -> bool:
    # Use re.IGNORECASE to support both "Table" and "table"
    return re.match(r"^(图|表|Figure|Fig\.|Table)\s*\d+", text, re.IGNORECASE) is not None


def is_formula_text(text: str) -> bool:
    # 1. Negative checks: Exclude common code patterns and text
    stripped = text.strip()
    
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
        
    # Exclude list items / bullets
    if re.match(r"^\s*(•|o|\*|-|\d+\.)\s", text):
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
        return True
    
    # Standard formula numbering at end
    if re.search(r"(（\d+(?:[-.]\d+)*）|\(\d+(?:[-.]\d+)*\))$", text):
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
        
        # Must contain some math-like structure?
        # If it's just "x = 1", it's a formula (scalar assignment).
        # But we filtered out "Let x = 1" and "Width = 100".
        # So "x = 1" or "E = mc^2" should pass.
        return True
    
    return False


def is_heading_text(text: str) -> bool:
    if re.match(r"^(\d+(?:\.\d+)*)[.\s、]", text):
        return True
    if re.match(r"^第[一二三四五六七八九十百]+[章节]", text):
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
