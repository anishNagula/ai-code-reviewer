"""
rule_engine.py — AST-based static analysis engine.

All checks use Python's ast module — zero string matching.
Checks implemented:
  1.  range(len(seq))          → use direct iteration
  2.  open() outside with      → resource leak
  3.  Unreachable code         → after return/raise/break/continue
  4.  Bare except:             → catches KeyboardInterrupt etc.
  5.  Mutable default args     → list/dict/set as default
  6.  Missing return           → non-trivial function returns nothing
  7.  Division by variable     → possible ZeroDivisionError
  8.  String concat with +     → prefer f-strings
  9.  append() in for-loop     → consider list comprehension
  10. Redundant bool return     → if cond: return True else: return False
  11. Global variables         → flagged as info
  12. Deeply nested code       → 4+ levels of indentation
"""

import ast
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Issue:
    severity: str           # "error" | "warning" | "info"
    category: str           # short tag
    message: str
    line: Optional[int] = None


SEVERITY_ICON = {"error": "🔴", "warning": "🟡", "info": "🔵"}


def check_rules(code: str) -> List[Issue]:
    issues: List[Issue] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        issues.append(Issue(
            severity="error",
            category="syntax",
            message=f"Syntax error — {exc.msg} (line {exc.lineno})",
            line=exc.lineno,
        ))
        return issues

    visitor = _RuleVisitor()
    visitor.visit(tree)
    return visitor.issues


