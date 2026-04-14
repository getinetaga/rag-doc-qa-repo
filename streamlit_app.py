import streamlit as st
import requests
import time

# Configure page
st.set_page_config(
    page_title="RAG Document QA",
    page_icon="📚",
    layout="wide"
)

# API endpoint
API_URL = "http://127.0.0.1:8000"

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 3rem;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 2rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #D4EDDA;
        border: 1px solid #C3E6CB;
        color: #155724;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #D1ECF1;
        border: 1px solid #BEE5EB;
        color: #0C5460;
    }
    .answer-box {
        padding: 1.5rem;
        border-radius: 0.5rem;
        background-color: #F8F9FA;
        border-left: 4px solid #1E88E5;
        margin-top: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

# Header
st.markdown('<h1 class="main-header">📚 RAG Document QA System</h1>', unsafe_allow_html=True)
st.markdown("---")

# Initialize session state
if 'document_uploaded' not in st.session_state:
    st.session_state.document_uploaded = False
if 'document_name' not in st.session_state:
    st.session_state.document_name = ""
if 'document_size_kb' not in st.session_state:
    st.session_state.document_size_kb = 0.0
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'process_requested' not in st.session_state:
    st.session_state.process_requested = False
if 'question_requested' not in st.session_state:
    st.session_state.question_requested = False
if 'process_status' not in st.session_state:
    st.session_state.process_status = None
if 'question_error' not in st.session_state:
    st.session_state.question_error = None


def on_file_change() -> None:
    selected_file = st.session_state.get("uploaded_file_widget")
    if selected_file is None or selected_file.name != st.session_state.document_name:
        st.session_state.document_uploaded = False
        st.session_state.document_name = ""
        st.session_state.document_size_kb = 0.0
        st.session_state.chat_history = []
    st.session_state.process_status = None
    st.session_state.question_error = None


def request_document_processing() -> None:
    st.session_state.process_requested = True


def process_document() -> None:
    uploaded_file = st.session_state.get("uploaded_file_widget")
    if uploaded_file is None:
        st.session_state.process_status = ("error", "Please choose a file before processing.")
        return

    try:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        response = requests.post(f"{API_URL}/upload", files=files, timeout=60)

        if response.status_code == 200:
            st.session_state.document_uploaded = True
            st.session_state.document_name = uploaded_file.name
            st.session_state.document_size_kb = uploaded_file.size / 1024
            st.session_state.chat_history = []
            st.session_state.process_status = ("success", "Document processed successfully!")
            st.session_state.question_error = None
        else:
            st.session_state.document_uploaded = False
            st.session_state.process_status = ("error", f"Error: {response.text}")
    except requests.RequestException as exc:
        st.session_state.document_uploaded = False
        st.session_state.process_status = (
            "error",
            f"Connection error: {exc}. Make sure the FastAPI server is running on {API_URL}",
        )


def request_question_submission() -> None:
    st.session_state.question_requested = True


def submit_question() -> None:
    question = st.session_state.get("question_input", "").strip()
    if not question:
        st.session_state.question_error = "Enter a question before requesting an answer."
        return

    try:
        response = requests.post(f"{API_URL}/ask", json={"question": question}, timeout=60)

        if response.status_code == 200:
            answer = response.json().get("answer", "")
            st.session_state.chat_history.append({
                "question": question,
                "answer": answer,
                "timestamp": time.strftime("%H:%M:%S")
            })
            st.session_state.question_error = None
        else:
            st.session_state.question_error = f"Error: {response.text}"
    except requests.RequestException as exc:
        st.session_state.question_error = f"Connection error: {exc}"


def clear_chat_history() -> None:
    st.session_state.chat_history = []
    st.session_state.question_error = None

# Layout: Two columns
col1, col2 = st.columns([1, 1])

# Left Column - Document Upload
with col1:
    st.header("📤 Upload Document")
    st.write("Upload a PDF, DOCX, or TXT file to get started")
    
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=['pdf', 'docx', 'txt'],
        help="Supported formats: PDF, DOCX, TXT",
        key="uploaded_file_widget",
        on_change=on_file_change,
    )
    
    if uploaded_file is not None:
        st.info(f"**Selected file:** {uploaded_file.name}")
        st.info(f"**File size:** {uploaded_file.size / 1024:.2f} KB")

        st.button(
            "🚀 Process Document",
            type="primary",
            use_container_width=True,
            on_click=request_document_processing,
        )

    if st.session_state.process_requested:
        st.session_state.process_requested = False
        with st.spinner("Processing document... This may take a moment."):
            process_document()

    if st.session_state.process_status:
        status_type, status_message = st.session_state.process_status
        if status_type == "success":
            st.success(f"✅ {status_message}")
            st.balloons()
            st.session_state.process_status = None
        else:
            st.error(f"❌ {status_message}")

    if st.session_state.document_uploaded:
        st.markdown('<div class="success-box">✓ Document is ready for questions!</div>', unsafe_allow_html=True)

