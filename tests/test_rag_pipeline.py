"""Tests for the RAG pipeline helpers in `app.rag`.

These tests monkeypatch external dependencies (embeddings and LLM
providers) to validate that `generate_answer` correctly retrieves context
from a vector store and forwards prompts to the configured backend.
"""

import types

import pytest

from app import config, rag


class DummyVS:
    def __init__(self, texts):
        self._texts = texts

    def search(self, query_embedding, top_k=5):
        # Return the stored texts up to top_k
        return self._texts[:top_k]


def test_generate_answer_huggingface(monkeypatch):
    # Patch to use huggingface provider
    monkeypatch.setattr(config, "LLM_PROVIDER", "huggingface")

    # Fake embed to return a deterministic vector
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.1, 0.2, 0.3]])

    # Fake vector store returns a known context chunk
    vs = DummyVS(["Context chunk A", "Context chunk B"])

    # Patch _call_huggingface to assert prompt contains the context
    def fake_hf(model, prompt):
        assert "Context chunk A" in prompt
        return "HF_REPLY"

    monkeypatch.setattr(rag, "_call_huggingface", fake_hf)

    out = rag.generate_answer("Tell me about A", vs)
    assert out == "HF_REPLY"


def test_generate_answer_openai(monkeypatch):
    # Ensure provider is openai for this test
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")

    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.4, 0.5, 0.6]])
    vs = DummyVS(["Some helpful context."])

    # Create a fake client with a responses.create that returns an object
    # having `output_text` populated (preferred path in generate_answer)
    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(output_text="OPENAI_REPLY")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    out = rag.generate_answer("Question?", vs)
    assert out == "OPENAI_REPLY"


def test_generate_answer_handles_provider_errors(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.4, 0.5, 0.6]])
    vs = DummyVS(["Some helpful context."])

    class FailingClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                raise rag.OpenAIError("quota exceeded")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FailingClient())

    out = rag.generate_answer("Question?", vs)
    assert "Some helpful context." in out
    assert "temporarily unavailable" not in out.lower()


def test_generate_answer_appends_section_references(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.7, 0.8, 0.9]])
    vs = DummyVS([
        "[Section 1: Introduction] Python is the main topic.",
        "[Section 2: Summary] The document wraps up the overview.",
    ])

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(output_text="Python is the main topic.")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    out = rag.generate_answer("What is the document about?", vs)
    assert "Python is the main topic." in out
    assert "References:" in out
    assert "Section 1: Introduction" in out
    assert "Section 2: Summary" in out


def test_generate_answer_fallback_is_clear_and_deduplicated(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.9, 0.1, 0.2]])
    vs = DummyVS([
        "[Section 1: Introduction] Python is the main topic.",
        "[Section 1: Introduction] Python is the main topic.",
        "[Section 2: Benefits] Python is used for APIs and data analysis.",
    ])

    class FailingClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                raise rag.OpenAIError("quota exceeded")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FailingClient())

    out = rag.generate_answer("What is the document about?", vs)
    assert "Python is the main topic." in out
    assert out.count("Python is the main topic.") == 1
    assert "temporarily unavailable" not in out.lower()
    assert "References:" in out
    assert "Section 1: Introduction" in out