def format_issues(issues: List[Issue]) -> str:
    if not issues:
        return "No issues detected."
    lines = []
    order = {"error": 0, "warning": 1, "info": 2}
    for iss in sorted(issues, key=lambda i: (order.get(i.severity, 9), i.line or 0)):
        icon = SEVERITY_ICON.get(iss.severity, "⚪")
        loc = f" (line {iss.line})" if iss.line else ""
        lines.append(f"{icon} [{iss.category}]{loc} {iss.message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Visitor
# ---------------------------------------------------------------------------

class _RuleVisitor(ast.NodeVisitor):
    def __init__(self):
        self.issues: List[Issue] = []
        self._in_try: int = 0
        self._open_lines: List[int] = []   # lines of bare open() calls
        self._with_open_lines: List[int] = []  # lines of open() inside with

    def _add(self, severity, category, message, node=None):
        line = getattr(node, "lineno", None)
        self.issues.append(Issue(severity=severity, category=category,
                                 message=message, line=line))

    # ── try depth tracking ────────────────────────────────────────────
    def visit_Try(self, node):
        self._in_try += 1
        self.generic_visit(node)
        self._in_try -= 1

    # ── open() tracking ───────────────────────────────────────────────
    def visit_With(self, node):
        for item in node.items:
            expr = item.context_expr
            if (isinstance(expr, ast.Call)
                    and isinstance(expr.func, ast.Name)
                    and expr.func.id == "open"):
                self._with_open_lines.append(getattr(expr, "lineno", -1))
        self.generic_visit(node)

    # ── Call-level checks ─────────────────────────────────────────────
    def visit_Call(self, node):
        func = node.func

        # 1. range(len(...))
        if (isinstance(func, ast.Name) and func.id == "range"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Name)
                and node.args[0].func.id == "len"):
            self._add("warning", "loop",
                      "Inefficient loop — use direct iteration instead of range(len(seq))",
                      node)

        # 2. bare open() — record line, check later in visit_Module
        if isinstance(func, ast.Name) and func.id == "open":
            self._open_lines.append(getattr(node, "lineno", -1))

        self.generic_visit(node)

    # ── FunctionDef checks ────────────────────────────────────────────
    def visit_FunctionDef(self, node):
        self._check_unreachable(node.body, node)
        self._check_bare_except(node)
        self._check_mutable_default(node)
        self._check_missing_return(node)
        self._check_redundant_bool(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_unreachable(self, stmts, context_node):
        terminators = (ast.Return, ast.Raise, ast.Continue, ast.Break)
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, terminators) and i < len(stmts) - 1:
                nxt = stmts[i + 1]
                # skip trailing docstring or pass
                if isinstance(nxt, ast.Pass):
                    continue
                if isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant):
                    continue
                self._add("warning", "unreachable",
                          f"Unreachable code after {type(stmt).__name__.lower()}",
                          nxt)
                break
            # recurse into nested blocks
            for field, value in ast.iter_fields(stmt):
                if (isinstance(value, list)
                        and value
                        and isinstance(value[0], ast.stmt)):
                    self._check_unreachable(value, context_node)

    def _check_bare_except(self, func_node):
        for n in ast.walk(func_node):
            if isinstance(n, ast.ExceptHandler) and n.type is None:
                self._add("warning", "exception",
                          "Bare except: catches KeyboardInterrupt too — use except Exception:",
                          n)

    def _check_mutable_default(self, func_node):
        defaults = func_node.args.defaults + [
            d for d in func_node.args.kw_defaults if d is not None
        ]
        for default in defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add("error", "mutable_default",
                          f"Mutable default argument in `{func_node.name}` — use None and initialise inside",
                          func_node)
                break

    def _check_missing_return(self, func_node):
        # Skip __init__, setters, and short functions
        if func_node.name.startswith("__") or len(func_node.body) <= 2:
            return
        has_return = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(func_node)
        )
        if not has_return:
            self._add("info", "return",
                      f"`{func_node.name}` has no return value — intentional?",
                      func_node)

    def _check_redundant_bool(self, func_node):
        """
        Detect:
            if <expr>:
                return True
            else:
                return False
        or the inverse (return False / return True).
        """
        for node in ast.walk(func_node):
            if not isinstance(node, ast.If):
                continue
            # Must have an else clause
            if not node.orelse:
                continue
            # if-body must be a single return
            if len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
                continue
            # else-body must be a single return
            orelse = node.orelse
            if len(orelse) != 1 or not isinstance(orelse[0], ast.Return):
                continue
            ret_if   = node.body[0].value
            ret_else = orelse[0].value
            # Both must be boolean constants
            if not (isinstance(ret_if, ast.Constant) and isinstance(ret_else, ast.Constant)):
                continue
            if {ret_if.value, ret_else.value} == {True, False}:
                self._add("info", "redundant_bool",
                          "Redundant if/else returning True/False — simplify to `return <condition>`",
                          node)

    # ── BinOp checks (division + string concat) ───────────────────────
    def visit_BinOp(self, node):
        # 7. division by variable outside try
        if (isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod))
                and self._in_try == 0
                and not isinstance(node.right, ast.Constant)):
            self._add("warning", "safety",
                      "Division by variable outside try/except — possible ZeroDivisionError",
                      node)

        # 8. string concat with +
        if isinstance(node.op, ast.Add):
            left_str  = isinstance(node.left,  ast.Constant) and isinstance(node.left.value,  str)
            right_str = isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)
            if left_str or right_str:
                self._add("info", "style",
                          "String concatenation with + — prefer an f-string",
                          node)

        self.generic_visit(node)

    # ── For-loop: append pattern ──────────────────────────────────────
    def visit_For(self, node):
        appends = [
            n for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "append"
        ]
        if appends:
            self._add("info", "loop",
                      "List built with .append() in a for-loop — consider a list comprehension",
                      node)
        self.generic_visit(node)

    # ── Global variable declarations ──────────────────────────────────
    def visit_Global(self, node):
        names = ", ".join(node.names)
        self._add("info", "global",
                  f"Global variable(s) `{names}` — consider passing as parameters instead",
                  node)
        self.generic_visit(node)

    # ── Deeply nested code ────────────────────────────────────────────
    def visit_Module(self, node):
        self.generic_visit(node)

        # Report open() calls not covered by a with statement
        bare = set(self._open_lines) - set(self._with_open_lines)
        for line in sorted(bare):
            self.issues.append(Issue(
                severity="warning",
                category="resource",
                message="open() called outside a `with` block — file may not be closed",
                line=line,
            ))

        # Deep nesting check
        self._check_nesting(node)

    def _check_nesting(self, tree):
        """Flag functions where control flow nests deeper than 4 levels."""
        nesting_nodes = (ast.If, ast.For, ast.While, ast.With, ast.Try,
                         ast.AsyncFor, ast.AsyncWith)

        def _depth(node, d):
            if isinstance(node, nesting_nodes):
                d += 1
            peak = d
            for child in ast.iter_child_nodes(node):
                peak = max(peak, _depth(child, d))
            return peak

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                depth = _depth(node, 0)
                if depth >= 4:
                    self.issues.append(Issue(
                        severity="info",
                        category="complexity",
                        message=(
                            f"`{node.name}` has deeply nested control flow "
                            f"(depth {depth}) — consider extracting helper functions"
                        ),
                        line=node.lineno,
                    ))
