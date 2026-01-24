# Retrieval + Generation

import openai
from .config import OPENAI_API_KEY, LLM_MODEL, TOP_K
from .embeddings import embed_text

openai.api_key = OPENAI_API_KEY

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

    response = openai.ChatCompletion.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return response.choices[0].message.content
