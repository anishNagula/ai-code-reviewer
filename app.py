import streamlit as st
import torch
torch.set_num_threads(1)

from agents import summariser_agent, reviewer_agent, improvement_agent
from rule_engine import check_rules

st.set_page_config(page_title="AI Code Reviewer", layout="wide")

# 🔥 Custom styling
st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
}
h1, h2, h3 {
    color: #ffffff;
}
</style>
""", unsafe_allow_html=True)

# Header
st.title("🤖 AI Code Reviewer")
st.caption("Hybrid Code Analysis (Rule-Based + AI)")

# Input
code = st.text_area("Paste your code here", height=300)

analyze = st.button("Analyze Code")

if analyze:
    if not code.strip():
        st.warning("Please enter some code")
    else:
        with st.spinner("Analyzing..."):

            # 🔥 Run pipeline
            rule_issues = check_rules(code)
            summary = summariser_agent(code)
            review = reviewer_agent(code)
            improvements = improvement_agent(code)

            st.divider()

            # 🔥 Status badge
            if rule_issues:
                st.error(f"⚠️ {len(rule_issues)} Issue(s) Detected")
            else:
                st.success("✅ No Issues Found")

            st.divider()

            # 🔥 Layout (2 columns)
            col1, col2 = st.columns(2)

            # LEFT SIDE
            with col1:
                st.subheader("📘 Code Explanation")
                st.markdown(summary)

                st.subheader("⚠️ Detected Issues")
                if rule_issues:
                    for issue in rule_issues:
                        st.markdown(f"- {issue}")
                else:
                    st.markdown("No issues detected.")

            # RIGHT SIDE
            with col2:
                st.subheader("🤖 AI Insights")
                st.markdown(review)

                st.subheader("🚀 Optimized Code")
                st.code(improvements, language="python")

            st.divider()

            # 🔥 Optional: show original code
            with st.expander("📂 Show Input Code"):
                st.code(code, language="python")
