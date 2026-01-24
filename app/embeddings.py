from sentence_transformers import SentenceTransformer
import ssl
import certifi

# Disable SSL verification for model download
ssl._create_default_https_context = ssl._create_unverified_context

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def embed_text(texts: list[str]):
    model = get_model()
    return model.encode(texts, show_progress_bar=False)
