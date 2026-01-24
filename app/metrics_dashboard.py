import streamlit as st
import matplotlib.pyplot as plt

st.set_page_config(page_title="RAG Retrieval Metrics", layout="wide")
st.title("📊 Retrieval Performance Dashboard")

# -------------------------
# Sample evaluation results
# (Replace with real data later)
# -------------------------
Ks = [1, 3, 5, 10]
precision_scores = [0.82, 0.78, 0.74, 0.65]
recall_scores = [0.40, 0.62, 0.75, 0.88]
topk_accuracy = 0.92

# Thresholds (CI/CD Quality Gate)
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
# Quality Gate
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
# Precision@K Plot
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
# Recall@K Plot
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