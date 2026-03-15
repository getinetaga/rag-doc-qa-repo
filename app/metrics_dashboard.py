"""Simple Streamlit dashboard for retrieval evaluation metrics.

This lightweight dashboard visualizes example retrieval metrics such as
Precision@K and Recall@K and exposes a simple CI/CD-style Quality Gate
that can be used to fail builds when retrieval quality regresses.

Notes:
- The file currently contains synthetic/sample data for local exploration.
    Replace the `Ks`, `precision_scores`, `recall_scores`, and
    `topk_accuracy` variables with real evaluation outputs in your pipeline.
- Intended for development and lightweight demos; production monitoring
    should integrate with log/metrics backends (Prometheus, Grafana, etc.).
"""

import streamlit as st
import matplotlib.pyplot as plt

# Page configuration
st.set_page_config(page_title="RAG Retrieval Metrics", layout="wide")
st.title("📊 Retrieval Performance Dashboard")

# -------------------------
# Sample evaluation results
# (Replace with real data later),Where to get real data?
#  You would replace the synthetic/sample data with real evaluation outputs from your retrieval evaluation pipeline.
#  This could be done by running your evaluation scripts and outputting the metrics to a file (e.g., JSON, CSV) 
# that this dashboard can read, or by integrating this dashboard directly into your evaluation code to pass the metrics
# -------------------------
Ks = [1, 3, 5, 10]
precision_scores = [0.82, 0.78, 0.74, 0.65]
recall_scores = [0.40, 0.62, 0.75, 0.88]
topk_accuracy = 0.92

# Thresholds (CI/CD Quality Gate). Are this thresholds arbitrary? Yes, these thresholds are currently set 
# to example values (e.g., 0.70 for Precision@5, 0.65 for Recall@5, and 0.90 for Top-5 Accuracy).
#  You should adjust these thresholds based on the specific requirements and performance characteristics of your application and use case.

PRECISION_THRESHOLD = 0.70
RECALL_THRESHOLD = 0.65
TOPK_THRESHOLD = 0.90

# -------------------------
# Metrics Summary
# -------------------------
st.subheader("📌 Retrieval Quality Summary")

col1, col2, col3 = st.columns(3)

col1.metric("Precision@5", f"{precision_scores[2]:.2f}")
col2.metric("Recall@5", f"{recall_scores[2]:.2f}")
col3.metric("Top-5 Accuracy", f"{topk_accuracy:.2f}")

# -------------------------
# Quality Gate. What is a quality gate? A quality gate is a set of conditions or thresholds that must be met 
# for a software build or deployment to be considered successful. In the context of this dashboard, the quality gate checks 
# whether the retrieval metrics (Precision@5, Recall@5, and Top-5 Accuracy) meet or exceed predefined thresholds. 
# If all conditions are satisfied, the gate passes; otherwise, it fails, which can be used to automatically 
# fail CI/CD builds when retrieval performance regresses.
# -------------------------
st.subheader("🚦 CI/CD Retrieval Quality Gate")

if (
    precision_scores[2] >= PRECISION_THRESHOLD and
    recall_scores[2] >= RECALL_THRESHOLD and
    topk_accuracy >= TOPK_THRESHOLD
):
    st.success("✅ Retrieval Quality Gate PASSED")
else:
    st.error("❌ Retrieval Quality Gate FAILED")

# -------------------------
# Precision@K Plot. What is Precision@K? Precision@K is a metric used to evaluate the performance of 
# information retrieval systems. It measures the proportion of relevant items among the top K retrieved items. 
# For example, Precision@5 would calculate how many of the top 5 retrieved items are relevant to the query. 
# A higher Precision@K indicates that the retrieval system is returning more relevant results within the top K items.
# -------------------------
st.subheader("📈 Precision@K vs K")

fig1, ax1 = plt.subplots()
ax1.plot(Ks, precision_scores, marker="o")
ax1.set_xlabel("Top-K Retrieved Chunks")
ax1.set_ylabel("Precision@K")
ax1.set_title("Precision@K Curve")
ax1.grid(True)

st.pyplot(fig1)

# -------------------------
# Recall@K . how to intergarte in to the dashboard? The Recall@K plot is integrated into the dashboard 
# as a separate section that visualizes how Recall@K changes with different values of K.
# -------------------------
st.subheader("📈 Recall@K vs K")

fig2, ax2 = plt.subplots()
ax2.plot(Ks, recall_scores, marker="o")
ax2.set_xlabel("Top-K Retrieved Chunks")
ax2.set_ylabel("Recall@K")
ax2.set_title("Recall@K Curve")
ax2.grid(True)

st.pyplot(fig2)

# -------------------------
# Interpretation Section
# -------------------------
st.subheader("🧠 Interpretation")

st.markdown("""
- **Precision@K** decreases gradually as K increases, indicating controlled noise.
- **Recall@K** improves with larger K, ensuring better information coverage.
- **Quality Gate** ensures retrieval regressions fail CI/CD automatically.
""")

#How to Run the Dashboard
#streamlit run app/streamlit_demo/metrics_dashboard.py