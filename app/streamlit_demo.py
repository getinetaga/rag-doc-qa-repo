import os
import tempfile
import time

import streamlit as st

from app.chunking import chunk_text
from app.embeddings import embed_text
from app.ingestion import extract_text
from app.rag import generate_answer
from app.vector_store import VectorStore

st.set_page_config(page_title="RAG Demo (in-process)", page_icon="📚", layout="wide")

st.title("📚 RAG Document QA — In-Process Demo")
st.write("This demo runs the ingestion + retrieval pipeline locally without the FastAPI server.")

# Session state
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "doc_name" not in st.session_state:
    st.session_state.doc_name = ""
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Upload Document")
    uploaded_file = st.file_uploader("Upload a PDF, DOCX or TXT file", type=["pdf", "docx", "txt"]) 

    if uploaded_file is not None:
        st.info(f"Selected file: {uploaded_file.name} — {uploaded_file.size/1024:.1f} KB")

        if st.button("🚀 Process document"):
            with st.spinner("Processing document — extracting, chunking, embedding..."):
                try:
                    # Save to temp file
                    suffix = os.path.splitext(uploaded_file.name)[1]
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp.write(uploaded_file.getvalue())
                    tmp.close()

                    # Run local pipeline
                    text = extract_text(tmp.name)
                    chunks = chunk_text(text)
                    embeddings = embed_text(chunks)

                    vs = VectorStore(dim=len(embeddings[0]))
                    vs.add(embeddings, chunks)

                    # Store in session state
                    st.session_state.vector_store = vs
                    st.session_state.doc_name = uploaded_file.name
                    st.session_state.chat_history = []

                    os.remove(tmp.name)

                    st.success("✅ Document processed and indexed locally!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Processing failed: {e}")

    if st.session_state.vector_store:
        st.markdown(f"**Indexed document:** {st.session_state.doc_name}")

with col2:
    st.header("💬 Ask Questions")

    if not st.session_state.vector_store:
        st.info("Please upload and process a document first.")
    else:
        question = st.text_input("Enter your question:")
        if st.button("🔍 Get answer") and question:
            with st.spinner("Generating answer — this may call your configured LLM..."):
                try:
                    answer = generate_answer(question, st.session_state.vector_store)

                    st.session_state.chat_history.append({
                        "question": question,
                        "answer": answer,
                        "timestamp": time.strftime("%H:%M:%S")
                    })

                except Exception as e:
                    st.error(f"Answer generation failed: {e}")

        if st.button("🗑️ Clear history"):
            st.session_state.chat_history = []

# Show history
if st.session_state.chat_history:
    st.markdown("---")
    st.header("📝 Conversation")
    for msg in reversed(st.session_state.chat_history):
        st.markdown(f"**Q:** {msg['question']}")
        st.info(f"{msg['answer']}")
        st.caption(msg["timestamp"])

with st.sidebar:
    st.header("ℹ️ About this demo")
    st.write("Runs the pipeline locally: ingestion -> chunking -> embeddings -> FAISS -> LLM generation.")
    st.markdown("---")
    st.write("Requirements: the project's Python dependencies must be installed (see requirements.txt).\nIf you use OpenAI or Hugging Face as the LLM backend, set the corresponding API keys in the environment before running the demo.")
    st.markdown("---")
    if st.session_state.vector_store:
        st.success("Indexed: yes")
    else:
        st.warning("Indexed: no")
