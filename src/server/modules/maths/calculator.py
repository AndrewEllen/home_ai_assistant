# modules/maths/calculator.py
import re, ast, operator, math

# ---------------- Safe evaluator ----------------
_ops = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_funcs = {k: getattr(math, k) for k in ("sqrt","sin","cos","tan","log","log10","exp","ceil","floor","fabs")}
_funcs.update({"abs": abs, "round": round})
_consts = {"pi": math.pi, "e": math.e, "tau": math.tau}

class SafeEval(ast.NodeVisitor):
    def visit(self, node):
        if isinstance(node, ast.Expression): return self.visit(node.body)
        if isinstance(node, ast.Num): return node.n
        if isinstance(node, ast.Constant) and isinstance(node.value,(int,float)): return node.value
        if isinstance(node, ast.BinOp): return _ops[type(node.op)](self.visit(node.left), self.visit(node.right))
        if isinstance(node, ast.UnaryOp): return _ops[type(node.op)](self.visit(node.operand))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _funcs: raise ValueError("bad func")
            args = [self.visit(a) for a in node.args]
            return _funcs[node.func.id](*args)
        if isinstance(node, ast.Name):
            if node.id in _consts: return _consts[node.id]
            raise ValueError("bad name")
        if isinstance(node, ast.Tuple): return tuple(self.visit(e) for e in node.elts)
        raise ValueError("bad expr")

def safe_eval(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    return SafeEval().visit(tree)

# ---------------- Number words ----------------
_units = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
    "ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,
    "seventeen":17,"eighteen":18,"nineteen":19,
    "twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90,
}
_scales = {
    "hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000, "quadrillion": 1_000_000_000_000_000,
    "quintillion": 1_000_000_000_000_000_000, "sextillion": 1_000_000_000_000_000_000_000,
    "septillion": 1_000_000_000_000_000_000_000_000, "octillion": 1_000_000_000_000_000_000_000_000_000,
    "nonillion": 1_000_000_000_000_000_000_000_000_000_000, "decillion": 10**33,
}
_frac_words = {
    "half": 1/2, "third": 1/3, "quarter": 1/4, "fourth": 1/4, "fifth": 1/5,
    "sixth": 1/6, "seventh": 1/7, "eighth": 1/8, "ninth": 1/9, "tenth": 1/10,
}
_scales_plural = {k + "s": v for k, v in _scales.items()}
_frac_words_plural = {k + "s": v for k, v in _frac_words.items()}
_all_scales = {**_scales, **_scales_plural}
_all_fracs = {**_frac_words, **_frac_words_plural}

def _is_num_word(w: str) -> bool:
    return (
        w in _units or w in _all_scales or w in _all_fracs
        or w in ("and","a","an","point","negative","positive")
        or w.isdigit() or re.fullmatch(r"-?\d+(?:\.\d+)?", w) is not None
    )

