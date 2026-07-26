"""Retrieval-augmented generation helpers.

This module wires retrieval (vector search) with text generation. It
provides two provider backends: Hugging Face Inference API and OpenAI's
Responses API (v1 SDK). The primary public function is `generate_answer`
which accepts a user question and a `vector_store` instance and returns a
generated answer string.

Behavior:
- The function retrieves the top-K context chunks from the provided
    `vector_store`, constructs a prompt that instructs the LLM to answer
    using only the provided context, and then calls the configured LLM
    provider to generate a response.
- If the external LLM provider is unavailable (for example missing API
    credentials, rate limiting, or service/network errors), a friendly
    fallback answer is returned instead of crashing the API endpoint.
- Returned answers include a short `References:` line so the UI can show
    which section(s) of the document support the answer.

Notes:
- OpenAI client initialization is lazy to avoid import-time failures when
    `OPENAI_API_KEY` is not yet available. A clear error is raised when the
    client is first used and the API key is missing.
"""

import logging
# Logging is used to provide informative messages about the flow of the retrieval and generation process, 
#including which provider is being used, how many context chunks are retrieved, and any errors that occur during LLM calls. 
# This helps with debugging and monitoring the application's behavior in production.
from collections import OrderedDict
import hashlib
import re # The re module is used for regular expression operations, such as extracting meaningful terms from questions and answers, and for text preprocessing tasks.
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests # The requests library is used to make HTTP requests to the Hugging Face Inference API when the Hugging Face provider is configured.
from openai import OpenAI, OpenAIError # The OpenAI library is used to interact with OpenAI's Responses API when the OpenAI provider is configured.

from . import config
from .embeddings import embed_text
from . import slo_metrics

logger = logging.getLogger(__name__)

_openai_client = None
_CACHE_LOCK = threading.RLock()
_RESPONSE_CACHE: OrderedDict[tuple, tuple[float, str]] = OrderedDict()
_RETRIEVAL_CACHE: OrderedDict[tuple, tuple[float, list[str]]] = OrderedDict()
_CACHE_TTL_SECONDS = 1800
_RESPONSE_CACHE_MAX_SIZE = 256
_RETRIEVAL_CACHE_MAX_SIZE = 512
NO_RELEVANT_INFO_RESPONSE = (
    "I couldn\u2019t find relevant information in the provided documents to answer your question."
)
# The following constants and sets are used for text preprocessing and filtering.
# EXTERNAL_RESPONSE_PREFIX is a prefix added to external responses.
# _QUESTION_STOP_WORDS is a set of common stop words to ignore in questions.
# _ANSWER_STOP_WORDS is a set of common stop words to ignore in answers.
EXTERNAL_RESPONSE_PREFIX = "External response:"
_QUESTION_STOP_WORDS = {
    "what", "which", "where", "when", "with", "why", "from", "that", "this",
    "about", "document", "your", "into", "than", "then", "them",
    "tell", "question", "questions", "describe", "explain", "summarize",
    "summary", "mention", "mentioned", "discuss", "discusses", "say", "does",
}
_ANSWER_STOP_WORDS = _QUESTION_STOP_WORDS | {
    "answer", "based", "provided", "documents", "relevant", "information",
    "couldn", "find", "external", "response",
}

_GENERIC_QUERY_TERMS = {
    "benefits",
    "project",
    "document",
    "documents",
    "application",
    "system",
    "details",
    "overview",
    "information",
    "include",
    "includes",
}


