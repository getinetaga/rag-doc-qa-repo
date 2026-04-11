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

import re

import requests
from openai import OpenAI, OpenAIError

from . import config
from .embeddings import embed_text

_openai_client = None


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
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 512}}

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
            return first["generated_text"]
        # Some models return a plain string in first element
        if isinstance(first, str):
            return first

    if isinstance(data, dict) and "generated_text" in data:
        return data["generated_text"]

    # Fallback to string conversion
    return str(data)


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
    if not refs or "references:" in answer.lower():
        return answer

    formatted = "; ".join(f"[{ref}]" for ref in refs)
    return f"{answer.rstrip()}\n\nReferences: {formatted}"


def _provider_error_answer(context_chunks, exc: Exception) -> str:
    """Return a user-friendly fallback when the LLM provider is unavailable."""

    preview_items = []
    for chunk in context_chunks[:3]:
        cleaned = " ".join(str(chunk).split())
        if cleaned:
            preview_items.append(f"- {cleaned[:220]}")

    preview = "\n".join(preview_items) or "- No context was retrieved from the document."
    return (
        "The configured LLM provider is temporarily unavailable, so I couldn't "
        f"generate a final answer right now ({exc}).\n\n"
        "Relevant retrieved context:\n"
        f"{preview}"
    )


def generate_answer(question, vector_store):
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

    query_embedding = embed_text([question])[0]
    context_chunks = vector_store.search(query_embedding, config.TOP_K)

    context = "\n\n".join(context_chunks)

    prompt = f""" 
Answer the question using ONLY the context below.
If the answer is not found, say "I don't know."
At the end of the answer, include a `References:` line citing the relevant
bracketed section labels from the context.

Context:
{context}

Question:
{question}
"""

    try:
        if config.LLM_PROVIDER.lower() == "huggingface":
            answer = _call_huggingface(config.LLM_MODEL, prompt)
            return _append_references(answer, context_chunks)

        client = _get_openai_client()
        response = client.responses.create(
            model=config.LLM_MODEL,
            input=prompt,
            temperature=0,
        )
        answer = response.output_text or str(response)
        return _append_references(answer, context_chunks)
    except (OpenAIError, requests.RequestException, RuntimeError, ValueError) as exc:
        return _append_references(_provider_error_answer(context_chunks, exc), context_chunks)