def words_to_number(text: str) -> str:
    """
    Convert robustly:
      'negative ten' -> '-10'
      'one hundred million and two' -> '100000002'
      'two and a half' -> '2.5'
      'three quarters' -> '0.75'
      'twenty-one' -> '21'
    Non-number words are preserved.
    """
    s = text.lower()
    # split only word-word hyphens; keep numeric negatives
    s = re.sub(r"(?<=\b[a-z])-(?=[a-z]\b)", " ", s)
    s = re.sub(r"(?<=\d),(?=\d)", "", s)  # remove digit group commas

    tokens = re.split(r"(\W+)", s)  # keep separators
    out = []
    total = 0
    current = 0
    neg_pending = False
    in_number = False
    decimal_mode = False
    dec_digits = []
    last_was_unit_int = False  # for "three quarters" -> 3 * 1/4

    def flush():
        nonlocal total, current, neg_pending, in_number, decimal_mode, dec_digits, last_was_unit_int
        if not in_number:
            return
        val = float(total + current)
        if decimal_mode and dec_digits:
            val = float(total + current) + float("0." + "".join(dec_digits))
        if neg_pending:
            val = -val
        out.append(str(int(val)) if float(val).is_integer() else str(val))
        total = 0
        current = 0
        neg_pending = False
        in_number = False
        decimal_mode = False
        dec_digits = []
        last_was_unit_int = False

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if re.fullmatch(r"\W+", tok):
            # spaces: keep; punctuation: boundary
            if tok.isspace():
                out.append(tok); i += 1; continue
            flush(); out.append(tok); i += 1; continue

        w = tok.strip().lower()
        if not w:
            i += 1; continue

        # sign words starting a number phrase
        if w == "negative" and not in_number:
            j = i + 1
            while j < len(tokens) and re.fullmatch(r"\W+", tokens[j]): j += 1
            if j < len(tokens) and _is_num_word(tokens[j].strip().lower()):
                neg_pending = True; in_number = True; i += 1; continue

        if w == "positive" and not in_number:
            j = i + 1
            while j < len(tokens) and re.fullmatch(r"\W+", tokens[j]): j += 1
            if j < len(tokens) and _is_num_word(tokens[j].strip().lower()):
                neg_pending = False; in_number = True; i += 1; continue

        # direct numeric token
        if re.fullmatch(r"-?\d+(?:\.\d+)?", w):
            val = float(w)
            if not in_number:
                in_number = True
                if val < 0: neg_pending = True; val = -val
                current = int(val) if val.is_integer() else val
            else:
                if isinstance(current, float) and not float(current).is_integer():
                    flush(); out.append(tok)
                else:
                    current += int(val) if float(val).is_integer() else val
            last_was_unit_int = isinstance(current, (int, float)) and float(current).is_integer()
            i += 1; continue

        # fractions
        if w in _all_fracs:
            frac = _all_fracs[w]
            if not in_number:
                in_number = True; current = frac
            else:
                if decimal_mode:
                    flush(); out.append(tok)
                else:
                    # "three quarters" -> multiplier semantics
                    if last_was_unit_int and total == 0:
                        current = float(current) * frac
                    else:
                        current = float(total + current) + frac
                        total = 0
            last_was_unit_int = False
            i += 1; continue

        # articles inside number phrase
        if w in ("a","an"):
            j = i + 1
            while j < len(tokens) and re.fullmatch(r"\W+", tokens[j]): j += 1
            nxt = tokens[j].strip().lower() if j < len(tokens) else ""
            if nxt in _all_fracs:
                if not in_number: in_number = True
                # 'a half' -> handled when next token (half) arrives
                i += 1; continue
            if nxt in _all_scales or nxt in _units:
                if not in_number: in_number = True
                current += 1; last_was_unit_int = True; i += 1; continue
            flush(); out.append(tok); i += 1; continue

        if w == "and" and in_number:
            i += 1; continue

        if w == "point" and in_number and not decimal_mode:
            decimal_mode = True; dec_digits = []
            j = i + 1
            while j < len(tokens):
                t = tokens[j]
                if re.fullmatch(r"\W+", t): j += 1; continue
                ww = t.strip().lower()
                if ww in _units: dec_digits.append(str(_units[ww])); j += 1; continue
                if ww.isdigit(): dec_digits.append(ww); j += 1; continue
                break
            i = j; continue

        if w in _units:
            current += _units[w]; in_number = True
            last_was_unit_int = True
            i += 1; continue

        if w in _all_scales:
            scale = _all_scales[w]
            if scale == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale; current = 0
            in_number = True; last_was_unit_int = False
            i += 1; continue

        # boundary on any other word
        flush(); out.append(tok); i += 1

    flush()
    return "".join(out)

# ---------------- Phrase normalization ----------------
# Order matters: more specific first.
_pre_rewrites = [
    (r"\babsolute\s+difference\s+between\s+(.+?)\s+and\s+(.+?)\b", r"abs(\1 - \2)"),
    (r"\babsolute\s+difference\s+of\s+(.+?)\s+and\s+(.+?)\b", r"abs(\1 - \2)"),
    (r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)\b", r"(\1 - \2)"),

    (r"\bsubtract\s+(.+?)\s+from\s+(.+?)\b", r"(\2 - \1)"),
    (r"\btake\s+(.+?)\s+away\s+from\s+(.+?)\b", r"(\2 - \1)"),
    (r"\badd\s+(.+?)\s+to\s+(.+?)\b", r"(\2 + \1)"),
    (r"\bdivide\s+(.+?)\s+by\s+(.+?)\b", r"(\1 / \2)"),
    (r"\bmultiply\s+(.+?)\s+by\s+(.+?)\b", r"(\1 * \2)"),
    (r"\b(.+?)\s+less\s+than\s+(.+?)\b", r"(\2 - \1)"),

    # cube root
    (r"\bcube\s+root\s+of\s+([^\(\)]+)", r"(\1) ** (1/3)"),
]

