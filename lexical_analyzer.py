import math
import re

KEYWORDS_BY_LANG = {
    "Python": {
        "False", "None", "True", "and", "as", "assert", "async", "await", "break",
        "class", "continue", "def", "del", "elif", "else", "except", "finally",
        "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
        "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
    },
    "C++": {
        "alignas", "alignof", "auto", "bool", "break", "case", "catch", "char",
        "class", "const", "constexpr", "continue", "default", "delete", "do",
        "double", "else", "enum", "explicit", "false", "float", "for", "friend",
        "if", "inline", "int", "long", "namespace", "new", "nullptr", "operator",
        "private", "protected", "public", "return", "short", "signed", "sizeof",
        "static", "struct", "switch", "template", "this", "throw", "true", "try",
        "typedef", "typename", "unsigned", "using", "virtual", "void", "while",
    },
    "Java": {
        "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
        "class", "continue", "default", "do", "double", "else", "enum", "extends",
        "false", "final", "finally", "float", "for", "if", "implements", "import",
        "instanceof", "int", "interface", "long", "native", "new", "null", "package",
        "private", "protected", "public", "return", "short", "static", "super",
        "switch", "synchronized", "this", "throw", "throws", "true", "try", "void",
        "while",
    },
    "JavaScript": {
        "async", "await", "break", "case", "catch", "class", "const", "continue",
        "debugger", "default", "delete", "do", "else", "export", "extends", "false",
        "finally", "for", "function", "if", "import", "in", "instanceof", "let",
        "new", "null", "return", "super", "switch", "this", "throw", "true", "try",
        "typeof", "undefined", "var", "void", "while", "yield",
    },
}

THREE_CHAR_OPS = {"===", "!==", ">>=", "<<=", "**=", "//="}
TWO_CHAR_OPS = {
    "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=",
    "/=", "%=", "->", "=>", "::", "<<", ">>", "**", "//",
}


def get_rank(cc):
    if cc <= 5:
        return "A"
    if cc <= 10:
        return "B"
    if cc <= 20:
        return "C"
    return "D"


def get_rating_label(avg):
    if avg <= 5:
        return "A · Low Risk"
    if avg <= 10:
        return "B · Moderate"
    if avg <= 20:
        return "C · Complex"
    return "D · High Risk"


