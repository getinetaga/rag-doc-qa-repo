"""Tests for the RAG pipeline helpers in `app.rag`.

These tests monkeypatch external dependencies (embeddings and LLM
providers) to validate that `generate_answer` correctly retrieves context
from a vector store and forwards prompts to the configured backend.
"""

import types

import pytest

from app import config, rag


@pytest.fixture(autouse=True)
def clear_rag_caches():
    rag._clear_caches()


class DummyVS:
    def __init__(self, texts):
        self._texts = texts
        self.revision = 1

    def search(self, query_embedding, top_k=5, source_document=None, filters=None):
        # Return the stored texts up to top_k
        return self._texts[:top_k]


@pytest.mark.parametrize("field", [
    "tenant_id", "collection_id", "document_id", "document_date", "author", "tag", "source_system",
])
def test_retrieval_cache_separates_every_filter(field):
    calls = []

    class FilterStore:
        revision = 1

        def search(self, vector, limit, *, source_document=None, filters=None):
            calls.append(dict(filters))
            return [filters.get(field, "missing")]

    values = {
        "tenant_id": "a", "collection_id": "p", "document_id": "doc",
        "document_date": "2026-01-01", "author": "author", "tag": "alpha", "source_system": "source",
    }
    store = FilterStore()
    first = rag._retrieve_context_chunks("Q", [0.1], store, **values)
    second = rag._retrieve_context_chunks("Q", [0.1], store, **{**values, field: "different"})
    assert first != second
    assert len(calls) == 2


def test_response_cache_isolates_stores_with_equal_revisions(monkeypatch):
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.1]])
    monkeypatch.setattr(rag, "_generate_from_prompt", lambda prompt: "Python supports APIs." if "Python supports APIs." in prompt else "Python builds applications.")
    first = DummyVS(["[A] Python supports APIs."])
    second = DummyVS(["[B] Python builds applications."])
    a = rag.generate_answer("What does Python do?", first)
    b = rag.generate_answer("What does Python do?", second)
    assert "supports" in a
    assert "builds" in b


def test_scoped_search_never_retries_typeerror_without_filters():
    class BrokenStore:
        revision = 1
        calls = 0

        def search(self, *args, **kwargs):
            self.calls += 1
            raise TypeError("Backend implementation failed")

    store = BrokenStore()
    with pytest.raises(TypeError):
        rag._retrieve_context_chunks("Q", [0.1], store, "a", "p", "doc")
    assert store.calls == 1


def test_persistent_store_caches_are_disabled_until_shared_generations(monkeypatch):
    class PersistentStore(DummyVS):
        backend = "pgvector"
        calls = 0

        def search(self, *args, **kwargs):
            self.calls += 1
            return self._texts

    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.1]])
    monkeypatch.setattr(rag, "_generate_from_prompt", lambda prompt: "Python supports APIs.")
    store = PersistentStore(["[A] Python supports APIs."])
    for _ in range(2):
        rag.generate_answer("What does Python do?", store)
    assert store.calls == 2
    assert not rag._RETRIEVAL_CACHE
    assert not rag._RESPONSE_CACHE


def test_vector_signature_does_not_round_distinct_vectors():
    assert rag._vector_signature([0.123401]) != rag._vector_signature([0.123402])


def test_remote_retrieval_response_is_validated(monkeypatch):
    monkeypatch.setattr(config, "RETRIEVAL_SERVICE_URL", "http://internal.invalid")
    monkeypatch.setattr(rag, "_post_json", lambda *args, **kwargs: {})
    with pytest.raises(RuntimeError, match="invalid context"):
        rag._retrieve_context_chunks("Q", [0.1], DummyVS([]), "a", "p", "doc")


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
        return "Context chunk A"

    monkeypatch.setattr(rag, "_call_huggingface", fake_hf)

    out = rag.generate_answer("Tell me about A", vs)
    assert out == "Context chunk A"


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
                return types.SimpleNamespace(output_text="Some helpful context.")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    out = rag.generate_answer("Question?", vs)
    assert out == "Some helpful context."


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


def test_generate_answer_returns_requested_message_for_irrelevant_context(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.2, 0.3, 0.4]])
    vs = DummyVS(["[Section 1: Cooking] This document describes baking bread."])

    called = {"openai": False}

    def fake_client():
        called["openai"] = True
        raise AssertionError("Provider should not be called when context is irrelevant")

    monkeypatch.setattr(rag, "_get_openai_client", fake_client)

    out = rag.generate_answer("What does the document say about Kubernetes clusters?", vs)

    assert out == rag.NO_RELEVANT_INFO_RESPONSE
    assert called["openai"] is False


def test_generate_answer_keeps_external_response_label_without_references(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.7, 0.8, 0.9]])
    vs = DummyVS(["[Section 1: Introduction] Python is the main topic."])

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(
                    output_text="External response: Python was created by Guido van Rossum in 1991."
                )

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    out = rag.generate_answer("What is the document about?", vs)

    assert out.startswith("External response:")
    assert "References:" not in out


def test_generate_answer_blocks_ungrounded_model_output(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.7, 0.8, 0.9]])
    vs = DummyVS(["[Section 1: Introduction] Python is the main topic."])

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(output_text="Python was created by Guido van Rossum in 1991.")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    out = rag.generate_answer("What is the document about?", vs)

    assert out == rag.NO_RELEVANT_INFO_RESPONSE


def test_generate_answer_rejects_partial_term_overlap(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.6, 0.2, 0.1]])
    vs = DummyVS(["[Section 2: Benefits] Python benefits include API development and data analysis."])

    called = {"openai": False}

    def fake_client():
        called["openai"] = True
        raise AssertionError("Provider should not be called when only partial term overlap exists")

    monkeypatch.setattr(rag, "_get_openai_client", fake_client)

    out = rag.generate_answer("What are the benefits of Kubernetes?", vs)

    assert out == rag.NO_RELEVANT_INFO_RESPONSE
    assert called["openai"] is False