QUESTION_DOMAIN_CATALOG = [
    {
        "id": "fact_based",
        "name": "Fact-Based Questions",
        "description": "Direct fact lookup where the answer is explicitly in the source.",
        "retrieval_quality_focus": "exact entity/value match",
        "sample_questions": ["What is OAuth 2.0?", "Who approved the design?"],
    },
    {
        "id": "definition",
        "name": "Definition Questions",
        "description": "Explain terminology and concepts from retrieved context.",
        "retrieval_quality_focus": "term-definition grounding",
        "sample_questions": ["What is RAG?", "Explain RBAC."],
    },
    {
        "id": "procedure",
        "name": "Procedure Questions",
        "description": "How-to and step-by-step instruction queries.",
        "retrieval_quality_focus": "ordered step completeness",
        "sample_questions": ["How do I deploy the application?"],
    },
    {
        "id": "comparison",
        "name": "Comparison Questions",
        "description": "Compare two or more options, tools, or approaches.",
        "retrieval_quality_focus": "balanced multi-entity evidence",
        "sample_questions": ["FAISS vs pgvector"],
    },
    {
        "id": "summarization",
        "name": "Summarization Questions",
        "description": "Summarize a full document, section, or report.",
        "retrieval_quality_focus": "coverage of key points",
        "sample_questions": ["Summarize the project plan."],
    },
    {
        "id": "list_extraction",
        "name": "List Extraction Questions",
        "description": "Extract enumerations such as risks, milestones, and APIs.",
        "retrieval_quality_focus": "list completeness and dedupe",
        "sample_questions": ["List all project risks."],
    },
    {
        "id": "search_navigation",
        "name": "Search and Navigation Questions",
        "description": "Locate where information appears in source material.",
        "retrieval_quality_focus": "location precision",
        "sample_questions": ["Where is warranty information?"],
    },
    {
        "id": "citation",
        "name": "Citation Questions",
        "description": "Request source references, chunks, pages, and provenance.",
        "retrieval_quality_focus": "source attribution fidelity",
        "sample_questions": ["Which page contains this information?"],
    },
    {
        "id": "analytical",
        "name": "Analytical Questions",
        "description": "Reasoning-heavy questions using retrieved evidence.",
        "retrieval_quality_focus": "multi-chunk synthesis quality",
        "sample_questions": ["Why is hybrid search better?"],
    },
    {
        "id": "decision_support",
        "name": "Decision Support Questions",
        "description": "Help choose between alternatives based on evidence.",
        "retrieval_quality_focus": "trade-off clarity",
        "sample_questions": ["Should I use Pinecone or pgvector?"],
    },
    {
        "id": "multi_document",
        "name": "Multi-Document Questions",
        "description": "Combine and compare evidence across multiple documents.",
        "retrieval_quality_focus": "cross-document coverage",
        "sample_questions": ["What changed between v1 and v2?"],
    },
    {
        "id": "compliance",
        "name": "Compliance Questions",
        "description": "Check policy, requirement, or standard conformance.",
        "retrieval_quality_focus": "requirement traceability",
        "sample_questions": ["Does the system support RBAC?"],
    },
    {
        "id": "numerical",
        "name": "Numerical Questions",
        "description": "Retrieve numeric values and quantitative constraints.",
        "retrieval_quality_focus": "number extraction accuracy",
        "sample_questions": ["What is the API rate limit?"],
    },
    {
        "id": "metadata",
        "name": "Metadata Questions",
        "description": "Ask about author, date, owner, and version metadata.",
        "retrieval_quality_focus": "metadata field precision",
        "sample_questions": ["Who authored this document?"],
    },
    {
        "id": "troubleshooting",
        "name": "Troubleshooting Questions",
        "description": "Diagnose failures and explain probable causes.",
        "retrieval_quality_focus": "root-cause evidence",
        "sample_questions": ["Why is vector search returning no results?"],
    },
    {
        "id": "security",
        "name": "Security Questions",
        "description": "Authentication, authorization, and protection controls.",
        "retrieval_quality_focus": "control mapping completeness",
        "sample_questions": ["How is data encrypted?"],
    },
    {
        "id": "code_related",
        "name": "Code-Related Questions",
        "description": "Locate or explain implementation details and code snippets.",
        "retrieval_quality_focus": "snippet relevance",
        "sample_questions": ["Show the upload endpoint implementation."],
    },
    {
        "id": "recommendation",
        "name": "Recommendation Questions",
        "description": "Ask for best-practice recommendation based on context.",
        "retrieval_quality_focus": "justified recommendation quality",
        "sample_questions": ["Which vector database is recommended?"],
    },
    {
        "id": "conversational_followup",
        "name": "Conversational Follow-up Questions",
        "description": "Follow-up requests that depend on prior turns.",
        "retrieval_quality_focus": "context carry-over",
        "sample_questions": ["Tell me more about that."],
    },
]


