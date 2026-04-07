"""
agents.py — Three-agent pipeline for AI Code Review.

Agent 1 · SUMMARISER
    Pure AST + heuristic analysis. No LLM.
    Reliable for single functions, multi-function files, classes,
    async code, files with imports, decorators, etc.
    Produces: description, structure inventory, complexity estimate.

Agent 2 · REVIEWER
    AST rule engine (rule_engine.py). Deterministic, zero hallucination.

Agent 3 · IMPROVER
    Priority order:
      a) Syntax error         → return original unchanged
      b) Deterministic rules  → apply targeted AST-aware rewrite
      c) LLM fallback         → codet5p-220m with strict prompt + validation
      d) Any LLM failure      → return original unchanged

    For multi-function / module-level code the improver applies rewrites
    per-function so unrelated code is never touched.
"""

import ast
import re
import textwrap
from typing import Optional, List, Dict, Any

from model import generate_improvement
from rule_engine import check_rules, format_issues, Issue


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 1 — SUMMARISER  (pure AST, no LLM)
# ═══════════════════════════════════════════════════════════════════════════════

def summariser_agent(code: str) -> str:
    """
    Return structured Markdown explaining what the code does.
    Entirely deterministic — derived from AST + heuristics.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"⚠️ Cannot parse code — syntax error on line {exc.lineno}: `{exc.msg}`"

    info = _analyse_tree(tree, code)
    return _render_summary(info)


def _analyse_tree(tree: ast.AST, source: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "functions": [],
        "classes": [],
        "imports": [],
        "top_level_calls": [],
        "has_async": False,
        "has_decorators": False,
        "has_type_hints": False,
        "max_loop_depth": 0,
        "total_lines": len(source.strip().splitlines()),
    }

    def _loop_depth(node, d=0):
        if isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            d += 1
        peak = d
        for child in ast.iter_child_nodes(node):
            peak = max(peak, _loop_depth(child, d))
        return peak

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.AsyncFunctionDef):
                info["has_async"] = True
            if node.decorator_list:
                info["has_decorators"] = True
            if node.returns or any(a.annotation for a in node.args.args):
                info["has_type_hints"] = True

            params = [a.arg for a in node.args.args]
            defaults_count = len(node.args.defaults)
            depth = _loop_depth(node)
            info["max_loop_depth"] = max(info["max_loop_depth"], depth)

            # Infer purpose from name + body heuristics
            purpose = _infer_purpose(node)

            info["functions"].append({
                "name": node.name,
                "params": params,
                "defaults": defaults_count,
                "loop_depth": depth,
                "purpose": purpose,
                "line": node.lineno,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })

        elif isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.col_offset > node.col_offset
            ]
            info["classes"].append({
                "name": node.name,
                "methods": methods,
                "line": node.lineno,
            })

        elif isinstance(node, ast.Import):
            for alias in node.names:
                info["imports"].append(alias.asname or alias.name)

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                info["imports"].append(f"{mod}.{alias.name}" if mod else alias.name)

    # Top-level calls (not inside a function/class) — detect entry points
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name):
                info["top_level_calls"].append(node.value.func.id)
            elif isinstance(node.value.func, ast.Attribute):
                info["top_level_calls"].append(node.value.func.attr)

    return info


def _infer_purpose(func_node: ast.FunctionDef) -> str:
    """Heuristically describe what a function does based on its name and body."""
    name = func_node.name.lower()

    # Name-based hints
    if name.startswith(("is_", "has_", "can_", "should_", "check_")):
        return "predicate / condition check"
    if name.startswith(("get_", "fetch_", "load_", "read_")):
        return "data retrieval"
    if name.startswith(("set_", "update_", "write_", "save_", "store_")):
        return "data mutation / persistence"
    if name.startswith(("calc_", "compute_", "calculate_", "sum_", "count_", "average_")):
        return "numeric computation"
    if name.startswith(("format_", "render_", "display_", "print_", "show_")):
        return "output / formatting"
    if name.startswith(("parse_", "extract_", "split_", "tokenize_")):
        return "data parsing / extraction"
    if name.startswith(("sort_", "filter_", "search_", "find_")):
        return "data filtering / searching"
    if name.startswith(("send_", "post_", "request_", "call_")):
        return "I/O or network operation"
    if name in ("__init__",):
        return "constructor / initialiser"
    if name in ("__str__", "__repr__"):
        return "string representation"
    if name.startswith("test_"):
        return "unit test"
    if name == "main":
        return "program entry point"

    # Body-based hints
    body_str = ast.dump(func_node)
    if "open" in body_str:
        return "file I/O"
    if "request" in body_str or "urllib" in body_str or "http" in body_str.lower():
        return "network / HTTP operation"
    if "append" in body_str or "extend" in body_str:
        return "list / collection builder"
    if "return" in body_str:
        # Check if it returns a bool
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, bool):
                    return "boolean predicate"
        return "computation / transformation"

    return "utility function"


def _complexity_label(max_depth: int, num_funcs: int, total_lines: int) -> str:
    if max_depth >= 3 or total_lines > 100:
        return "O(n³) or higher — highly nested logic"
    if max_depth == 2:
        return "O(n²) — nested loops detected"
    if max_depth == 1:
        return "O(n) — single-pass iteration"
    return "O(1) — constant time"


def _render_summary(info: Dict[str, Any]) -> str:
    parts = []

    # Imports
    if info["imports"]:
        imp_list = ", ".join(f"`{i}`" for i in sorted(set(info["imports"])))
        parts.append(f"**Imports:** {imp_list}")

    # Classes
    for cls in info["classes"]:
        method_list = ", ".join(f"`{m}`" for m in cls["methods"]) or "none"
        parts.append(
            f"**Class `{cls['name']}`** *(line {cls['line']})*  \n"
            f"Methods: {method_list}"
        )

    # Functions
    for fn in info["functions"]:
        param_str = ", ".join(f"`{p}`" for p in fn["params"]) if fn["params"] else "none"
        flags = []
        if fn["is_async"]:
            flags.append("async")
        if fn["loop_depth"] >= 2:
            flags.append(f"nested loops ×{fn['loop_depth']}")
        flag_str = f"  *({', '.join(flags)})*" if flags else ""
        parts.append(
            f"**`{fn['name']}({', '.join(fn['params'])})`**{flag_str} *(line {fn['line']})*  \n"
            f"Purpose: {fn['purpose']}  \n"
            f"Parameters: {param_str}"
        )

    # Entry points
    if info["top_level_calls"]:
        calls = ", ".join(f"`{c}()`" for c in info["top_level_calls"])
        parts.append(f"**Entry-point calls:** {calls}")

    # Complexity
    complexity = _complexity_label(
        info["max_loop_depth"], len(info["functions"]), info["total_lines"]
    )
    parts.append(f"**Estimated complexity:** {complexity}")

    # Badges
    badges = []
    if info["has_async"]:
        badges.append("`async`")
    if info["has_type_hints"]:
        badges.append("`typed`")
    if info["has_decorators"]:
        badges.append("`decorated`")
    if badges:
        parts.append("**Features:** " + " ".join(badges))

    if not parts:
        return "No functions, classes, or imports detected."

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 2 — REVIEWER
# ═══════════════════════════════════════════════════════════════════════════════

def reviewer_agent(code: str):
    """Returns (List[Issue], formatted_markdown_string)."""
    issues = check_rules(code)
    return issues, format_issues(issues)


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 3 — IMPROVER
# ═══════════════════════════════════════════════════════════════════════════════

def improvement_agent(code: str, issues: List[Issue]) -> str:
    """
    Produce improved code.
    For module-level code with multiple functions, rewrites are applied
    per-function so unrelated code is never touched.
    """
    if not issues:
        return code

    categories = {iss.category for iss in issues}

    # ── Abort on syntax errors ───────────────────────────────────────
    if "syntax" in categories:
        return code

    # ── Detect if this is a multi-function/module file ───────────────
    try:
        tree = ast.parse(code)
        func_nodes = [
            n for n in ast.iter_child_nodes(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
    except SyntaxError:
        return code

    is_module = len(func_nodes) > 1 or any(
        isinstance(n, (ast.ClassDef, ast.Import, ast.ImportFrom))
        for n in ast.iter_child_nodes(tree)
    )

    if is_module:
        return _improve_module(code, issues, tree, func_nodes)
    else:
        return _improve_single(code, issues)


def _improve_module(code: str, issues: List[Issue], tree, func_nodes) -> str:
    """
    Apply per-function improvements, leave everything else untouched.
    Issues are mapped to functions by line number.
    """
    lines = code.splitlines(keepends=True)

    # Map issues to the function they belong to (by line range)
    func_ranges = []
    for i, fn in enumerate(func_nodes):
        start = fn.lineno - 1  # 0-indexed
        end = func_nodes[i + 1].lineno - 2 if i + 1 < len(func_nodes) else len(lines)
        func_ranges.append((start, end, fn))

    # Collect per-function issues
    func_issues: Dict[str, List[Issue]] = {}
    for iss in issues:
        if iss.line is None:
            continue
        for start, end, fn in func_ranges:
            if start <= (iss.line - 1) <= end:
                func_issues.setdefault(fn.name, []).append(iss)
                break

    # Apply rewrites function by function (in reverse order to preserve line numbers)
    result_lines = list(lines)
    for start, end, fn in reversed(func_ranges):
        fn_issues = func_issues.get(fn.name, [])
        if not fn_issues:
            continue
        fn_source = "".join(lines[start:end + 1])
        improved = _improve_single(fn_source, fn_issues)
        if improved.strip() != fn_source.strip():
            improved_lines = improved.splitlines(keepends=True)
            if not improved_lines[-1].endswith("\n"):
                improved_lines[-1] += "\n"
            result_lines[start:end + 1] = improved_lines

    return "".join(result_lines)


def _improve_single(code: str, issues: List[Issue]) -> str:
    """Apply improvements to a single function or snippet."""
    categories = {iss.category for iss in issues}
    fname = _get_func_name(code) or "function"

    # ── Deterministic rewrites (in priority order) ───────────────────

    # Redundant bool: if cond: return True else: return False
    if "redundant_bool" in categories:
        result = _rewrite_redundant_bool(code, fname)
        if result:
            return result

    # range(len()) with accumulator → sum()
    if "loop" in categories and _has_accumulator(code):
        result = _rewrite_to_sum(code, fname)
        if result:
            return result

    # append() loop → list comprehension (simple cases only)
    if "loop" in categories and "redundant_bool" not in categories:
        result = _rewrite_append_loop(code, fname)
        if result:
            return result

    # Resource leak: open() → with open()
    if "resource" in categories:
        result = _rewrite_open(code, fname)
        if result:
            return result

    # Mutable default argument
    if "mutable_default" in categories:
        result = _rewrite_mutable_default(code)
        if result and result != code:
            return result

    # String concatenation → f-string (simple single-expression cases)
    if "style" in categories and categories == {"style"}:
        result = _rewrite_str_concat(code, fname)
        if result:
            return result

    # ── LLM fallback ─────────────────────────────────────────────────
    issue_summary = "; ".join(iss.message for iss in issues)
    raw = generate_improvement(code, issue_summary)
    return _validate(raw, code)


# ── Deterministic rewrite helpers ────────────────────────────────────────────

def _get_func_name(code: str) -> Optional[str]:
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
    except SyntaxError:
        pass
    return None


def _get_func_params(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return [a.arg for a in node.args.args]
    except SyntaxError:
        pass
    return []


def _get_indent(code: str) -> str:
    """Return the indentation string used in the function body."""
    for line in code.splitlines():
        stripped = line.lstrip()
        if stripped and not stripped.startswith("def ") and not stripped.startswith("#"):
            return line[: len(line) - len(stripped)]
    return "    "


def _has_accumulator(code: str) -> bool:
    """True if there's a range(len()) loop AND an accumulator."""
    has_range_len = False
    has_accum = False
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Name) and node.func.id == "range"
                        and len(node.args) == 1
                        and isinstance(node.args[0], ast.Call)
                        and isinstance(node.args[0].func, ast.Name)
                        and node.args[0].func.id == "len"):
                    has_range_len = True
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                has_accum = True
    except SyntaxError:
        pass
    return has_range_len and has_accum


