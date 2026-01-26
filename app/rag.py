# Retrieval + Generation

import os

from openai import OpenAI
import requests

from .config import (HUGGINGFACE_API_KEY, LLM_MODEL, LLM_PROVIDER,
                     OPENAI_API_KEY, TOP_K)
from .embeddings import embed_text

# Initialize OpenAI client. If OPENAI_API_KEY is not set, the client will
# fall back to the environment variable behavior supported by the SDK.
_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()


def _call_huggingface(model: str, prompt: str) -> str:
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

    if LLM_PROVIDER.lower() == "huggingface":
        # Use the Hugging Face Inference API
        return _call_huggingface(LLM_MODEL, prompt)

    # Default: use OpenAI Responses API (1.x SDK)
    try:
        response = _openai_client.responses.create(
            model=LLM_MODEL,
            input=prompt,
            temperature=0
        )

        # Prefer the convenience property if available
        if hasattr(response, "output_text") and response.output_text:
            return response.output_text

        # Fallback: assemble text from structured output
        outputs = []
        for item in getattr(response, "output", []) or []:
            # each item may have a `content` list containing dicts or strings
            for chunk in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(chunk, dict) and "text" in chunk:
                    outputs.append(chunk["text"])
                elif isinstance(chunk, str):
                    outputs.append(chunk)

        if outputs:
            return "".join(outputs)

        # Last resort: stringify the response
        return str(response)
    except Exception:
        # Surface the error rather than failing silently
        raise