def get_question_domain_catalog() -> list[dict]:
    """Return the supported question-domain taxonomy for QA evaluation."""

    return [dict(item) for item in QUESTION_DOMAIN_CATALOG]


def classify_question_domain(question: str) -> str:
    """Classify a user question into one of the supported question domains."""

    q = " ".join(str(question or "").lower().split())
    if not q:
        return "fact_based"

    if q.startswith(("tell me more", "explain the previous", "compare it", "what about that", "give an example")):
        return "conversational_followup"

    if any(token in q for token in ("show the source", "which page", "chunk", "citation", "confidence score", "source document")):
        return "citation"

    if any(token in q for token in ("where is", "which page", "find references", "open the appendix", "chapter ", "go to page")):
        return "search_navigation"

    if any(token in q for token in ("list ", "all the", "supported file types", "stakeholders", "milestones", "risks")):
        return "list_extraction"

    if any(token in q for token in ("summarize", "summary", "key points", "executive summary")):
        return "summarization"

    if any(token in q for token in ("vs ", "versus", "compare", "difference between")):
        return "comparison"

    if any(token in q for token in ("how do i", "how to", "steps", "configure", "deploy", "setup", "set up")):
        return "procedure"

    if any(token in q for token in ("recommend", "should i", "best option", "which should", "suitable for")):
        return "recommendation"

    if any(token in q for token in ("compliant", "compliance", "required", "zero trust", "policy")):
        return "compliance"

    if any(token in q for token in ("budget", "how many", "rate limit", "storage", "maximum", "minimum", "number of")):
        return "numerical"

    if any(token in q for token in ("authored", "last updated", "department", "version", "metadata")):
        return "metadata"

    if any(token in q for token in ("why is", "failing", "no results", "hallucinating", "slow", "error")):
        return "troubleshooting"

    if any(token in q for token in ("authentication", "authorization", "permissions", "encrypted", "security", "rbac", "sso", "mfa")):
        return "security"

    if any(token in q for token in ("show the", "endpoint", "function", "python", "code", "implemented", "api creates")):
        return "code_related"

    if any(token in q for token in ("advantages", "why", "scalable", "trade-off", "impact")):
        return "analytical"

    if any(token in q for token in ("which embedding model", "which cloud", "choose", "decision")):
        return "decision_support"

    if any(token in q for token in ("between version", "across documents", "which documents", "all reports")):
        return "multi_document"

    if q.startswith(("what is", "define", "explain ")):
        return "definition"

    return "fact_based"


