"""Embeddings helper using SentenceTransformers.

Responsibilities:
- Lazily load and cache a SentenceTransformer model in a thread-safe way.
- Provide a small wrapper to encode a list/iterable of texts to embeddings
  (returns a NumPy array).

Notes:
- Avoids global changes to SSL settings. If you need to customize TLS
  certificate authorities for model downloads, use `certifi` explicitly
  when constructing network clients; do not disable verification globally.
"""

import threading #Threading is used to ensure that the model is loaded in a thread-safe manner, preventing multiple threads from loading the model simultaneously.
from typing import Iterable

import numpy as np

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None# Global variable to hold the loaded model instance. Initialized to None and set on first call to get_model().
_model_lock = threading.Lock() # Lock to ensure thread-safe initialization of the model.


def get_model():
    """Return a cached SentenceTransformer model instance.

    The model is loaded lazily on first call and protected by a lock so
    multiple threads don't attempt to construct it concurrently. The
    function returns the model instance from the `sentence_transformers`
    library.

    Returns:
        SentenceTransformer: loaded embedding model.
    """

    global _model
    if _model is not None:
        return _model

    with _model_lock:
        # Double-check inside the lock
        if _model is not None:
            return _model

        # Import inside the loader to avoid heavy imports at module import time
        try:
            from sentence_transformers import SentenceTransformer
        except Exception:
            raise

        _model = SentenceTransformer(_MODEL_NAME)
        return _model


def embed_text(texts: Iterable[str], batch_size: int = 32) -> np.ndarray:
    """Encode input texts into dense embeddings.

    Args:
        texts: An iterable of strings to embed. Will be cast to a list internally.
        batch_size: Optional batch size to use during encoding (passed to the
            underlying model). Default is 32.

    Returns:
        numpy.ndarray: float32 array of shape (len(texts), embedding_dim).

    Raises:
        ValueError: if input contains non-string items.
        RuntimeError: if encoding fails for any reason.
    """

    texts_list = list(texts)
    # Fast-path: empty input -> return empty array with 0 rows
    if len(texts_list) == 0:
        # dimension unknown without loading model; return empty 2D array
        return np.empty((0, 0), dtype="float32")

    # Validate inputs are strings
    for i, t in enumerate(texts_list):
        if not isinstance(t, str):
            raise ValueError(f"embed_text expects strings; item {i} is {type(t)}")

    model = get_model()
    try:
        # Request NumPy output explicitly and avoid progress bars in servers
        embeddings = model.encode(
            texts_list,
            show_progress_bar=False,# why is it set to false? In a server environment, progress bars can clutter logs and are not useful, so we disable them by default.
            convert_to_numpy=True,
            batch_size=batch_size,
        )
        return np.array(embeddings, dtype="float32")
    except Exception as e:
        raise RuntimeError("Failed to create embeddings") from e
