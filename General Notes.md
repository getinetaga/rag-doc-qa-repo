# General Notes — RAG Document QA System

## 1. Purpose
This document serves as a **general reference guide** for the application. It explains:

- how to use the main files,
- what each folder is for,
- the technology stack used,
- common acronyms used in the project,
- and how all the pieces work together.

It is intended for developers, testers, reviewers, and project stakeholders.

---

## 2. Application Summary
This application is an **AI-powered Retrieval-Augmented Generation (RAG) Document Question Answering System**.

It allows a user to:
1. upload a document (`PDF`, `DOCX`, or `TXT`),
2. process and split the document into chunks,
3. create embeddings from the text,
4. store/retrieve those chunks using vector search,
5. ask questions in natural language,
6. receive a clear answer with **section references**.

---

## 3. Main Project Structure

```text
app/                 -> core application logic
scripts/             -> helper SQL and script files
docs/                -> project and architecture documentation
tests/               -> automated test suite
streamlit_app.py     -> main Streamlit user interface
README.md            -> quick start and project overview
requirements.txt     -> Python dependencies
Dockerfile           -> container definition
Jenkinsfile          -> CI/CD pipeline definition
```

---

## 4. How to Use the Main Files

## 4.1 `README.md`
**Purpose:**
- main starting point for the project
- explains what the app does
- provides setup and run instructions

**Use it when:**
- you are new to the project,
- you want to install dependencies,
- you want to run the app quickly.

---

## 4.2 `streamlit_app.py`
**Purpose:**
- provides the web user interface
- allows users to upload documents and ask questions

**Use it when:**
- you want to interact with the app visually in the browser

**Run with:**
```bash
streamlit run streamlit_app.py
```

---

## 4.3 `app/main.py`
**Purpose:**
- FastAPI backend entry point
- exposes the API endpoints:
  - `/upload`
  - `/ask`

**Use it when:**
- you want to run the backend API,
- you want to integrate the app with other tools or services.

**Run with:**
```bash
uvicorn app.main:app --reload
```

---

## 4.4 `app/ingestion.py`
**Purpose:**
- reads and extracts text from uploaded files
- supports `TXT`, `PDF`, and `DOCX`

**Use it when:**
- you need to understand how the document text enters the system.

---

## 4.5 `app/chunking.py`
**Purpose:**
- splits the document into smaller overlapping pieces called **chunks**
- adds section labels for better referencing

**Use it when:**
- you want to improve retrieval quality,
- you want answers to cite document sections clearly.

---

## 4.6 `app/embeddings.py`
**Purpose:**
- converts text chunks and user questions into embedding vectors
- uses the `SentenceTransformers` model

**Use it when:**
- you need semantic search capability.

---

## 4.7 `app/vector_store.py`
**Purpose:**
- stores and retrieves embeddings using:
  - `FAISS`
  - `pgvector`
  - `hybrid`

**Use it when:**
- you want to manage vector search behavior,
- you need persistent storage through PostgreSQL.

---

## 4.8 `app/rag.py`
**Purpose:**
- handles the RAG logic
- retrieves context
- builds prompts
- calls OpenAI or Hugging Face
- formats the answer and references

**Use it when:**
- you want to understand how the final answer is generated.

---

## 4.9 `app/config.py`
**Purpose:**
- reads environment variables from `.env`
- stores app configuration values

**Use it when:**
- you need to change model/provider/db settings.

---

## 4.10 `tests/`
**Purpose:**
- contains automated tests for API, ingestion, vector store, and RAG behavior

**Use it when:**
- you want to verify that the app is working correctly,
- you want to confirm that no recent changes broke existing features.

**Run with:**
```bash
python -m pytest -q
```

---

## 4.11 `scripts/create_pgvector_table.sql`
**Purpose:**
- creates the `pgvector` extension
- creates the `rag_embeddings` table and indexes in PostgreSQL

**Use it when:**
- setting up PostgreSQL for persistent vector storage.

---

## 4.12 `Dockerfile`
**Purpose:**
- packages the app in a Docker container

**Use it when:**
- you want to run the app in a containerized environment,
- you want consistent deployment behavior.

---

## 4.13 `Jenkinsfile`
**Purpose:**
- defines the CI pipeline
- installs dependencies, runs tests, and optionally builds a Docker image

**Use it when:**
- automating build and test workflows.

---

## 5. Technology Stack Used in This App

| Stack / Tool | Role in the Application |
|---|---|
| **Python** | main development language |
| **FastAPI** | backend API framework |
| **Uvicorn** | FastAPI server |
| **Streamlit** | browser-based UI |
| **SentenceTransformers** | embedding generation |
| **FAISS** | in-memory vector search |
| **PostgreSQL** | persistent database |
| **pgvector** | vector extension for PostgreSQL |
| **psycopg** | PostgreSQL database connector |
| **OpenAI API** | answer generation provider |
| **Hugging Face API** | alternative answer generation provider |
| **pytest** | automated testing |
| **Docker** | containerization |
| **Jenkins** | CI/CD automation |
| **Git/GitHub** | version control |

---

## 6. Acronyms Used in This Project