def _get_openai_client():
    """Lazily create and return an OpenAI client.

    This avoids raising an exception at import time when `OPENAI_API_KEY`
    is not set. The client will raise a clear error only when OpenAI is
    actually used and the API key is missing.
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    try:
        if config.OPENAI_API_KEY:
            _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        else:
            # Let the SDK pick up the key from environment variables if set;
            # this will raise OpenAIError if no key is available when used.
            _openai_client = OpenAI()
        return _openai_client
    except OpenAIError as e:
        # Re-raise with a clearer message for callers
        raise OpenAIError(
            "OpenAI client initialization failed: set OPENAI_API_KEY in environment or .env"
        ) from e


def _call_huggingface(model: str, prompt: str) -> str:
    """Call the Hugging Face Inference API for a single-text prompt.

    Args:
        model: Hugging Face model identifier (e.g., 'gpt2').
        prompt: Full prompt text to send to the model.

    Returns:
        The generated text returned by the model as a string.

    Raises:
        ValueError: if `HUGGINGFACE_API_KEY` is not configured.
        requests.HTTPError: for non-2xx HTTP responses.
    """

    if not config.HUGGINGFACE_API_KEY:
        raise ValueError("HUGGINGFACE_API_KEY is not set in environment")

    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {config.HUGGINGFACE_API_KEY}"}
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 512, "return_full_text": False},
        "options": {"wait_for_model": True},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Hugging Face inference API may return different shapes; handle common ones
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Hugging Face API error: {data['error']}")

    if isinstance(data, list):
        # Typical text-generation response: [{'generated_text': '...'}]
        first = data[0]
        if isinstance(first, dict) and "generated_text" in first:
            text = str(first["generated_text"])
            # Some text-generation models may still echo the prompt.
            if text.startswith(prompt):
                text = text[len(prompt):]
            return text.strip()
        # Some models return a plain string in first element
        if isinstance(first, str):
            text = first
            if text.startswith(prompt):
                text = text[len(prompt):]
            return text.strip()

    if isinstance(data, dict) and "generated_text" in data:
        text = str(data["generated_text"])
        if text.startswith(prompt):
            text = text[len(prompt):]
        return text.strip()

    # Fallback to string conversion
    return str(data)


def _call_openai(model: str, prompt: str) -> str:
    """Call OpenAI Responses API and return generated text."""

    client = _get_openai_client()
    response = client.responses.create(
        model=model,
        input=prompt,
        temperature=0,
    )
    return response.output_text or str(response)


def _call_fastest_provider(prompt: str) -> str:
    """Return the first successful response from OpenAI or Hugging Face.

    Raises:
        RuntimeError: if neither provider returns a valid response.
    """

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            "openai": executor.submit(_call_openai, config.OPENAI_LLM_MODEL, prompt),
            "huggingface": executor.submit(_call_huggingface, config.HUGGINGFACE_LLM_MODEL, prompt),
        }

        pending = set(futures.values())
        errors: list[str] = []

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                provider_name = next(name for name, task in futures.items() if task is future)
                try:
                    result = future.result()
                    if result and str(result).strip():
                        for other in pending:
                            other.cancel()
                        return str(result)
                    errors.append(f"{provider_name}: empty response")
                except (OpenAIError, requests.RequestException, RuntimeError, ValueError) as exc:
                    errors.append(f"{provider_name}: {exc}")

    detail = "; ".join(errors) if errors else "both providers failed"
    raise RuntimeError(f"Automatic provider mode failed ({detail})")


def _extract_section_references(context_chunks) -> list[str]:
    """Extract unique bracketed section labels from retrieved chunks."""

    references: list[str] = []
    for chunk in context_chunks:
        match = re.match(r"\[([^\]]+)\]", str(chunk).strip())
        if not match:
            continue
        label = match.group(1).strip()
        if label and label not in references:
            references.append(label)
    return references


def _append_references(answer: str, context_chunks) -> str:
    """Append a `References:` line when section labels are available."""

    refs = _extract_section_references(context_chunks)
    if (
        not refs
        or "references:" in answer.lower()
        or answer.strip() == NO_RELEVANT_INFO_RESPONSE
        or answer.strip().lower().startswith(EXTERNAL_RESPONSE_PREFIX.lower())
    ):
        return answer

    formatted = "; ".join(f"[{ref}]" for ref in refs)
    return f"{answer.rstrip()}\n\nReferences: {formatted}"


def _dedupe_chunks(context_chunks) -> list[str]:
    """Remove repeated retrieved chunks while preserving order."""

    unique: list[str] = []
    seen: set[str] = set()
    for chunk in context_chunks:
        cleaned = " ".join(str(chunk).split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(str(chunk))
    return unique


def _rerank_context_chunks(question: str, context_chunks) -> list[str]:
    """Reorder retrieved chunks so the most question-relevant chunks come first."""

    question_terms = _question_terms(question)
    if not context_chunks or not question_terms:
        return _dedupe_chunks(context_chunks)

    ranked: list[tuple[float, int, str]] = []
    for index, chunk in enumerate(_dedupe_chunks(context_chunks)):
        clean_chunk = _strip_section_label(chunk)
        chunk_terms = set(re.findall(r"[A-Za-z0-9']+", clean_chunk.lower()))
        overlap = question_terms & chunk_terms
        score = float(len(overlap) * 10)

        if chunk.lower().startswith("[section"):
            score += 1.5
        if clean_chunk and clean_chunk.lower().startswith(tuple(term + " " for term in question_terms)):
            score += 1.0
        if overlap:
            score += min(3.0, len(overlap) * 0.5)

        ranked.append((score, index, chunk))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [chunk for _, _, chunk in ranked]


def _clear_caches():
    """Reset in-memory caches for tests or explicit invalidation."""

    with _CACHE_LOCK:
        _RESPONSE_CACHE.clear()
        _RETRIEVAL_CACHE.clear()


def _normalize_question(question: str) -> str:
    return " ".join(str(question).split()).strip().lower()


def _normalize_scope_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() == "default":
        return None
    return cleaned


def _vector_signature(query_embedding) -> str:
    values = [f"{float(value):.4f}" for value in query_embedding]
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def _cache_key_prefix(vector_store, tenant_id: str | None, collection_id: str | None, document_id: str | None) -> tuple:
    return (
        int(getattr(vector_store, "revision", 0) or 0),
        config.LLM_PROVIDER,
        config.OPENAI_LLM_MODEL,
        config.HUGGINGFACE_LLM_MODEL,
        config.TOP_K,
        _normalize_scope_value(tenant_id) or "",
        _normalize_scope_value(collection_id) or "",
        _normalize_scope_value(document_id) or "",
    )


def _normalize_optional_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _build_retrieval_filters(
    tenant_id: str | None,
    collection_id: str | None,
    document_id: str | None,
    document_date: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    source_system: str | None = None,
) -> tuple[str | None, str | None, str | None, dict]:
    tenant_scope = _normalize_scope_value(tenant_id)
    collection_scope = _normalize_scope_value(collection_id)
    document_scope = _normalize_scope_value(document_id)
    date_scope = _normalize_optional_filter(document_date)
    author_scope = _normalize_optional_filter(author)
    tag_scope = _normalize_optional_filter(tag)
    source_scope = _normalize_optional_filter(source_system)

    filters = {}
    if tenant_scope:
        filters["tenant_id"] = tenant_scope
    if collection_scope:
        filters["collection_id"] = collection_scope
    if document_scope:
        filters["document_id"] = document_scope
    if date_scope:
        filters["document_date"] = date_scope
    if author_scope:
        filters["author"] = author_scope
    if tag_scope:
        filters["tag"] = tag_scope
    if source_scope:
        filters["source_system"] = source_scope

    return tenant_scope, collection_scope, document_scope, filters


def _cache_get(cache: OrderedDict, key):
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = cache.get(key)
        if entry is None:
            return None

        expires_at, value = entry
        if expires_at <= now:
            cache.pop(key, None)
            return None

        cache.move_to_end(key)
        return value


def _cache_set(cache: OrderedDict, key, value, max_size: int):
    expires_at = time.monotonic() + _CACHE_TTL_SECONDS
    with _CACHE_LOCK:
        cache[key] = (expires_at, value)
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)


def _post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    """POST JSON to a service endpoint and return the decoded payload."""

    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Service {url} returned an unexpected response shape")
    return data


def _retrieve_context_chunks(
    question: str,
    query_embedding,
    vector_store,
    tenant_id: str | None,
    collection_id: str | None,
    document_id: str | None,
    document_date: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    source_system: str | None = None,
):
    """Get candidate chunks locally or from a dedicated retrieval service."""

    tenant_scope, collection_scope, document_scope, filters = _build_retrieval_filters(
        tenant_id,
        collection_id,
        document_id,
        document_date=document_date,
        author=author,
        tag=tag,
        source_system=source_system,
    )

    if config.RETRIEVAL_SERVICE_URL:
        payload = {
            "question": question,
            "tenant_id": tenant_scope,
            "collection_id": collection_scope,
            "document_id": document_scope,
            "document_date": filters.get("document_date"),
            "author": filters.get("author"),
            "tag": filters.get("tag"),
            "source_system": filters.get("source_system"),
            "top_k": config.TOP_K,
            "candidate_pool_size": config.RETRIEVAL_RERANK_POOL_SIZE,
        }
        data = _post_json(f"{config.RETRIEVAL_SERVICE_URL}/search", payload)
        return data.get("context_chunks", [])

    cache_prefix = _cache_key_prefix(vector_store, tenant_scope, collection_scope, document_scope)
    retrieval_cache_key = (
        "retrieval",
        *cache_prefix,
        config.RETRIEVAL_RERANK_POOL_SIZE,
        _vector_signature(query_embedding),
    )
    cached_search_results = _cache_get(_RETRIEVAL_CACHE, retrieval_cache_key)
    if cached_search_results is not None:
        search_results = list(cached_search_results)
    else:
        try:
            search_results = vector_store.search(
                query_embedding,
                config.RETRIEVAL_RERANK_POOL_SIZE,
                source_document=document_scope,
                filters=filters or None,
            )
        except TypeError:
            # Backward compatibility for legacy vector-store implementations
            # that only support search(query_embedding, top_k).
            search_results = vector_store.search(query_embedding, config.TOP_K)
        _cache_set(_RETRIEVAL_CACHE, retrieval_cache_key, list(search_results), _RETRIEVAL_CACHE_MAX_SIZE)

    return _rerank_context_chunks(question, search_results)[: config.TOP_K]


def _generate_from_prompt(prompt: str) -> str:
    """Generate text using the configured local provider or an external inference service."""

    if config.INFERENCE_SERVICE_URL:
        data = _post_json(f"{config.INFERENCE_SERVICE_URL}/generate", {"prompt": prompt})
        answer = data.get("answer", "")
        return str(answer)

    if config.LLM_PROVIDER == "huggingface":
        return _call_huggingface(config.HUGGINGFACE_LLM_MODEL, prompt)
    if config.LLM_PROVIDER == "auto":
        return _call_fastest_provider(prompt)
    return _call_openai(config.OPENAI_LLM_MODEL, prompt)


def _question_terms(question: str) -> set[str]:
    """Extract meaningful search terms from a user question."""

    return {
        token
        for token in re.findall(r"[A-Za-z0-9']+", question.lower())
        if len(token) > 2 and token not in _QUESTION_STOP_WORDS
    }


def _answer_terms(answer: str) -> set[str]:
    """Extract meaningful terms from a generated answer."""

    return {
        token
        for token in re.findall(r"[A-Za-z0-9']+", answer.lower())
        if len(token) > 2 and token not in _ANSWER_STOP_WORDS
    }


def _minimum_overlap_required(terms: set[str]) -> int:
    """Return the minimum overlap count needed for relevance checks."""

    if not terms:
        return 0
    if len(terms) == 1:
        return 1
    return 2


def _is_high_signal_term(term: str) -> bool:
    """Return True when a single overlap term is specific enough to trust."""

    cleaned = str(term or "").strip().lower()
    if not cleaned or cleaned in _GENERIC_QUERY_TERMS:
        return False
    if cleaned.isdigit():
        return False
    return len(cleaned) >= 5


def _strip_section_label(text: str) -> str:
    """Remove a leading bracketed section label from chunk text."""

    return re.sub(r"^\[[^\]]+\]\s*", "", text).strip()


def _has_relevant_context(question: str, context_chunks) -> bool:
    """Return True when retrieved chunks appear relevant to the question."""

    if not context_chunks:
        return False

    terms = _question_terms(question)
    if not terms:
        return True

    required_overlap = _minimum_overlap_required(terms)

    for chunk in context_chunks:
        chunk_terms = set(re.findall(r"[A-Za-z0-9']+", _strip_section_label(str(chunk)).lower()))
        overlap = terms & chunk_terms
        if len(overlap) >= required_overlap:
            return True
        if len(overlap) == 1 and len(terms) <= 3:
            term = next(iter(overlap))
            if _is_high_signal_term(term):
                return True

    return False


def _answer_addresses_question(question: str, answer: str) -> bool:
    """Return True when the answer appears responsive to the user's question."""

    question_terms = _question_terms(question)
    if not question_terms:
        return True

    answer_terms = _answer_terms(answer)
    if not answer_terms:
        return False

    overlap = question_terms & answer_terms
    return len(overlap) >= 1