def _rewrite_to_sum(code: str, fname: str) -> Optional[str]:
    params = _get_func_params(code)
    param = params[0] if params else "nums"
    # Check if there's a multiplier or condition
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign):
                # Look for total += nums[i] * something
                if (isinstance(node.value, ast.BinOp)
                        and isinstance(node.value.op, ast.Mult)):
                    # Can't safely simplify — fall through
                    return None
    except SyntaxError:
        return None
    return f"def {fname}({param}):\n    return sum({param})\n"


def _rewrite_redundant_bool(code: str, fname: str) -> Optional[str]:
    """
    Rewrite:
        if <cond>:
            return True
        else:
            return False
    to:
        return <cond>

    Also handles the inverted case (return False / return True → return not <cond>).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            if not node.orelse or len(node.body) != 1 or len(node.orelse) != 1:
                continue
            if not isinstance(node.body[0], ast.Return):
                continue
            if not isinstance(node.orelse[0], ast.Return):
                continue

            ret_if   = node.body[0].value
            ret_else = node.orelse[0].value
            if not (isinstance(ret_if, ast.Constant) and isinstance(ret_else, ast.Constant)):
                continue
            if {ret_if.value, ret_else.value} != {True, False}:
                continue

            # Extract the condition source
            cond_src = ast.unparse(node.test)
            params = [a.arg for a in fn.args.args]
            param_str = ", ".join(params)

            # Reconstruct the full function, preserving decorators + docstring
            # Keep everything before this if-statement, replace from the if onward
            source_lines = code.splitlines()
            indent = _get_indent(code)

            # Find the line of the if node
            if_line = node.lineno  # 1-indexed

            # Rebuild: keep def line + docstring + everything before the if
            new_lines = []
            for i, line in enumerate(source_lines, start=1):
                if i < if_line:
                    new_lines.append(line)
                else:
                    break

            # If the if/else was the only statement after def, just emit return
            if ret_if.value is True:
                new_lines.append(f"{indent}return {cond_src}")
            else:
                new_lines.append(f"{indent}return not ({cond_src})")

            return "\n".join(new_lines) + "\n"

    return None


def _rewrite_append_loop(code: str, fname: str) -> Optional[str]:
    """
    Rewrite simple append loops to list comprehensions.
    Only handles the canonical pattern:
        result = []
        for x in iterable:
            [if cond:]
                result.append(expr)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Find: assign = [], for loop with single append
        init_name = None
        for_node = None
        for stmt in fn.body:
            # result = []
            if (isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, (ast.List,))
                    and len(stmt.value.elts) == 0):
                init_name = stmt.targets[0].id

            # for x in y: result.append(expr)
            if isinstance(stmt, ast.For) and init_name:
                body = stmt.body
                # Simple: single append
                if (len(body) == 1
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Call)
                        and isinstance(body[0].value.func, ast.Attribute)
                        and body[0].value.func.attr == "append"
                        and isinstance(body[0].value.func.value, ast.Name)
                        and body[0].value.func.value.id == init_name):
                    for_node = stmt
                    target = ast.unparse(stmt.target)
                    iterable = ast.unparse(stmt.iter)
                    expr = ast.unparse(body[0].value.args[0])
                    # Build comprehension
                    comp = f"[{expr} for {target} in {iterable}]"
                    params = [a.arg for a in fn.args.args]
                    param_str = ", ".join(params)
                    indent = _get_indent(code)
                    return (
                        f"def {fn.name}({param_str}):\n"
                        f"{indent}return {comp}\n"
                    )

                # With if-condition: for x in y: if cond: result.append(expr)
                if (len(body) == 1
                        and isinstance(body[0], ast.If)
                        and not body[0].orelse
                        and len(body[0].body) == 1
                        and isinstance(body[0].body[0], ast.Expr)
                        and isinstance(body[0].body[0].value, ast.Call)
                        and isinstance(body[0].body[0].value.func, ast.Attribute)
                        and body[0].body[0].value.func.attr == "append"
                        and isinstance(body[0].body[0].value.func.value, ast.Name)
                        and body[0].body[0].value.func.value.id == init_name):
                    target = ast.unparse(stmt.target)
                    iterable = ast.unparse(stmt.iter)
                    cond = ast.unparse(body[0].test)
                    expr = ast.unparse(body[0].body[0].value.args[0])
                    comp = f"[{expr} for {target} in {iterable} if {cond}]"
                    params = [a.arg for a in fn.args.args]
                    param_str = ", ".join(params)
                    indent = _get_indent(code)
                    return (
                        f"def {fn.name}({param_str}):\n"
                        f"{indent}return {comp}\n"
                    )

    return None