| Acronym | Meaning | Explanation |
|---|---|---|
| **AI** | Artificial Intelligence | used for intelligent question answering |
| **RAG** | Retrieval-Augmented Generation | combines retrieval with LLM answer generation |
| **LLM** | Large Language Model | model used to generate natural-language answers |
| **API** | Application Programming Interface | endpoints used for upload and ask requests |
| **UI** | User Interface | the Streamlit front end |
| **DB** | Database | where persistent data is stored |
| **CI** | Continuous Integration | automated test/build validation |
| **CD** | Continuous Deployment/Delivery | automated or semi-automated release flow |
| **SQL** | Structured Query Language | used to manage PostgreSQL tables |
| **ASGI** | Asynchronous Server Gateway Interface | interface used by FastAPI/Uvicorn |
| **PDF** | Portable Document Format | supported upload file type |
| **DOCX** | Microsoft Word document format | supported upload file type |
| **TXT** | Plain text file | supported upload file type |
| **DSN** | Data Source Name | PostgreSQL connection string |
| **QA** | Quality Assurance | software testing and validation process |
| **OV** | Overlap Value | chunk overlap used in text splitting conceptually |

---

## 7. Typical Usage Flow

### Step 1 — Configure the environment
Set values in `.env`:
```env
LLM_PROVIDER=openai
VECTOR_DB_BACKEND=pgvector
PGVECTOR_DSN=postgresql://postgres:<password>@localhost:5432/ragdb
```

### Step 2 — Start the backend
```bash
uvicorn app.main:app --reload
```

### Step 3 — Start the UI
```bash
streamlit run streamlit_app.py
```

### Step 4 — Open the browser
Visit:
- `http://127.0.0.1:8501` for the UI
- `http://127.0.0.1:8000/docs` for the API docs

### Step 5 — Upload a document
Use the upload panel in the Streamlit app.

### Step 6 — Ask a question
Enter a question about the uploaded document.

### Step 7 — Review the answer
The answer should be clear and include a `References:` line showing the source section.

---

## 8. Important Supporting Documents
This repository now includes several supporting documentation files:

| File | Purpose |
|---|---|
| `Test Plan.md` | detailed testing approach |
| `DevOps.md` | deployment and operational strategy |
| `AI_Integration.md` | AI implementation details |
| `Software_Quality_Management.md` | quality management and implementation |
| `Docker_Jenkins_Implementation.md` | Docker and Jenkins implementation guide |

---

## 9. How to Convert `.md` Files into Word Documents
You can convert project Markdown files such as `README.md`, `Test Plan.md`, or `DevOps.md` into Microsoft Word documents in several easy ways.

### Option 1 — Open in VS Code and copy into Microsoft Word
**Steps:**
1. Open the `.md` file in VS Code.
2. Right-click inside the file and choose **Open Preview** or press `Ctrl + Shift + V`.
3. Select the formatted content from the preview page.
4. Copy it.
5. Open Microsoft Word.
6. Paste the content into a blank Word document.
7. Adjust any spacing or table formatting if needed.
8. Save the file as `.docx`.

### Option 2 — Use Pandoc (recommended for professional output)
This is the best option when you want cleaner headings, tables, and structure.

**Steps to install Pandoc on Windows:**
1. Go to the official Pandoc website: `https://pandoc.org/installing.html`
2. Download the Windows installer.
3. Run the installer.
4. Reopen your terminal after installation.

**Steps to convert a file:**
1. Open PowerShell in the project folder.
2. Run one of the commands below:

```bash
pandoc "General Notes.md" -o "General Notes.docx"
pandoc "Test Plan.md" -o "Test Plan.docx"
pandoc "DevOps.md" -o "DevOps.docx"
```

**Steps to convert multiple documentation files:**
```bash
pandoc "AI_Integration.md" -o "AI_Integration.docx"
pandoc "Software_Quality_Management.md" -o "Software_Quality_Management.docx"
pandoc "Docker_Jenkins_Implementation.md" -o "Docker_Jenkins_Implementation.docx"
```

### Option 3 — Use Microsoft Word directly
**Steps:**
1. Open Microsoft Word.
2. Go to **File** → **Open**.
3. Browse to the `.md` file location.
4. Open the Markdown file directly if Word supports it on your system.
5. Review the formatting.
6. Save it as a `.docx` Word document.

### Option 4 — Use online Markdown-to-Word tools
You can paste the Markdown content into a trusted converter and download a `.docx` file.

> For project or company files, prefer **Pandoc** or **Microsoft Word copy/paste** instead of public online tools.

---

## 10. Common Troubleshooting Notes

### If the app does not answer correctly
- verify the uploaded file is processed,
- confirm the document contains the answer,
- check if the LLM provider key is valid.

### If PostgreSQL data is not visible
- verify you are connected to the correct host and port,
- confirm the app uses `localhost:5432`,
- refresh the database tree in pgAdmin.

### If answers are repeated
- re-upload the document,
- confirm the app is using the updated code that clears stale rows and deduplicates results.

### If the app shows provider unavailable
- check `OPENAI_API_KEY` or `HUGGINGFACE_API_KEY`,
- confirm the key is valid and active.

---

## 10. Summary
This project combines:
- AI-based document question answering,
- a FastAPI backend,
- a Streamlit user interface,
- PostgreSQL + pgvector or FAISS for retrieval,
- and CI/CD/quality documentation for maintainability.

This `General Notes.md` file is meant to help anyone quickly understand **what the files do, how to use them, what technologies are involved, and what the key acronyms mean**.
