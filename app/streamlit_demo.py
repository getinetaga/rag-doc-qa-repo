"""Streamlit in-process demo for the RAG document QA pipeline.

This demo runs the ingestion -> chunking -> embeddings -> vector index ->
LLM generation pipeline entirely in-process so you can try the project
locally without running the FastAPI server.

Usage notes:
- Install project dependencies (see `requirements.txt`).
- Set `OPENAI_API_KEY` or `HUGGINGFACE_API_KEY` in your environment if you
  want the demo to call an external LLM provider.

The UI is intentionally minimal and uses `st.session_state` to cache the
configured `VectorStore` so you can ask multiple questions without
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
if "history_cleared" not in st.session_state:
    st.session_state.history_cleared = False

# ---------------------------------------------------------------------------
# Event handler callbacks — defined before any widget renders so Streamlit
# can reference them during the current run.
# ---------------------------------------------------------------------------

def on_file_change() -> None:
    """Reset the indexed state whenever the user selects a different file.

    Fires via the ``on_change`` hook of ``st.file_uploader``.  If the new
    file is *different* from the one that is already indexed (or if the
    uploader was cleared), we invalidate the cached ``VectorStore`` so the
    user never queries stale results.
    """
    new_file = st.session_state.get("uploaded_file_widget")
    if new_file is None or new_file.name != st.session_state.doc_name:
        st.session_state.vector_store = None
        st.session_state.doc_name = ""
        st.session_state.chat_history = []


def on_clear_history() -> None:
    """Clear the conversation log and set a flag to show a confirmation toast.

    Fires via the ``on_click`` hook of the *Clear history* button so the
    state mutation is decoupled from the render path.
    """
    st.session_state.chat_history = []
    st.session_state.history_cleared = True


col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Upload Document")
    # Accept common document types; the ingestion module will detect and
    # extract text from PDF, DOCX, or plain text files.
    # key= lets on_change read st.session_state.uploaded_file_widget;
    # on_change resets the index whenever the selected file changes.
    uploaded_file = st.file_uploader(
        "Upload a PDF, DOCX or TXT file",
        type=["pdf", "docx", "txt"],
        key="uploaded_file_widget",
        on_change=on_file_change,
    )

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

                    st.success(
                        f"✅ Document processed and indexed using `{getattr(vs, 'backend', 'faiss')}`!"
                    )
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
        # Wrap input + submit in a form so pressing Enter also fires
        # the submit event (st.form_submit_button responds to Enter).
        with st.form(key="question_form", clear_on_submit=True):
            question = st.text_input("Enter your question:")
            submitted = st.form_submit_button("🔍 Get answer")

        # `submitted` and `question` remain in scope after the form block.
        if submitted and question:
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

        # on_click fires the callback before the re-render; avoids inline
        # state mutation in the render path.
        st.button("🗑️ Clear history", on_click=on_clear_history)
        if st.session_state.history_cleared:
            st.toast("Conversation history cleared.", icon="🗑️")
            st.session_state.history_cleared = False

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
    st.write("Runs the pipeline locally: ingestion -> chunking -> embeddings -> vector search (FAISS / pgvector) -> LLM generation.")
    st.write(f"Vector backend: `{getattr(st.session_state.vector_store, 'backend', 'faiss')}`")
    st.markdown("---")
    st.write("Requirements: the project's Python dependencies must be installed (see requirements.txt).\nIf you use OpenAI or Hugging Face as the LLM backend, set the corresponding API keys in the environment before running the demo.")
    st.markdown("---")
    if st.session_state.vector_store:
        st.success("Indexed: yes")
    else:
        st.warning("Indexed: no")
