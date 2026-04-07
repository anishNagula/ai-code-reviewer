import streamlit as st
import torch
torch.set_num_threads(1)

from agents import summariser_agent, reviewer_agent, improvement_agent

st.set_page_config(page_title="AI Code Reviewer", layout="wide")

# Styling
st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
}
</style>
""", unsafe_allow_html=True)

st.title("🤖 AI Code Reviewer")
st.caption("Agentic Code Analysis (Summariser + Reviewer + Improver)")

code = st.text_area("Paste your code here", height=300)

if st.button("Analyze Code"):

    if not code.strip():
        st.warning("Please enter some code")
    else:
        with st.spinner("Analyzing..."):

            summary = summariser_agent(code)
            review = reviewer_agent(code)
            improvements = improvement_agent(code, review)

            st.divider()

            col1, col2 = st.columns(2)

            with col1:
                st.subheader("📘 Code Explanation")
                st.markdown(summary)

                st.subheader("⚠️ Issues")
                st.markdown(review)

            with col2:
                st.subheader("🚀 Optimized Code")
                st.code(improvements, language="python")

            st.divider()

            with st.expander("📂 Input Code"):
                st.code(code, language="python")