_replacements = [
    # brackets
    (r"\b(open|left)\s+(?:bracket|parenthesis|paren)\b", "("),
    (r"\b(close|right)\s+(?:bracket|parenthesis|paren)\b", ")"),

    # addition
    (r"\bplus\b", "+"),
    (r"\badd(ed|ing)?\b", "+"),
    (r"\bsum\s+of\b", "+"),

    # subtraction
    (r"\bminus\b", "-"),
    (r"\btake\s+away\b", "-"),
    (r"\bsubtract(ed|ing)?\b", "-"),
    (r"\bless\b", "-"),

    # multiplication
    (r"\b(times|multiplied\s+by|x)\b", "*"),
    (r"\bmultiply(ed|ing)?\b", "*"),

    # division
    (r"\b(divided\s+by|over)\b", "/"),
    (r"\bdivide(ed|ing)?\b", "/"),

    # powers
    (r"\b(to\s+the\s+power\s+of|power\s+of|raised\s+to)\b", "**"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),

    # roots
    (r"\bsquare\s+root\s+of\b", "sqrt("),

    # modulo
    (r"\bmod(?:ulo)?\b", "%"),

    # common STT typo
    (r"(?<=\d)\s+mins\s+(?=\d)", " - "),

    # percentages
    (r"\bpercent\s+of\b", "% of"),
    (r"\bpercent\b", "%"),
]

# ---------------- Filler stripping + windowing ----------------
# Strip lead prompts; not critical, windowing handles "extra words before math".
_LEAD_STRIP_SEQ = re.compile(
    r"""^\s*(?:hey\s+\w+[,\s]+)?\s*
        (?:
           (?:what\s+is|what(?:'s|s)|how\s+much(?:\s+is)?|how\s+many|
            calculate|compute|work\s*out|solve|evaluate|equals?|equal\s+to|
            give\s+me|find|tell\s+me|can\s+you|could\s+you|please|show\s+me|is)
           \s+
        )+
    """, re.I | re.X
)
_TRAIL_TRASH_RE = re.compile(r"[?=\s]+$")
_MATH_CHUNK_RE = re.compile(r"[0-9a-z\.\(\)\+\-\*/%\s\^]+")

# window finder for math-y span inside noisy sentences
_WORD_NUM_PATTERN = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|million|billion|trillion|quadrillion|quintillion|"
    r"sextillion|septillion|octillion|nonillion|decillion|"
    r"half|third|quarter|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"halves|thirds|quarters|fourths|fifths|sixths|sevenths|eighths|ninths|tenths|"
    r"point|and|a|an|negative|positive"
)
_OP_WORD_PATTERN = (
    r"plus|add(?:ed|ing)?|sum\s+of|minus|take\s+away|subtract(?:ed|ing)?|less|"
    r"times|multipl(?:y|ied)\s+by|x|divided\s+by|divide(?:d|ing)?|over|"
    r"to\s+the\s+power\s+of|power\s+of|raised\s+to|squared|cubed|"
    r"square\s+root\s+of|cube\s+root\s+of|mod(?:ulo)?|percent(?:\s+of)?"
)
_MATH_WINDOW_TOKEN = re.compile(
    rf"(?:\b(?:{_WORD_NUM_PATTERN}|{_OP_WORD_PATTERN})\b|[0-9\.\(\)\+\-\*/%\^])",
    re.I,
)

