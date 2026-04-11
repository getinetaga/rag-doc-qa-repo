import io

import pytest
from fastapi.testclient import TestClient
"""Tests for the FastAPI endpoints in `app.main`.

This module contains small, deterministic tests that exercise the
two HTTP endpoints provided by the example RAG app:

- POST `/upload`: accepts a file upload, extracts text, chunks it,
  computes embeddings, and builds an in-memory `VectorStore`.
- POST `/ask`: accepts a question and returns an answer based on the
  current in-memory index.

To keep these tests fast and hermetic we use `fastapi.testclient.TestClient`
and `pytest`'s `monkeypatch` fixture to replace expensive or networked
operations (text extraction, embedding, and LLM calls) with small,
predictable fakes.

Run the tests with:

	python -m pytest tests/test_api.py -q

"""

import io
import pytest
from fastapi.testclient import TestClient

from app import main


# TestClient wraps the FastAPI app and lets us call endpoints synchronously
client = TestClient(main.app)


def setup_function():
	"""Reset module-level state before each test.

	The application stores a `vector_store` at module scope when a document
	is uploaded; tests must clear it to avoid cross-test interference.
	"""

	main.vector_store = None


def test_ask_without_upload():
	"""When no document has been uploaded, `/ask` should return an
	informative message rather than attempting retrieval or generation.
	"""

	main.vector_store = None
	resp = client.post("/ask", json={"question": "Hello"})
	assert resp.status_code == 200
	assert resp.json() == {"answer": "No document uploaded yet."}


def test_upload_and_ask(monkeypatch):
	"""Smoke-test the upload -> ask flow using monkeypatched helpers.

	We replace the real `extract_text`, `chunk_text`, `embed_text`,
	`VectorStore` and `generate_answer` with tiny fakes so the test is
	deterministic and fast. The test verifies that `/upload` returns a
	success message and that `/ask` later returns the expected fake
	answer produced by the patched `generate_answer` function.
	"""

	# --- Fake implementations used in this test ---
	def fake_extract_text(path):
		return "This is a small test document."

	def fake_chunk_text(text):
		# Single chunk containing the entire test document
		return [text]

	def fake_embed_text(chunks):
		# Return a small fixed-dimension vector per chunk
		return [[0.0, 0.0, 0.0, 0.0] for _ in chunks]

	class FakeVectorStore:
		def __init__(self, dim):
			self.texts = []
			self.clear_called = False

		def clear(self):
			self.clear_called = True
			self.texts = []

		def add(self, embeddings, texts):
			self.texts.extend(texts)

		def search(self, query_embedding, top_k=5):
			return self.texts[:top_k]

	def fake_generate_answer(question, vector_store):
		return f"FAKE ANSWER: {question}"

	# Patch functions and classes used by the endpoint handlers
	monkeypatch.setattr(main, "extract_text", fake_extract_text)
	monkeypatch.setattr(main, "chunk_text", fake_chunk_text)
	monkeypatch.setattr(main, "embed_text", fake_embed_text)
	monkeypatch.setattr(main, "VectorStore", FakeVectorStore)
	monkeypatch.setattr(main, "generate_answer", fake_generate_answer)

	# Upload a dummy file (actual content ignored by fakes)
	files = {"file": ("doc.txt", b"ignored", "text/plain")}
	r = client.post("/upload", files=files)
	assert r.status_code == 200
	assert r.json().get("message") == "Document processed successfully"
	assert main.vector_store.clear_called is True

	# Ask a question and verify the fake generator is invoked
	r2 = client.post("/ask", json={"question": "What is this?"})
	assert r2.status_code == 200
	assert r2.json().get("answer") == "FAKE ANSWER: What is this?"