def _retrieval_quality_score(question: str, context_chunks) -> float:
    """Estimate how well the retrieved chunks match the question."""

    question_terms = _question_terms(question)
    if not question_terms or not context_chunks:
        return 0.0

    scores: list[float] = []
    for chunk in context_chunks:
        chunk_terms = set(re.findall(r"[A-Za-z0-9']+", _strip_section_label(str(chunk)).lower()))
        overlap = question_terms & chunk_terms
        if not overlap:
            scores.append(0.0)
            continue
        scores.append(len(overlap) / max(1, len(question_terms)))

    return max(scores) if scores else 0.0


def _is_answer_grounded(answer: str, context_chunks) -> bool:
    """Return True when the answer appears supported by retrieved context."""

    if not context_chunks:
        return False

    answer_body = str(answer).strip()
    if not answer_body:
        return False

    answer_body = re.sub(r"\n+References:.*$", "", answer_body, flags=re.IGNORECASE | re.DOTALL).strip()
    if answer_body.lower().startswith(EXTERNAL_RESPONSE_PREFIX.lower()):
        return False

    normalized_context = "\n".join(_strip_section_label(str(chunk)) for chunk in context_chunks)
    context_lower = normalized_context.lower()
    answer_lower = answer_body.lower()
    if answer_lower in context_lower:
        return True

    context_terms = set(re.findall(r"[A-Za-z0-9']+", context_lower))
    answer_terms = _answer_terms(answer_body)
    if not answer_terms:
        return False

    overlap = answer_terms & context_terms
    return len(overlap) >= max(1, min(2, len(answer_terms))) and (len(overlap) / len(answer_terms)) >= 0.4