# Right Column - Ask Questions
with col2:
    st.header("💬 Ask Questions")
    
    if not st.session_state.document_uploaded:
        st.markdown('<div class="info-box">⚠️ Please upload a document first</div>', unsafe_allow_html=True)
    else:
        with st.form("question_form", clear_on_submit=True):
            st.text_input(
                "Enter your question:",
                placeholder="e.g., What is the main topic of this document?",
                key="question_input"
            )
            st.form_submit_button(
                "🔍 Get Answer",
                type="primary",
                use_container_width=True,
                on_click=request_question_submission,
            )

        _, clear_col = st.columns([3, 1])
        with clear_col:
            st.button("🗑️ Clear", use_container_width=True, on_click=clear_chat_history)

        if st.session_state.question_requested:
            st.session_state.question_requested = False
            with st.spinner("Searching for answer..."):
                submit_question()

        if st.session_state.question_error:
            st.error(f"❌ {st.session_state.question_error}")

# Display Chat History
if st.session_state.chat_history:
    st.markdown("---")
    st.header("📝 Question History")
    
    # Display in reverse order (newest first)
    for idx, chat in enumerate(reversed(st.session_state.chat_history)):
        with st.container():
            st.markdown(f"**Q{len(st.session_state.chat_history) - idx}:** {chat['question']}")
            st.markdown(f'<div class="answer-box"><strong>Answer:</strong><br>{chat["answer"]}</div>', unsafe_allow_html=True)
            st.caption(f"⏰ {chat['timestamp']}")
            st.markdown("")

# Sidebar - Information
with st.sidebar:
    st.header("ℹ️ About")
    st.write("""
    This **RAG (Retrieval-Augmented Generation)** system allows you to:
    
    1. 📤 **Upload** your documents
    2. 🔍 **Ask** questions about them
    3. 🤖 **Get** AI-powered answers
    
    The system uses:
    - **Sentence Transformers** for embeddings
    - **FAISS** for vector search
    - **OpenAI GPT** or **Hugging Face** for answer generation
    """)
    
    st.markdown("---")
    st.header("🛠️ System Status")
    
    # Check API health
    try:
        response = requests.get(f"{API_URL}/docs", timeout=2)
        if response.status_code == 200:
            st.success("✅ API Server: Online")
        else:
            st.error("❌ API Server: Error")
    except:
        st.error("❌ API Server: Offline")
    
    if st.session_state.document_uploaded:
        st.success("✅ Document: Loaded")
    else:
        st.warning("⚠️ Document: Not loaded")

    st.markdown("---")
    st.header("📄 Document")
    if st.session_state.document_uploaded and st.session_state.document_name:
        st.write(f"**Name:** {st.session_state.document_name}")
        st.write(f"**Size:** {st.session_state.document_size_kb:.2f} KB")
    else:
        st.caption("No document loaded")
    
    st.markdown("---")
    st.info("💡 **Tip:** Ask specific questions about the content of your uploaded document for best results!")
