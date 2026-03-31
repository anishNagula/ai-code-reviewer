def format_output(summary, rule_issues, review, improvements):

    rule_text = "\n".join([f"- {r}" for r in rule_issues]) if rule_issues else "No rule violations detected."

    return f"""
## 📘 Code Explanation
{summary}

---

## ⚠️ Detected Issues (Rule-Based)
{rule_text}

---

## 🤖 AI Insights
{review}

---

## 🚀 Optimized Code Suggestion

{improvements}
"""