def _provider_error_answer(question: str, context_chunks, exc: Exception) -> str:
    """Build a concise document-grounded answer when the LLM is unavailable."""

    del exc  # The user-facing answer should stay focused on the document.

    context_chunks = _dedupe_chunks(context_chunks)
    if not _has_relevant_context(question, context_chunks):
        return NO_RELEVANT_INFO_RESPONSE

    terms = _question_terms(question)

    best_sentence = ""
    best_score = -1
    for chunk in context_chunks:
        clean_chunk = _strip_section_label(str(chunk))
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", clean_chunk)
            if sentence.strip()
        ] or [clean_chunk]

        for index, sentence in enumerate(sentences):
            sentence_terms = set(re.findall(r"[A-Za-z0-9']+", sentence.lower()))
            overlap = len(sentence_terms & terms)
            score = overlap * 10 - index
            if score > best_score:
                best_score = score
                best_sentence = sentence

    if not best_sentence:
        best_sentence = _strip_section_label(str(context_chunks[0]))

    return best_sentence


def _finalize_answer(answer: str, question: str, context_chunks) -> str:
    """Normalize final answer formatting before returning it to callers."""

    cleaned = str(answer).strip()
    if not cleaned:
        return NO_RELEVANT_INFO_RESPONSE
    if cleaned == NO_RELEVANT_INFO_RESPONSE:
        return cleaned
    if cleaned.lower().startswith(EXTERNAL_RESPONSE_PREFIX.lower()):
        return cleaned
    if not _is_answer_grounded(cleaned, context_chunks):
        return NO_RELEVANT_INFO_RESPONSE
    if not _answer_addresses_question(question, cleaned):
        return NO_RELEVANT_INFO_RESPONSE
    return _append_references(cleaned, context_chunks)