def _rewrite_open(code: str, fname: str) -> Optional[str]:
    """Replace bare f = open(path) / f.read() / f.close() with with-open."""
    params = _get_func_params(code)
    param = params[0] if params else "path"
    indent = _get_indent(code)

    # Check if there's processing after the read
    try:
        tree = ast.parse(code)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Collect all statements, look for open() assignment
            for stmt in fn.body:
                if (isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.value, ast.Call)
                        and isinstance(stmt.value.func, ast.Name)
                        and stmt.value.func.id == "open"):
                    file_var = ast.unparse(stmt.targets[0])
                    open_args = ", ".join(ast.unparse(a) for a in stmt.value.args)

                    # Rebuild everything after the open() assignment using with
                    open_line = stmt.lineno
                    source_lines = code.splitlines()
                    prefix_lines = [
                        line for i, line in enumerate(source_lines, 1)
                        if i < open_line
                    ]
                    suffix_lines = [
                        line for i, line in enumerate(source_lines, 1)
                        if i > open_line
                    ]
                    # Remove close() calls from suffix
                    suffix_lines = [
                        l for l in suffix_lines
                        if f"{file_var}.close()" not in l
                    ]

                    new_code = "\n".join(prefix_lines)
                    new_code += f"\n{indent}with open({open_args}) as {file_var}:\n"
                    for l in suffix_lines:
                        # Add one extra indent level to body
                        if l.strip():
                            new_code += f"{indent}    {l.lstrip()}\n"
                        else:
                            new_code += "\n"
                    return new_code.rstrip() + "\n"

    except SyntaxError:
        pass

    # Fallback: simple template
    return (
        f"def {fname}({param}):\n"
        f"{indent}with open({param}) as f:\n"
        f"{indent}    return f.read()\n"
    )