def _extract_best_math_window(text: str) -> str | None:
    """
    Merge adjacent mathy tokens separated only by spaces/commas.
    Fixes cases like '1 million - 1' where basic findall splits into two matches.
    Also ignores any leading chatter safely.
    """
    matches = list(_MATH_WINDOW_TOKEN.finditer(text))
    if not matches:
        return None
    # Build contiguous spans by merging when only [\s,]+ lies between tokens
    spans = []
    start = matches[0].start()
    end = matches[0].end()
    for m in matches[1:]:
        gap = text[end:m.start()]
        if re.fullmatch(r"[\s,]+", gap or ""):
            end = m.end()
        else:
            spans.append((start, end))
            start, end = m.start(), m.end()
    spans.append((start, end))
    # Pick the longest span
    s, e = max(spans, key=lambda p: p[1]-p[0])
    return text[s:e].strip()

def _preclean(text: str) -> str:
    s = _LEAD_STRIP_SEQ.sub("", text.strip())
    s = _TRAIL_TRASH_RE.sub("", s).strip()
    if not s:
        return s
    s = s.replace("–","-").replace("—","-").replace("−","-").replace("×","x").replace("÷","/")
    return s

def _apply_pre_rewrites(s: str) -> str:
    for pat, rep in _pre_rewrites:
        s = re.sub(pat, rep, s, flags=re.I)
    return s

def _apply_word_operators(s: str) -> str:
    for pat, rep in _replacements:
        s = re.sub(pat, rep, s, flags=re.I)
    return s

def _close_functions(s: str) -> str:
    return re.sub(r"sqrt\(([^()]+)(?!\))", r"sqrt(\1)", s)

def _apply_percent_rules(s: str) -> str:
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", r"(\1/100)*(\2)", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    return s

def _apply_unary_negatives(s: str) -> str:
    return re.sub(r"(?:(?<=^)|(?<=[\(\+\-\*/%]))\s*negative\s+(\d+(?:\.\d+)?)", r"-\1", s, flags=re.I)

def normalize_math(text: str) -> str:
    s = _preclean(text)
    if not s:
        return s
    s = _apply_pre_rewrites(s)
    s = _apply_word_operators(s)
    s = words_to_number(s)
    s = _apply_unary_negatives(s)
    s = _close_functions(_apply_percent_rules(s))
    s = s.replace("^", "**")
    s = re.sub(r"\s+", " ", s).strip()
    # allow digits, ops, parens, whitespace, comma, caret, letters (funcs/consts)
    if re.search(r"[^\d\.\+\-\*/%\(\)\s,\^A-Za-z_]", s):
        raise ValueError("disallowed characters")
    return s

def try_calculate(text: str):
    # 1) Find best math window in the ORIGINAL text, then normalize
    window = _extract_best_math_window(text)
    if window:
        try:
            expr = normalize_math(window)
            if expr:
                chunks = _MATH_CHUNK_RE.findall(expr)
                candidate = (max(chunks, key=len).strip() if chunks else expr.strip())
                return safe_eval(candidate)
        except Exception:
            pass

    # 2) Fallback: normalize whole text
    try:
        expr2 = normalize_math(text)
        if expr2:
            chunks2 = _MATH_CHUNK_RE.findall(expr2)
            candidate2 = (max(chunks2, key=len).strip() if chunks2 else expr2.strip())
            return safe_eval(candidate2)
    except Exception:
        pass

    return None

# ---------------- Examples ----------------
if __name__ == "__main__":
    tests = [
"what is 12 times 3 plus 5", "whats 12 times 3 plus 5", "12 times 3 plus 5", "square root of 2", "two hundred and five divided by 5", "15 percent of 80", "finally home hey jarvis calculate 7 to the power of 4", "7 to the power of 4", "7 squared", "what's 1 + 1", "whats 10 + 10", "1 million minus 1", "what is 1 million - 1", "one hundred million plus one", "one hundred plus one", "negative 10 plus 10", "negative 10 minus ten", "-10 minus 10", "-10 plus 10", "subtract 4 from 10", "take 4 away from 10", "difference between 9 and 2", "absolute difference between 2 and 9", "twenty-one plus eight", "two and a half plus a quarter", "three quarters plus a half", "open bracket five plus three close bracket times two", "log10(1000)", "round(2.7)", "abs(-5) + tau / pi", "-10 mins 10",
    ]
    for t in tests:
        print(f"{t:55} => {try_calculate(t)}")