def generate_answer(
    question,
    vector_store,
    tenant_id: str | None = None,
    collection_id: str | None = None,
    document_id: str | None = None,
    document_date: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    source_system: str | None = None,
):
    """Generate an answer for `question` using `vector_store` as context.

    This function:
    1. Embeds the user `question` and retrieves the top-K most similar
       chunks from `vector_store`.
    2. Assembles a prompt that instructs the model to answer using ONLY
       the provided context.
    3. Calls the configured LLM provider (Hugging Face or OpenAI Responses)
       and returns the generated text.

    Args:
        question: User question as a string.
        vector_store: Object implementing `search(query_embedding, top_k)` and
            returning a list of text chunks. This module expects the
            repository's `VectorStore` interface.

    Returns:
        A string containing the model's answer. If the model cannot find the
        answer in the context, it should respond with "I don't know." as
        instructed in the prompt.
    """

    request_started_at = time.monotonic()
    tenant_scope, collection_scope, document_scope, filters = _build_retrieval_filters(
        tenant_id,
        collection_id,
        document_id,
        document_date=document_date,
        author=author,
        tag=tag,
        source_system=source_system,
    )

    cache_prefix = (
        *_cache_key_prefix(vector_store, tenant_scope, collection_scope, document_scope),
        filters.get("document_date") or "",
        filters.get("author") or "",
        filters.get("tag") or "",
        filters.get("source_system") or "",
    )
    normalized_question = _normalize_question(question)
    response_cache_key = ("response", *cache_prefix, normalized_question)
    cached_answer = _cache_get(_RESPONSE_CACHE, response_cache_key)
    if cached_answer is not None:
        logger.debug("Response cache hit for question=%r.", normalized_question)
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return cached_answer

    query_embedding = embed_text([question])[0]
    context_chunks = _retrieve_context_chunks(
        question,
        query_embedding,
        vector_store,
        tenant_scope,
        collection_scope,
        document_scope,
        document_date=filters.get("document_date"),
        author=filters.get("author"),
        tag=filters.get("tag"),
        source_system=filters.get("source_system"),
    )
    slo_metrics.record_retrieval_quality(question, context_chunks, _retrieval_quality_score(question, context_chunks))

    if not context_chunks:
        _cache_set(_RESPONSE_CACHE, response_cache_key, NO_RELEVANT_INFO_RESPONSE, _RESPONSE_CACHE_MAX_SIZE)
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return NO_RELEVANT_INFO_RESPONSE

    context = "\n\n".join(context_chunks)

    prompt = f"""Answer the question using ONLY the information provided in the context below.
You may summarize, paraphrase, and synthesize information from the context to form your answer.
If the context does not contain enough information to answer the question at all, return exactly:
"{NO_RELEVANT_INFO_RESPONSE}"
Do not use outside knowledge or facts not present in the context.
At the end of your answer, include a `References:` line citing the relevant bracketed section labels from the context.

Context:
{context}

Question:
{question}
"""

    logger.info(
        "Generating answer — provider: %s | %d context chunks",
        config.LLM_PROVIDER,
        len(context_chunks),
    )
    _t0 = time.monotonic()
    try:
        answer = _generate_from_prompt(prompt)
        logger.info("Answer generated in %.2fs.", time.monotonic() - _t0)
        # Trust the LLM response; it was instructed to return NO_RELEVANT_INFO_RESPONSE
        # when context is insufficient. Keyword-based grounding checks cause false
        # negatives when the LLM correctly paraphrases or uses synonyms of context terms.
        cleaned = str(answer).strip() or NO_RELEVANT_INFO_RESPONSE
        if cleaned == NO_RELEVANT_INFO_RESPONSE or cleaned.lower().startswith(EXTERNAL_RESPONSE_PREFIX.lower()):
            final_answer = cleaned
        else:
            final_answer = _append_references(cleaned, context_chunks)
        _cache_set(_RESPONSE_CACHE, response_cache_key, final_answer, _RESPONSE_CACHE_MAX_SIZE)
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return final_answer
    except (OpenAIError, requests.RequestException, RuntimeError, ValueError) as exc:
        logger.warning(
            "LLM provider failed (%.2fs): %s — using fallback answer.",
            time.monotonic() - _t0, exc,
        )
        final_answer = _finalize_answer(_provider_error_answer(question, context_chunks, exc), question, context_chunks)
        _cache_set(_RESPONSE_CACHE, response_cache_key, final_answer, _RESPONSE_CACHE_MAX_SIZE)
        slo_metrics.record_request(time.monotonic() - request_started_at, success=False)
        return final_answer
