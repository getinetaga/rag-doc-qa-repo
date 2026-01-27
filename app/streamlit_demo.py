"""Streamlit in-process demo for the RAG document QA pipeline.

This demo runs the ingestion -> chunking -> embeddings -> vector index ->
LLM generation pipeline entirely in-process so you can try the project
locally without running the FastAPI server.

Usage notes:
- Install project dependencies (see `requirements.txt`).
- Set `OPENAI_API_KEY` or `HUGGINGFACE_API_KEY` in your environment if you
  want the demo to call an external LLM provider.

The UI is intentionally minimal and uses `st.session_state` to cache the
in-memory `VectorStore` so you can ask multiple questions without
re-indexing.
"""

import os
import tempfile
import time

import streamlit as st

# Pipeline building blocks (local package modules)
from app.chunking import chunk_text
from app.embeddings import embed_text
from app.ingestion import extract_text
from app.rag import generate_answer
from app.vector_store import VectorStore

# Streamlit page configuration
st.set_page_config(page_title="RAG Demo (in-process)", page_icon="📚", layout="wide")

st.title("📚 RAG Document QA — In-Process Demo")
st.write("This demo runs the ingestion + retrieval pipeline locally without the FastAPI server.")

# ---------------------------------------------------------------------------
# Session-state keys used by this demo
# - `vector_store`: the in-memory VectorStore instance after indexing
# - `doc_name`: original filename of the uploaded document
# - `chat_history`: list of past Q&A dictionaries for the session
# ---------------------------------------------------------------------------
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "doc_name" not in st.session_state:
    st.session_state.doc_name = ""
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Upload Document")
    # Accept common document types; the ingestion module will detect and
    # extract text from PDF, DOCX, or plain text files.
    uploaded_file = st.file_uploader("Upload a PDF, DOCX or TXT file", type=["pdf", "docx", "txt"]) 

    if uploaded_file is not None:
        st.info(f"Selected file: {uploaded_file.name} — {uploaded_file.size/1024:.1f} KB")

        if st.button("🚀 Process document"):
            # Process document: save to a temporary file and run the local
            # pipeline: extract -> chunk -> embed -> index.
            with st.spinner("Processing document — extracting, chunking, embedding..."):
                try:
                    # Persist upload to a temp file for the ingestion helpers
                    suffix = os.path.splitext(uploaded_file.name)[1]
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp.write(uploaded_file.getvalue())
                    tmp.close()

                    # Run local pipeline
                    text = extract_text(tmp.name)
                    chunks = chunk_text(text)
                    embeddings = embed_text(chunks)

                    # Create a small in-memory VectorStore and add vectors
                    vs = VectorStore(dim=len(embeddings[0]))
                    vs.add(embeddings, chunks)

                    # Cache the index in session state for subsequent queries
                    st.session_state.vector_store = vs
                    st.session_state.doc_name = uploaded_file.name
                    st.session_state.chat_history = []

                    # Cleanup temporary file
                    os.remove(tmp.name)

                    st.success("✅ Document processed and indexed locally!")
                    st.balloons()
                except Exception as e:
                    # Surface any processing errors to the user
                    st.error(f"Processing failed: {e}")

    if st.session_state.vector_store:
        st.markdown(f"**Indexed document:** {st.session_state.doc_name}")

with col2:
    st.header("💬 Ask Questions")

    if not st.session_state.vector_store:
        st.info("Please upload and process a document first.")
    else:
        # Simple question input and submit button. On submit we call
        # `generate_answer` which performs retrieval + LLM generation.
        question = st.text_input("Enter your question:")
        if st.button("🔍 Get answer") and question:
            with st.spinner("Generating answer — this may call your configured LLM..."):
                try:
                    answer = generate_answer(question, st.session_state.vector_store)

                    # Append to session chat history so the user can review
                    st.session_state.chat_history.append({
                        "question": question,
                        "answer": answer,
                        "timestamp": time.strftime("%H:%M:%S")
                    })

                except Exception as e:
                    st.error(f"Answer generation failed: {e}")

        if st.button("🗑️ Clear history"):
            st.session_state.chat_history = []

# Show past Q&A interactions (most recent first)
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
