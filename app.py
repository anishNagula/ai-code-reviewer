import streamlit as st
import torch

torch.set_num_threads(2)

# ── Page config ─────────────────────────────────────────────────
st.set_page_config(
    page_title="CodeLens · AI Code Reviewer",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS — dark terminal aesthetic ───────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600&family=DM+Sans:wght@300;400;600&display=swap');

/* ── Global ── */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background: #0d0f14;
    color: #c9d1d9;
}

/* ── Header strip ── */
.header-strip {
    background: linear-gradient(135deg, #0f1117 0%, #161b22 100%);
    border-bottom: 1px solid #21262d;
    padding: 1.6rem 2rem 1.2rem;
    margin: -1rem -1rem 2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
}

.header-logo {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.5rem;
    font-weight: 600;
    color: #58a6ff;
    letter-spacing: -0.03em;
}

.header-tagline {
    font-size: 0.8rem;
    color: #6e7681;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

/* ── Panels ── */
.panel {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1rem;
}

.panel-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #58a6ff;
    margin-bottom: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

/* ── Badges ── */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.2rem 0.55rem;
    border-radius: 20px;
    margin-right: 0.4rem;
}

.badge-error   { background:#3d1212; color:#f85149; border:1px solid #6b1a1a; }
.badge-warning { background:#2d2208; color:#e3b341; border:1px solid #5a440a; }
.badge-info    { background:#0d1f33; color:#58a6ff; border:1px solid #1f3b59; }
.badge-ok      { background:#0d2118; color:#3fb950; border:1px solid #1a4229; }

/* ── Issue cards ── */
.issue-card {
    display: block; /* Ensure full width */
    border-left: 3px solid;
    border-radius: 0 6px 6px 0;
    padding: 0.8rem 1rem; /* Slightly more padding */
    margin-bottom: 0.6rem !important; /* Force separation between cards */
    font-size: 0.85rem;
    background: #0d1117;
}

.issue-card.error   { border-color: #f85149; }
.issue-card.warning { border-color: #e3b341; }
.issue-card.info    { border-color: #58a6ff; }

.issue-tag {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-right: 0.5rem;
}

.issue-line {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    color: #8b949e;
    margin-right: 0.8rem;
}

/* ── Textarea overrides ── */
.stTextArea textarea {
    background: #0d1117 !important;
    color: #c9d1d9 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    border: 1px solid #21262d !important;
    border-radius: 8px !important;
}

/* ── Button ── */
.stButton > button {
    background: linear-gradient(135deg, #1f6feb 0%, #388bfd 100%);
    color: #ffffff;
    font-family: 'DM Sans', sans-serif;
    font-weight: 600;
    font-size: 0.88rem;
    border: none;
    border-radius: 8px;
    padding: 0.55rem 1.6rem;
    width: 100%;
}

/* ── Summary prose ── */
.summary-container {
    background: #161b22;
    padding: 1rem;
    border-radius: 8px;
    border: 1px solid #21262d;
    font-size: 0.9rem;
    line-height: 1.6;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Lazy imports ───────────────────────────────────────────────
from agents import summariser_agent, reviewer_agent, improvement_agent
from utils import severity_counts

# ── Header ──────────────────────────────────────────────────────
st.markdown("""
<div class="header-strip">
    <div>
        <div class="header-logo">🔬 CodeLens</div>
        <div class="header-tagline">Multi-Agent AI Code Reviewer · CodeT5+ · AST Engine</div>
    </div>
</div>
""", unsafe_allow_html=True)

left, right = st.columns([5, 7], gap="large")

# ════════════════════════════════════════════════════════════════
# LEFT — Input pane
# ════════════════════════════════════════════════════════════════
with left:
    st.markdown('<div class="panel-title">📄 INPUT CODE</div>', unsafe_allow_html=True)
    code = st.text_area(
        label="",
        height=360,
        placeholder="# Paste your Python function here...",
        label_visibility="collapsed",
    )

    run = st.button("⚡  Analyze Code", use_container_width=True)

    st.markdown("""
    <div class="panel" style="margin-top:1rem;">
        <div class="panel-title">🧠 PIPELINE</div>
        <div style="font-size:0.82rem; color:#8b949e; line-height:1.8;">
            <b style="color:#58a6ff;">Summariser</b> → Salesforce/codet5p-220m<br>
            <b style="color:#e3b341;">Reviewer</b>&nbsp;&nbsp; → Python AST engine<br>
            <b style="color:#3fb950;">Improver</b>&nbsp;&nbsp; → Rule transforms + codet5p-770m
        </div>
    </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# RIGHT — Results pane
# ════════════════════════════════════════════════════════════════
with right:
    if not run:
        st.markdown("""
        <div style="display:flex; align-items:center; justify-content:center;
                    height:440px; flex-direction:column; gap:0.6rem;
                    color:#30363d; font-family:'JetBrains Mono',monospace;">
            <div style="font-size:3rem;">⬅</div>
            <div style="font-size:0.8rem; letter-spacing:0.1em; text-transform:uppercase;">
                Paste code and click Analyze
            </div>
        </div>
        """, unsafe_allow_html=True)

    elif not code.strip():
        st.warning("Please paste some Python code first.")

    else:
        with st.spinner("Running pipeline..."):
            summary = summariser_agent(code)
            issues, issues_md = reviewer_agent(code)
            counts = severity_counts(issues)
            improved = improvement_agent(code, issues)

        # ── Summary section ──
        # Fixed: We render Markdown directly so formatting works, but keep the title styling
        st.markdown('<div class="panel-title">📘 EXPLANATION</div>', unsafe_allow_html=True)
        st.markdown(summary) 

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Issues section ──
        st.markdown('<div class="panel-title">⚠️ DETECTED ISSUES</div>', unsafe_allow_html=True)
        
        badge_html = '<div style="margin-bottom:0.8rem;">'
        if counts["error"]:
            badge_html += f'<span class="badge badge-error">🔴 {counts["error"]} error{"s" if counts["error"]!=1 else ""}</span>'
        if counts["warning"]:
            badge_html += f'<span class="badge badge-warning">🟡 {counts["warning"]} warning{"s" if counts["warning"]!=1 else ""}</span>'
        if counts["info"]:
            badge_html += f'<span class="badge badge-info">🔵 {counts["info"]} suggestion{"s" if counts["info"]!=1 else ""}</span>'
        if not issues:
            badge_html += '<span class="badge badge-ok">✅ Clean</span>'
        badge_html += '</div>'
        st.markdown(badge_html, unsafe_allow_html=True)

        if issues:
            # Fixed: Wrapped in a container or used display:block to prevent compression
            for iss in sorted(issues, key=lambda i: ("error","warning","info").index(i.severity)):
                sev_color = {"error":"#f85149","warning":"#e3b341","info":"#58a6ff"}.get(iss.severity,"#8b949e")
                line_info = f'<span class="issue-line">L{iss.line}</span>' if iss.line else ""
                
                st.markdown(f"""
                <div class="issue-card {iss.severity}">
                    <div style="display: flex; align-items: center; margin-bottom: 4px;">
                        <span class="issue-tag" style="color:{sev_color};">{iss.category}</span>
                        {line_info}
                    </div>
                    <div style="color:#c9d1d9;">{iss.message}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="issue-card info" style="border-color:#3fb950; color:#3fb950;">✅ No issues detected</div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Improved code section ──
        st.markdown('<div class="panel-title">🚀 OPTIMIZED CODE</div>', unsafe_allow_html=True)
        if improved.strip() == code.strip():
            st.info("No changes suggested.")
        else:
            st.code(improved, language="python")

        with st.expander("📂 Original Input"):
            st.code(code, language="python")