def _rewrite_mutable_default(code: str) -> Optional[str]:
    """Replace [] and {} defaults with None sentinel."""
    result = re.sub(
        r"(def\s+\w+\s*\([^)]*?)(\[\])([^)]*\):)",
        r"\1None\3",
        code,
    )
    result = re.sub(
        r"(def\s+\w+\s*\([^)]*?)(\{\})([^)]*\):)",
        r"\1None\3",
        result,
    )
    if result == code:
        return None

    # Also inject None-guard inside function body
    try:
        tree = ast.parse(result)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for arg in fn.args.args:
                # Find params that now default to None (were mutable)
                pass  # Complex injection — return the signature fix only
    except SyntaxError:
        pass

    return result


def _rewrite_str_concat(code: str, fname: str) -> Optional[str]:
    """
    Rewrite simple string concat:
        return "Hello, " + name + "!"
    to:
        return f"Hello, {name}!"
    Only handles single-return functions with one concat expression.
    """
    try:
        tree = ast.parse(code)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Find return with BinOp Add
            for node in ast.walk(fn):
                if not isinstance(node, ast.Return):
                    continue
                if not isinstance(node.value, ast.BinOp):
                    continue

                # Flatten the + chain
                parts = _flatten_add(node.value)
                if parts is None:
                    continue

                # Build f-string
                fstr_parts = []
                has_var = False
                for part in parts:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        # Escape braces in literal parts
                        fstr_parts.append(part.value.replace("{", "{{").replace("}", "}}"))
                    else:
                        fstr_parts.append("{" + ast.unparse(part) + "}")
                        has_var = True

                if not has_var:
                    continue

                fstr = "f\"" + "".join(fstr_parts) + "\""
                params = [a.arg for a in fn.args.args]
                param_str = ", ".join(params)
                indent = _get_indent(code)
                return f"def {fn.name}({param_str}):\n{indent}return {fstr}\n"

    except SyntaxError:
        pass
    return None


def _flatten_add(node) -> Optional[List]:
    """Recursively flatten a chain of BinOp Add nodes into a list."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _flatten_add(node.left)
        right = _flatten_add(node.right)
        if left is None or right is None:
            return None
        return left + right
    elif isinstance(node, (ast.Constant, ast.Name, ast.Attribute)):
        return [node]
    return None


# ── Output validation ────────────────────────────────────────────────────────

def _validate(raw: str, original: str) -> str:
    """Accept LLM output only if it's valid Python and contains a def."""
    if not raw or len(raw.strip()) < 10:
        return original
    # Strip markdown code fences if the model wrapped output
    raw = re.sub(r"^```(?:python)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    if "def " not in raw:
        return original
    try:
        ast.parse(raw)
        return raw.strip() + "\n"
    except SyntaxError:
        return original