def test_generate_answer_accepts_short_question_with_high_signal_overlap(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.2, 0.2, 0.2]])
    vs = DummyVS([
        "[Section 1: Stack] Python was used to build FastAPI endpoints, data ingestion, and embedding services.",
    ])

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(
                    output_text="Python was used to build FastAPI endpoints, data ingestion, and embedding services."
                )

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    out = rag.generate_answer("What was the application of Python in this document?", vs)

    assert "Python was used to build FastAPI endpoints" in out
    assert out != rag.NO_RELEVANT_INFO_RESPONSE


def test_rerank_context_chunks_promotes_more_relevant_chunk():
    chunks = [
        "[Section 1: Overview] This part discusses deployment and packaging.",
        "[Section 2: Retrieval] Retrieval reranking improves relevance quality for question answering.",
        "[Section 3: Appendix] Miscellaneous notes.",
    ]

    ranked = rag._rerank_context_chunks("How does retrieval reranking improve relevance?", chunks)

    assert ranked[0].startswith("[Section 2: Retrieval]")
    assert ranked[-1].startswith("[Section 3: Appendix]")


def test_generate_answer_uses_response_cache_for_repeated_question(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")

    calls = {"embed": 0, "search": 0, "provider": 0}

    def fake_embed(texts):
        calls["embed"] += 1
        return [[0.1, 0.2, 0.3]]

    class CountingVS:
        revision = 1

        def search(self, query_embedding, top_k=5, source_document=None, filters=None):
            calls["search"] += 1
            return ["[Section 1: Introduction] Python is the main topic."]

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                calls["provider"] += 1
                return types.SimpleNamespace(output_text="Python is the main topic.")

    monkeypatch.setattr(rag, "embed_text", fake_embed)
    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    vs = CountingVS()
    first = rag.generate_answer("What is the document about?", vs)
    second = rag.generate_answer("What is the document about?", vs)

    assert first == second
    assert calls["embed"] == 1
    assert calls["search"] == 1
    assert calls["provider"] == 1


def test_generate_answer_reuses_retrieval_cache_for_equivalent_embeddings(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")

    calls = {"embed": 0, "search": 0, "provider": 0}

    def fake_embed(texts):
        calls["embed"] += 1
        return [[0.4, 0.5, 0.6]]

    class CountingVS:
        revision = 1

        def search(self, query_embedding, top_k=5, source_document=None, filters=None):
            calls["search"] += 1
            return ["[Section 1: Introduction] Python is the main topic."]

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                calls["provider"] += 1
                return types.SimpleNamespace(output_text="Python is the main topic.")

    monkeypatch.setattr(rag, "embed_text", fake_embed)
    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    vs = CountingVS()
    first = rag.generate_answer("What is the document about?", vs)
    second = rag.generate_answer("Tell me about the document.", vs)

    assert first == second
    assert calls["embed"] == 2
    assert calls["search"] == 1
    assert calls["provider"] == 2


def test_generate_answer_uses_collection_scope_across_multiple_documents(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.2, 0.3, 0.4]])

    class KnowledgeSpaceVS:
        revision = 1

        def search(self, query_embedding, top_k=5, source_document=None, filters=None):
            assert filters is not None
            assert filters.get("collection_id") == "project-alpha"
            return [
                "[Doc A: Planning] Project Alpha defines the roadmap and milestones.",
                "[Doc B: Delivery] Project Alpha also includes the deployment checklist.",
            ]

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(output_text="Project Alpha defines the roadmap and milestones.")

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    vs = KnowledgeSpaceVS()
    out = rag.generate_answer(
        "What does Project Alpha include?",
        vs,
        tenant_id="default",
        collection_id="project-alpha",
    )

    assert "Project Alpha defines the roadmap and milestones." in out
    assert "References:" in out
    assert "Doc A: Planning" in out
    assert "Doc B: Delivery" in out


def test_generate_answer_applies_advanced_metadata_filters(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0.2, 0.3, 0.4]])

    captured = {}

    class FilteredVS:
        revision = 1

        def search(self, query_embedding, top_k=5, source_document=None, filters=None):
            captured["source_document"] = source_document
            captured["filters"] = dict(filters or {})
            return [
                "[Doc: Metadata] Source system and tags are included in retrieval metadata.",
            ]

    class FakeClient:
        class responses:
            @staticmethod
            def create(model, input, temperature=0):
                return types.SimpleNamespace(
                    output_text="Source system and tags are included in retrieval metadata."
                )

    monkeypatch.setattr(rag, "_get_openai_client", lambda: FakeClient())

    vs = FilteredVS()
    out = rag.generate_answer(
        "What metadata filters are active?",
        vs,
        tenant_id="tenant-a",
        collection_id="project-alpha",
        document_id="doc-01",
        document_date="2026-07-01",
        author="Getinet Aga",
        tag="release-notes",
        source_system="confluence",
    )

    assert "retrieval metadata" in out.lower()
    assert captured["source_document"] == "doc-01"
    assert captured["filters"]["tenant_id"] == "tenant-a"
    assert captured["filters"]["collection_id"] == "project-alpha"
    assert captured["filters"]["document_id"] == "doc-01"
    assert captured["filters"]["document_date"] == "2026-07-01"
    assert captured["filters"]["author"] == "Getinet Aga"
    assert captured["filters"]["tag"] == "release-notes"
    assert captured["filters"]["source_system"] == "confluence"
