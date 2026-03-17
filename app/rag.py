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

Notes:
- OpenAI client initialization is lazy to avoid import-time failures when
    `OPENAI_API_KEY` is not yet available. A clear error is raised when the
    client is first used and the API key is missing.
"""

import os

import requests
from openai import OpenAI, OpenAIError

from .config import HUGGINGFACE_API_KEY, LLM_MODEL, LLM_PROVIDER, OPENAI_API_KEY, TOP_K
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
        if OPENAI_API_KEY:
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
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

    if not HUGGINGFACE_API_KEY:
        raise ValueError("HUGGINGFACE_API_KEY is not set in environment")

    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
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

    Raises:
        Any exceptions raised by the underlying embedding/model APIs will
        propagate to the caller.
    """

    query_embedding = embed_text([question])[0]
    context_chunks = vector_store.search(query_embedding, TOP_K)

    context = "\n\n".join(context_chunks)

    prompt = f""" 
Answer the question using ONLY the context below.
If the answer is not found, say "I don't know."

Context:
{context}

Question:
{question}
"""
# How to us hugging face? The function checks the `LLM_PROVIDER` configuration variable to determine which LLM 
# provider to use. If `LLM_PROVIDER` is set to "huggingface" (case-insensitive), it calls the `_call_huggingface` 
# helper function, passing the configured `LLM_MODEL` and the constructed `prompt`. The `_call_huggingface` function 
# handles the API call to Hugging Face's Inference API and returns the generated text. If `LLM_PROVIDER` is not set 
# to "huggingface", the function defaults to using the OpenAI Responses API via the `_get_openai_client` helper, 
# which initializes an OpenAI client and sends a request with the prompt, returning the generated answer.
    if LLM_PROVIDER.lower() == "huggingface":
        # Use the Hugging Face Inference API
        return _call_huggingface(LLM_MODEL, prompt)

    # Default: use OpenAI Responses API (1.x SDK)
    client = _get_openai_client()
    response = client.responses.create(
        model=LLM_MODEL,
        input=prompt,
        temperature=0
    )
    return response.output_text or str(response)
