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
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# Layout: Two columns
col1, col2 = st.columns([1, 1])

# Left Column - Document Upload
with col1:
    st.header("📤 Upload Document")
    st.write("Upload a PDF, DOCX, or TXT file to get started")
    
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=['pdf', 'docx', 'txt'],
        help="Supported formats: PDF, DOCX, TXT"
    )
    
    if uploaded_file is not None:
        st.info(f"**Selected file:** {uploaded_file.name}")
        st.info(f"**File size:** {uploaded_file.size / 1024:.2f} KB")
        
        if st.button("🚀 Process Document", type="primary", use_container_width=True):
            with st.spinner("Processing document... This may take a moment."):
                try:
                    # Send file to API
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    response = requests.post(f"{API_URL}/upload", files=files)
                    
                    if response.status_code == 200:
                        st.session_state.document_uploaded = True
                        st.session_state.chat_history = []
                        st.success("✅ Document processed successfully!")
                        st.balloons()
                    else:
                        st.error(f"❌ Error: {response.text}")
                        
                except Exception as e:
                    st.error(f"❌ Connection error: {str(e)}")
                    st.info("Make sure the FastAPI server is running on http://127.0.0.1:8000")

    if st.session_state.document_uploaded:
        st.markdown('<div class="success-box">✓ Document is ready for questions!</div>', unsafe_allow_html=True)

# Right Column - Ask Questions
with col2:
    st.header("💬 Ask Questions")
    
    if not st.session_state.document_uploaded:
        st.markdown('<div class="info-box">⚠️ Please upload a document first</div>', unsafe_allow_html=True)
    else:
        question = st.text_input(
            "Enter your question:",
            placeholder="e.g., What is the main topic of this document?",
            key="question_input"
        )
        
        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn1:
            ask_button = st.button("🔍 Get Answer", type="primary", use_container_width=True)
        with col_btn2:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state.chat_history = []
                st.rerun()
        
        if ask_button and question:
            with st.spinner("Searching for answer..."):
                try:
                    payload = {"question": question}
                    response = requests.post(f"{API_URL}/ask", json=payload)
                    
                    if response.status_code == 200:
                        answer = response.json()["answer"]
                        
                        # Add to chat history
                        st.session_state.chat_history.append({
                            "question": question,
                            "answer": answer,
                            "timestamp": time.strftime("%H:%M:%S")
                        })
                        
                    else:
                        st.error(f"❌ Error: {response.text}")
                        
                except Exception as e:
                    st.error(f"❌ Connection error: {str(e)}")

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
    st.info("💡 **Tip:** Ask specific questions about the content of your uploaded document for best results!")