def count_branches(block, language):
    """Count decision branches after stripping strings and comments."""
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', '""', block)
    cleaned = re.sub(r"//.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"#.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)

    if language == "Python":
        patterns = [r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b", r"\bexcept\b", r"\band\b", r"\bor\b"]
    else:
        patterns = [
            r"\bif\b", r"\belse\s+if\b", r"\bfor\b", r"\bwhile\b",
            r"\bcase\b", r"\bcatch\b", r"&&", r"\|\|", r"\?[^:]+:",
        ]

    return 1 + sum(len(re.findall(p, cleaned)) for p in patterns)


def analyze_complexity(code, language):
    """Calculate per-function cyclomatic complexity, nesting depth, and maintainability."""
    lines = code.splitlines()
    loc = sum(1 for line in lines if line.strip())
    details = []

    if language == "Python":
        for i, line in enumerate(lines):
            match = re.match(r"^(\s*)def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", line)
            if not match:
                continue
            base_indent = len(match.group(1))
            fn_lines = [line]
            max_nest = 0

            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    fn_lines.append(nxt)
                    continue
                indent = len(nxt) - len(nxt.lstrip(" \t"))
                if indent <= base_indent and not nxt.lstrip().startswith("#"):
                    break
                max_nest = max(max_nest, max(0, (indent - base_indent) // 4 - 1))
                fn_lines.append(nxt)

            cc = count_branches("\n".join(fn_lines), language)
            details.append({
                "name": f"{match.group(2)}()",
                "line": i + 1,
                "complexity": cc,
                "nesting": max_nest,
                "rank": get_rank(cc),
            })
    else:
        if language == "JavaScript":
            fn_re = re.compile(
                r"^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\([^)]*\)\s*\{"
                r"|^\s*(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>\s*\{"
            )
        elif language == "Java":
            fn_re = re.compile(
                r"^\s*(?:public|private|protected|static|final|synchronized|\s)*[\w<>\[\]]+\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*\)\s*\{"
            )
        else:
            fn_re = re.compile(
                r"^\s*(?:static|inline|virtual|const|unsigned|signed|[\w:<>]+)\s+(?:[\w:*&<>]+\s+)*([a-zA-Z_][a-zA-Z0-9_:]*)\s*\([^;]*\)\s*(?:const)?\s*\{"
            )

        for i, line in enumerate(lines):
            if re.match(r"^\s*(if|else|for|while|switch|catch)\b", line):
                continue
            match = fn_re.match(line)
            if not match:
                continue

            fn_name = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None) or "anonymous"
            depth = 0
            max_nest = 0
            started = False
            fn_lines = []

            for cur in lines[i:]:
                fn_lines.append(cur)
                for ch in cur:
                    if ch == "{":
                        depth += 1
                        started = True
                        max_nest = max(max_nest, depth - 1)
                    elif ch == "}":
                        depth -= 1
                if started and depth <= 0:
                    break

            cc = count_branches("\n".join(fn_lines), language)
            details.append({
                "name": f"{fn_name}()",
                "line": i + 1,
                "complexity": cc,
                "nesting": max_nest,
                "rank": get_rank(cc),
            })

    if not details:
        overall_cc = count_branches(code, language)
        details.append({
            "name": "Module / Top-Level",
            "line": 1,
            "complexity": overall_cc,
            "nesting": 0,
            "rank": get_rank(overall_cc),
        })

    avg_cc = round(sum(d["complexity"] for d in details) / len(details), 2)
    max_cc = max(d["complexity"] for d in details)
    raw_mi = 100 - math.log2(max(loc, 1)) * 7.5 - avg_cc * 2.4

    return {
        "method": "Python Branch Scan" if language == "Python" else f"{language} Control-Flow Scan",
        "average_complexity": avg_cc,
        "max_complexity": max_cc,
        "rating": get_rating_label(avg_cc),
        "maintainability_index": max(0, min(100, round(raw_mi))),
        "loc": loc,
        "details": details,
    }


def tokenize(code, language):
    keywords = KEYWORDS_BY_LANG.get(language, KEYWORDS_BY_LANG["Python"])
    tokens = []
    unclosed_strings = []
    unbalanced_delimiters = []
    stack = []
    matching_open = {")": "(", "]": "[", "}": "{"}

    i = 0
    line = 1
    col = 1
    length = len(code)

    def advance(count):
        nonlocal i, line, col
        for _ in range(count):
            if code[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < length:
        ch = code[i]

        if ch in (" ", "\t", "\r", "\n"):
            advance(1)
            continue

        if language == "Python" and ch == "#":
            start_line, start_col = line, col
            end = i
            while end < length and code[end] != "\n":
                end += 1
            value = code[i:end]
            tokens.append({"type": "comment", "value": value, "line": start_line, "column": start_col})
            advance(len(value))
            continue

        if language != "Python" and code[i:i + 2] == "//":
            start_line, start_col = line, col
            end = i
            while end < length and code[end] != "\n":
                end += 1
            value = code[i:end]
            tokens.append({"type": "comment", "value": value, "line": start_line, "column": start_col})
            advance(len(value))
            continue

        if language != "Python" and code[i:i + 2] == "/*":
            start_line, start_col = line, col
            close_idx = code.find("*/", i + 2)
            value = code[i:] if close_idx == -1 else code[i:close_idx + 2]
            tokens.append({"type": "comment", "value": value, "line": start_line, "column": start_col})
            advance(len(value))
            continue

        if ch in ('"', "'") or (language == "JavaScript" and ch == "`"):
            start_line, start_col = line, col
            is_triple = language == "Python" and code[i:i + 3] == ch * 3
            quote = ch * 3 if is_triple else ch
            j = i + len(quote)
            closed = False

            while j < length:
                if code[j] == "\\":
                    j += 2
                    continue
                if is_triple:
                    if code[j:j + 3] == quote:
                        j += 3
                        closed = True
                        break
                else:
                    if code[j] == quote:
                        j += 1
                        closed = True
                        break
                    if code[j] == "\n" and ch != "`":
                        break
                j += 1

            if not closed:
                unclosed_strings.append(start_line)
            value = code[i:j]
            tokens.append({"type": "string", "value": value, "line": start_line, "column": start_col})
            advance(len(value))
            continue

        if ch.isdigit() or (ch == "." and i + 1 < length and code[i + 1].isdigit()):
            start_line, start_col = line, col
            m = re.match(r"^(?:0x[0-9a-fA-F_]+|0b[01_]+|[0-9_]+(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]+)?)", code[i:])
            value = m.group(0) if m else ch
            tokens.append({"type": "number", "value": value, "line": start_line, "column": start_col})
            advance(len(value))
            continue

        if re.match(r"[a-zA-Z_$]", ch):
            start_line, start_col = line, col
            m = re.match(r"^[a-zA-Z_$][a-zA-Z0-9_$]*", code[i:])
            value = m.group(0) if m else ch
            tok_type = "keyword" if value in keywords else "identifier"
            tokens.append({"type": tok_type, "value": value, "line": start_line, "column": start_col})
            advance(len(value))
            continue

        if ch in "()[]{},;:.":
            start_line, start_col = line, col
            if ch in ("(", "[", "{"):
                stack.append({"char": ch, "line": start_line})
            elif ch in (")", "]", "}"):
                expected = matching_open[ch]
                if not stack:
                    unbalanced_delimiters.append({
                        "char": ch,
                        "line": start_line,
                        "message": f"Unexpected closing '{ch}' with no matching '{expected}'.",
                    })
                elif stack[-1]["char"] != expected:
                    top = stack.pop()
                    unbalanced_delimiters.append({
                        "char": ch,
                        "line": start_line,
                        "message": f"Mismatched '{ch}': expected closing match for '{top['char']}' opened on line {top['line']}.",
                    })
                else:
                    stack.pop()
            tokens.append({"type": "delimiter", "value": ch, "line": start_line, "column": start_col})
            advance(1)
            continue

        three_char = code[i:i + 3]
        two_char = code[i:i + 2]
        if three_char in THREE_CHAR_OPS:
            tokens.append({"type": "operator", "value": three_char, "line": line, "column": col})
            advance(3)
            continue
        if two_char in TWO_CHAR_OPS:
            tokens.append({"type": "operator", "value": two_char, "line": line, "column": col})
            advance(2)
            continue
        if ch in "+-*/%=<>!&|^~?@#":
            tokens.append({"type": "operator", "value": ch, "line": line, "column": col})
            advance(1)
            continue

        tokens.append({"type": "unknown", "value": ch, "line": line, "column": col})
        advance(1)

    for leftover in stack:
        unbalanced_delimiters.append({
            "char": leftover["char"],
            "line": leftover["line"],
            "message": f"Unclosed '{leftover['char']}' opened on line {leftover['line']}.",
        })

    return {
        "tokens": tokens,
        "unclosed_strings": unclosed_strings,
        "unbalanced_delimiters": unbalanced_delimiters,
    }


def strip_strings_and_comments(line, language):
    out = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', '""', line)
    if language == "Python":
        out = re.sub(r"#.*$", "", out)
    else:
        out = re.sub(r"//.*$", "", out)
        out = re.sub(r"/\*[\s\S]*?\*/", "", out)
    return out


def normalize_operator_spacing(line, language):
    tokens = tokenize(line, language)["tokens"]
    if any(t["type"] in ("comment", "string") for t in tokens):
        return line
    return re.sub(r"([a-zA-Z0-9_)\]])([+\-*/%])([a-zA-Z0-9_(])", r"\1 \2 \3", line)


def build_improved_code(code, language, lines):
    out_lines = list(lines)

    if language == "Python":
        has_negative_subtract = False
        i = 0
        while i < len(out_lines):
            line = out_lines[i]
            indent = re.match(r"^(\s*)", line).group(1)

            line = re.sub(r"==\s*None\b", "is None", line)
            line = re.sub(r"!=\s*None\b", "is not None", line)
            line = re.sub(r"^(\s*)except\s*:", r"\1except Exception:", line)

            range_match = re.match(
                r"^(\s*)for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+range\s*\(\s*len\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*\)\s*:\s*$",
                line,
            )
            if range_match and i + 1 < len(out_lines):
                idx_var = range_match.group(2)
                seq_var = range_match.group(3)
                next_line = out_lines[i + 1]
                assign_match = re.match(
                    rf"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*{re.escape(seq_var)}\[{re.escape(idx_var)}\]\s*$",
                    next_line,
                )
                if assign_match:
                    item_var = assign_match.group(1)
                    out_lines[i] = f"{range_match.group(1)}for {item_var} in {seq_var}:"
                    del out_lines[i + 1]
                    continue

            line = re.sub(r"^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\2\s*\+\s*(.+)$", r"\1\2 += \3", line)

            flat_sub = re.match(
                r"^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\2\s*-\s*([0-9]+(?:\.[0-9]+)?)\s*$",
                line,
            )
            if flat_sub:
                has_negative_subtract = True
                line = f"{flat_sub.group(1)}{flat_sub.group(2)} = max(0, {flat_sub.group(2)} - {flat_sub.group(3)})"
            else:
                line = re.sub(r"^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\2\s*-\s*(.+)$", r"\1\2 -= \3", line)

            if has_negative_subtract and re.match(r"^\s*if\s+[a-zA-Z_][a-zA-Z0-9_]*\s*==\s*0\s*:", line):
                line = re.sub(r"==\s*0\s*:", "<= 0:", line)

            if re.search(r'if\s+item\["price"\]\s*>\s*0\s*:', line):
                line = f'{indent}if item.get("price", 0) > 0 and item.get("qty", 0) > 0:'

            out_lines[i] = normalize_operator_spacing(line, language)
            i += 1

        return "\n".join(out_lines)

    if language == "C++":
        uses_inclusive_right = bool(re.search(r"while\s*\(\s*left\s*<=\s*right\s*\)", code))

        def replace_param(match):
            type_name, param_name = match.group(1), match.group(2)
            if f"{param_name}.push_back" in code or f"{param_name} =" in code:
                return match.group(0)
            return f"const {type_name}& {param_name}"

        for i, line in enumerate(out_lines):
            line = re.sub(
                r"\b((?:std::)?vector<[^>]+>|(?:std::)?string)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b(?!\s*[&=])",
                replace_param,
                line,
            )
            if uses_inclusive_right:
                line = re.sub(
                    r"^(\s*int\s+right\s*=\s*)([a-zA-Z_][a-zA-Z0-9_]*)\.size\(\)\s*;",
                    r"\1static_cast<int>(\2.size()) - 1;",
                    line,
                )
            line = re.sub(
                r"\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\+\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*/\s*2\b",
                r"\1 + (\2 - \1) / 2",
                line,
            )
            out_lines[i] = normalize_operator_spacing(line, language)

        return "\n".join(out_lines)

    if language == "Java":
        for i, line in enumerate(out_lines):
            line = re.sub(
                r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.equals\(\s*("(?:\\.|[^"\\])*")\s*\)',
                r"\2.equals(\1)",
                line,
            )
            line = re.sub(
                r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*!=\s*""',
                r"\1 != null && !\1.isEmpty()",
                line,
            )
            line = re.sub(
                r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*==\s*""',
                r"(\1 == null || \1.isEmpty())",
                line,
            )
            line = re.sub(
                r"^(\s*private\s+)((?:Map|List|Set)<[^>]+>\s+[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*new\s+)",
                r"\1final \2",
                line,
            )
            out_lines[i] = normalize_operator_spacing(line, language)

        return "\n".join(out_lines)

    # JavaScript
    for i, line in enumerate(out_lines):
        line = re.sub(r"([^=!<>])==([^=])", r"\1===\2", line)
        line = re.sub(r"([^!])!=([^=])", r"\1!==\2", line)
        line = re.sub(r"^(\s*)var\s+", r"\1let ", line)
        out_lines[i] = normalize_operator_spacing(line, language)

    return "\n".join(out_lines)


def analyze_code_lexically(code, language):
    complexity = analyze_complexity(code, language)
    lines = code.replace("\r\n", "\n").split("\n")
    lex = tokenize(code, language)

    bugs = []
    seen_bugs = set()
    improvements = []
    seen_improvements = set()

    def add_bug(bug):
        key = f"{bug['line']}:{bug['title']}"
        if key not in seen_bugs:
            seen_bugs.add(key)
            bugs.append(bug)

    def add_improvement(item):
        if item["title"] not in seen_improvements:
            seen_improvements.add(item["title"])
            improvements.append(item)

    # 1. Structural lexical checks
    for str_line in lex["unclosed_strings"]:
        add_bug({
            "line": str(str_line),
            "severity": "critical",
            "title": "Unterminated string literal",
            "description": "Lexical scanner reached end of line or file before finding a matching closing quote.",
            "fix": "Close the string literal with a matching quote character or escape internal quotes.",
        })

    for delim in lex["unbalanced_delimiters"]:
        add_bug({
            "line": str(delim["line"]),
            "severity": "critical",
            "title": f"Unbalanced delimiter '{delim['char']}'",
            "description": delim["message"],
            "fix": "Ensure every opening parenthesis, bracket, and brace has a matching closing delimiter.",
        })

    # 2. Indentation consistency (Python)
    if language == "Python":
        uses_spaces = False
        uses_tabs = False
        for idx, raw in enumerate(lines):
            if not raw.strip():
                continue
            ws_match = re.match(r"^[ \t]+", raw)
            ws = ws_match.group(0) if ws_match else ""
            if " " in ws:
                uses_spaces = True
            if "\t" in ws:
                uses_tabs = True
            if " " in ws and "\t" in ws:
                add_bug({
                    "line": str(idx + 1),
                    "severity": "high",
                    "title": "Mixed tabs and spaces",
                    "description": "Mixing tabs and spaces in indentation can cause TabError or unexpected block scoping in Python.",
                    "fix": "Standardize indentation to 4 spaces across the entire file.",
                })
        if uses_spaces and uses_tabs and all(b["title"] != "Mixed tabs and spaces" for b in bugs):
            add_improvement({
                "title": "Use consistent 4-space indentation",
                "category": "Style",
                "description": "The file mixes tabs on some lines and spaces on others, which violates PEP 8.",
                "suggestion": "Configure your editor to insert 4 spaces per indent level.",
            })

    # 3. Language-specific rules
    if language == "Python":
        discount_subtract_line = None

        for idx, raw in enumerate(lines):
            line_num = idx + 1
            clean = strip_strings_and_comments(raw, language)

            if re.match(r"^\s*def\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*=\s*(\[\]|\{\})", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "high",
                    "title": "Mutable default argument",
                    "description": "Default list or dict literals are evaluated once at function definition and shared across all calls.",
                    "fix": "Default the parameter to None and initialize `param = [] if param is None else param` inside the function.",
                })

            if re.match(r"^\s*except\s*:", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "medium",
                    "title": "Bare except clause",
                    "description": "A bare `except:` catches BaseException subclasses including KeyboardInterrupt and SystemExit.",
                    "fix": "Catch a specific exception type or `except Exception as err:`.",
                })

            if re.search(r"\b(eval|exec)\s*\(", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "critical",
                    "title": "Dynamic code execution risk",
                    "description": "Calling eval() or exec() executes arbitrary code strings and creates severe injection risk.",
                    "fix": "Replace with `ast.literal_eval()` for literals or explicit parsing logic.",
                })

            if re.search(r"([!=]=)\s*(None|True|False)\b", clean):
                add_improvement({
                    "title": "Use identity check for singletons",
                    "category": "Style",
                    "description": "PEP 8 recommends `is` / `is not` when comparing against `None`, `True`, or `False`.",
                    "suggestion": re.sub(r"!=\s*None\b", "is not None", re.sub(r"==\s*None\b", "is None", raw.strip())),
                })

            if re.search(r'\bis\s+(?:""|[0-9]+)\b', raw):
                add_bug({
                    "line": str(line_num),
                    "severity": "medium",
                    "title": "Identity check on literal",
                    "description": "Using `is` with string or integer literals relies on object interning rather than value equality.",
                    "fix": "Use `==` or `!=` for value comparisons with strings and numbers.",
                })

            if re.search(r'\bif\s+item\["price"\]', raw) and 'item["qty"]' in code and not re.search(r'item\["qty"\]\s*>', code):
                add_bug({
                    "line": str(line_num),
                    "severity": "medium",
                    "title": "Unvalidated item quantity & keys",
                    "description": 'Checking `item["price"] > 0` without verifying `item["qty"] > 0` allows negative quantities to reduce the order total, and direct indexing raises KeyError on missing keys.',
                    "fix": 'Use `item.get("price", 0) > 0 and item.get("qty", 0) > 0` before accumulating.',
                })

            if re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\1\s*-\s*[0-9]+", clean):
                discount_subtract_line = line_num

            if discount_subtract_line is not None and re.search(r"\bif\s+[a-zA-Z_][a-zA-Z0-9_]*\s*==\s*0\s*:", clean):
                add_bug({
                    "line": f"{discount_subtract_line}-{line_num}",
                    "severity": "high",
                    "title": "Discount can produce negative total",
                    "description": "Subtracting a flat amount without clamping allows `total` to drop below zero, bypassing the `total == 0` guard.",
                    "fix": "Clamp with `total = max(0, total - 50)` and check `if total <= 0:`.",
                })

            if re.search(r"for\s+[a-zA-Z_][a-zA-Z0-9_]*\s+in\s+range\s*\(\s*len\s*\(", clean):
                add_improvement({
                    "title": "Iterate directly instead of range(len())",
                    "category": "Readability",
                    "description": "Iterating directly over items (or using `enumerate()`) removes manual index lookups and off-by-one boilerplate.",
                    "suggestion": "for item in items:",
                })

            def_match = re.match(r"^\s*def\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(([^)]*)\)\s*:", clean)
            if def_match and "->" not in clean and ":" not in def_match.group(1):
                add_improvement({
                    "title": "Add Python type annotations",
                    "category": "Maintainability",
                    "description": "Adding parameter and return type annotations improves static checking and IDE autocomplete.",
                    "suggestion": "def func(param: type) -> return_type:",
                })

    elif language == "C++":
        uses_inclusive_right = bool(re.search(r"while\s*\(\s*left\s*<=\s*right\s*\)", code))

        for idx, raw in enumerate(lines):
            line_num = idx + 1
            clean = strip_strings_and_comments(raw, language)

            if uses_inclusive_right and re.search(r"\bint\s+right\s*=\s*[a-zA-Z_][a-zA-Z0-9_]*\.size\(\)\s*;", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "critical",
                    "title": "Out-of-bounds right index",
                    "description": "Initializing `right = arr.size()` with `while (left <= right)` reads `arr[arr.size()]` when the target is greater than all elements or when the vector is empty.",
                    "fix": "Initialize `int right = static_cast<int>(arr.size()) - 1;`.",
                })

            if re.search(r"\(\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\+\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\)\s*/\s*2\b", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "medium",
                    "title": "Potential signed integer overflow",
                    "description": "Computing `(left + right) / 2` can overflow `INT_MAX` when `left + right` exceeds 32-bit signed integer limits.",
                    "fix": "Compute `int mid = left + (right - left) / 2;` instead.",
                })

            copy_param = re.search(
                r"\b((?:std::)?vector<[^>]+>|(?:std::)?string|(?:std::)?map<[^>]+>)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b(?!\s*[&=])",
                clean,
            )
            if copy_param:
                add_improvement({
                    "title": f"Pass {copy_param.group(2)} by const reference",
                    "category": "Performance",
                    "description": f"Passing `{copy_param.group(1)}` by value copies the entire container on every call.",
                    "suggestion": f"const {copy_param.group(1)}& {copy_param.group(2)}",
                })

            if re.match(r"^\s*using\s+namespace\s+std\s*;", clean):
                add_improvement({
                    "title": "Avoid global `using namespace std;`",
                    "category": "Safety",
                    "description": "Importing the entire `std` namespace can cause subtle name collisions across headers and translation units.",
                    "suggestion": "Qualify standard types explicitly with `std::vector`, `std::string`, etc.",
                })

            if re.search(r"\b(gets|strcpy|strcat|sprintf)\s*\(", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "critical",
                    "title": "Unsafe buffer operation",
                    "description": "Unbounded C string functions can cause stack or heap buffer overflows.",
                    "fix": "Use `std::string`, `snprintf`, or bounded `strncpy` alternatives.",
                })

            if re.search(r"\b(?:if|while)\s*\([^)]*[^=!<>]=[^=][^)]*\)", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "high",
                    "title": "Assignment inside condition",
                    "description": "Single `=` inside a conditional evaluates the assigned value instead of comparing for equality.",
                    "fix": "Replace `=` with `==` if a comparison was intended.",
                })

    elif language == "Java":
        guarded_non_null = set()

        for idx, raw in enumerate(lines):
            line_num = idx + 1
            clean = strip_strings_and_comments(raw, language)

            non_null_check = re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*!=\s*null\b", clean)
            if non_null_check:
                guarded_non_null.add(non_null_check.group(1))

            eq_match = re.search(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.equals\(\s*("(?:\\.|[^"\\])*")\s*\)', clean)
            if eq_match and eq_match.group(1) not in guarded_non_null:
                var_name, literal = eq_match.group(1), eq_match.group(2)
                add_bug({
                    "line": str(line_num),
                    "severity": "high",
                    "title": f"Potential NullPointerException on `{var_name}`",
                    "description": f"Calling `{var_name}.equals({literal})` throws NullPointerException when `{var_name}` is null (e.g., missing map key).",
                    "fix": f"Invert the comparison to `{literal}.equals({var_name})` or check `{var_name} != null`.",
                })

            str_cmp = re.search(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*([!=]=)\s*("(?:\\.|[^"\\])*")', raw)
            if str_cmp:
                var_name, op, literal = str_cmp.group(1), str_cmp.group(2), str_cmp.group(3)
                add_bug({
                    "line": str(line_num),
                    "severity": "high",
                    "title": "String compared by reference",
                    "description": f"Using `{op}` on Strings checks object reference identity rather than character contents, and fails to guard against null.",
                    "fix": f"Use `{var_name} != null && !{var_name}.isEmpty()` or `.equals({literal})`.",
                })

            if re.match(r"^\s*import\s+[\w.]+\.\*\s*;", clean):
                add_improvement({
                    "title": "Replace wildcard import with explicit imports",
                    "category": "Style",
                    "description": "Wildcard imports obscure which classes are used and can introduce ambiguity when packages grow.",
                    "suggestion": "import java.util.HashMap;\nimport java.util.Map;",
                })

            if re.match(r"^\s*private\s+(?!final\b)(?:Map|List|Set)<[^>]+>\s+[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*new\s+", clean):
                add_improvement({
                    "title": "Mark collection field as final",
                    "category": "Safety",
                    "description": "Marking the backing map/collection reference `final` prevents accidental reassignment.",
                    "suggestion": "private final Map<String, String> sessions = new HashMap<>();",
                })

            if re.search(r"catch\s*\([^)]+\)\s*\{\s*\}", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "medium",
                    "title": "Empty catch block",
                    "description": "Swallowing exceptions silently hides runtime failures and complicates debugging.",
                    "fix": "Log the exception or rethrow a domain-specific error.",
                })

    elif language == "JavaScript":
        for idx, raw in enumerate(lines):
            line_num = idx + 1
            clean = strip_strings_and_comments(raw, language)

            if re.search(r"[^=!<>]==[^=]", clean) or re.search(r"[^!]!=[^=]", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "medium",
                    "title": "Loose equality comparison",
                    "description": "Using `==` or `!=` performs implicit type coercion and can cause unexpected truthy/falsy matches.",
                    "fix": "Use strict equality `===` and `!==`.",
                })

            if re.match(r"^\s*var\s+", clean):
                add_improvement({
                    "title": "Replace `var` with `const` or `let`",
                    "category": "Safety",
                    "description": "`var` is function-scoped and hoisted, which can cause subtle closure and redeclaration bugs.",
                    "suggestion": "Use `const` for bindings that are never reassigned and `let` otherwise.",
                })

            if re.search(r"\beval\s*\(", clean):
                add_bug({
                    "line": str(line_num),
                    "severity": "critical",
                    "title": "Unsafe eval() invocation",
                    "description": "Executing strings with eval() exposes the application to code injection vulnerabilities.",
                    "fix": "Use JSON.parse() or structured lookup tables instead.",
                })

    # 4. Cross-language spacing check
    tight_operator_sample = ""
    for raw in lines:
        clean = strip_strings_and_comments(raw, language)
        if re.search(r"[a-zA-Z0-9_)\]][+\-*/%][a-zA-Z0-9_(]", clean) and not re.search(r"->|\+\+|--", clean):
            tight_operator_sample = normalize_operator_spacing(raw.strip(), language)
            break

    if tight_operator_sample:
        add_improvement({
            "title": "Add whitespace around binary operators",
            "category": "Style",
            "description": "Surrounding arithmetic operators with single spaces improves token legibility.",
            "suggestion": tight_operator_sample,
        })

    # 5. Compute lexical metrics & score
    improved_code = build_improved_code(code, language, lines)
    tokens = lex["tokens"]
    token_count = len(tokens)
    comment_count = sum(1 for t in tokens if t["type"] == "comment")
    keyword_count = sum(1 for t in tokens if t["type"] == "keyword")
    identifier_count = len({t["value"] for t in tokens if t["type"] == "identifier"})

    score = 10.0
    for bug in bugs:
        sev = bug["severity"]
        if sev == "critical":
            score -= 2.5
        elif sev == "high":
            score -= 2.0
        elif sev == "medium":
            score -= 1.0
        else:
            score -= 0.5
    score -= min(1.5, len(improvements) * 0.5)
    if complexity["average_complexity"] > 10:
        score -= 1.0
    elif complexity["average_complexity"] > 5:
        score -= 0.5

    clamped = max(1.0, min(10.0, round(score * 2) / 2))
    final_score = int(clamped) if clamped.is_integer() else clamped

    bug_word = "issue" if len(bugs) == 1 else "issues"
    imp_word = "suggestion" if len(improvements) == 1 else "suggestions"
    enh_word = "enhancement" if len(improvements) == 1 else "enhancements"

    if not bugs:
        summary = (
            f"Lexical scan across {complexity['loc']} non-empty lines ({token_count} tokens) "
            f"found no defects; {len(improvements)} style or structural {enh_word} noted."
        )
    else:
        summary = (
            f"Lexical scan across {complexity['loc']} non-empty lines ({token_count} tokens) "
            f"flagged {len(bugs)} potential {bug_word} and {len(improvements)} refactoring {imp_word}."
        )

    block_word = "block" if len(complexity["details"]) == 1 else "blocks"
    complexity_notes = (
        f"Lexical scan tokenized {token_count} tokens ({keyword_count} keywords, "
        f"{identifier_count} unique identifiers, {comment_count} comments) across "
        f"{len(complexity['details'])} {block_word}. "
        f"Average cyclomatic complexity is {complexity['average_complexity']} "
        f"({complexity['rating']}) with max complexity {complexity['max_complexity']} "
        f"and Maintainability Index {complexity['maintainability_index']}/100."
    )

    review = {
        "summary": summary,
        "bugs": bugs,
        "improvements": improvements,
        "complexity_notes": complexity_notes,
        "overall_score": final_score,
        "improved_code": improved_code,
    }
    return review, complexity
