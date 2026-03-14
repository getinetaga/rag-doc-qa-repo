"""Minimal FAISS-backed in-memory vector store used by the demo.

This module provides a tiny wrapper around a FAISS `IndexFlatL2` index
to store float32 embeddings alongside their source text chunks and to
perform nearest-neighbor searches. It is intentionally small and
synchronous so it is easy to use inside the Streamlit demo and unit
tests. For production use you may want a persistent, sharded, or
approximate index (HNSW, IVF, etc.) and additional metadata handling.
"""

import faiss
import numpy as np


class VectorStore:
    """In-memory vector store that holds embeddings and their texts.

    Args:
        dim: Dimensionality of the embedding vectors. This is used to
            initialize a FAISS IndexFlatL2 index for L2-distance search.

    Notes:
        - Embeddings are stored in FAISS as float32 arrays. Input
          sequences are converted with NumPy before insertion.
        - The `texts` list stores the original text chunk for each
          inserted vector and is used to reconstruct search results.
    """

    def __init__(self, dim: int):
        self.index = faiss.IndexFlatL2(dim)
        self.texts = []

    def add(self, embeddings, texts):
        """Add a batch of embeddings and their corresponding texts.

        Args:
            embeddings: Sequence[list[float]] or NumPy array of shape
                (n, dim) containing embedding vectors.
            texts: Sequence[str] with length `n` containing the text
                associated with each embedding.
        """

        arr = np.array(embeddings).astype("float32")
        self.index.add(arr)
        self.texts.extend(texts)

    def search(self, query_embedding, top_k=5):
        """Return the top_k most similar text chunks for a query.

        Args:
            query_embedding: 1-D sequence or NumPy array representing
                the query vector.
            top_k: Number of neighbors to retrieve.

        Returns:
            List[str]: the text chunks corresponding to the nearest
            neighbors, ordered from most to least similar.
        """

        q = np.array([query_embedding]).astype("float32")
        _, I = self.index.search(q, top_k)
        # I is an (1, top_k) array of indices into self.texts
        return [self.texts[i] for i in I[0]]
