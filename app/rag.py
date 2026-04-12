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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

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
    if not refs or "references:" in answer.lower():
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


def _strip_section_label(text: str) -> str:
    """Remove a leading bracketed section label from chunk text."""

    return re.sub(r"^\[[^\]]+\]\s*", "", text).strip()


def _provider_error_answer(question: str, context_chunks, exc: Exception) -> str:
    """Build a concise document-grounded answer when the LLM is unavailable."""

    del exc  # The user-facing answer should stay focused on the document.

    context_chunks = _dedupe_chunks(context_chunks)
    if not context_chunks:
        return "I don't know."

    terms = {
        token
        for token in re.findall(r"[A-Za-z0-9']+", question.lower())
        if len(token) > 2 and token not in {"what", "which", "where", "when", "with", "from", "that", "this", "about", "document"}
    }

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
    context_chunks = _dedupe_chunks(vector_store.search(query_embedding, config.TOP_K))

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
        if config.LLM_PROVIDER == "huggingface":
            answer = _call_huggingface(config.HUGGINGFACE_LLM_MODEL, prompt)
            return _append_references(answer, context_chunks)

        if config.LLM_PROVIDER == "auto":
            answer = _call_fastest_provider(prompt)
            return _append_references(answer, context_chunks)

        answer = _call_openai(config.OPENAI_LLM_MODEL, prompt)
        return _append_references(answer, context_chunks)
    except (OpenAIError, requests.RequestException, RuntimeError, ValueError) as exc:
        return _append_references(_provider_error_answer(question, context_chunks, exc), context_chunks)
