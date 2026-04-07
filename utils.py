"""
utils.py — Output formatting helpers.
"""
from typing import List
from rule_engine import Issue, SEVERITY_ICON


def severity_counts(issues: List[Issue]) -> dict:
    counts = {"error": 0, "warning": 0, "info": 0}
    for iss in issues:
        counts[iss.severity] = counts.get(iss.severity, 0) + 1
    return counts


def format_output(summary: str, issues: List[Issue], improvements: str) -> str:
    """Full Markdown report (used for exports / expanders)."""
    issue_lines = []
    for iss in sorted(issues, key=lambda i: ({"error":0,"warning":1,"info":2}.get(i.severity,9), i.line or 0)):
        icon = SEVERITY_ICON.get(iss.severity, "⚪")
        loc = f" *(line {iss.line})*" if iss.line else ""
        issue_lines.append(f"{icon} **[{iss.category}]**{loc} {iss.message}")

    issues_block = "\n\n".join(issue_lines) if issue_lines else "✅ No issues detected."

    return (
        f"## 📘 Explanation\n\n{summary}\n\n"
        f"---\n\n## ⚠️ Issues\n\n{issues_block}\n\n"
        f"---\n\n## 🚀 Optimized Code\n\n```python\n{improvements}\n```"
    )
