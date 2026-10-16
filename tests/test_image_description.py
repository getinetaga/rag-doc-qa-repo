import base64
import io
import json
import threading
from types import SimpleNamespace

from fastapi import HTTPException
from openai import OpenAIError
from PIL import Image
import pytest

from app import config, image_description, ingestion, main
from app.ingestion_errors import IngestionError
from app.vector_store import VectorStore


def image_bytes():
    output = io.BytesIO()
    Image.new("RGBA", (96, 64), (255, 0, 0, 128)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def vision(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "IMAGE_DESCRIPTION_ENABLED", True)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setattr(config, "OPENAI_VISION_MODEL", "gpt-4o-mini")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status="completed", output_text="A red rectangle appears on a white background.", output=[],
        )
    monkeypatch.setattr(image_description, "_get_openai_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create),
    ))
    path = tmp_path / "synthetic.png"
    path.write_bytes(image_bytes())
    return path, calls


def test_visual_request_normalizes_image_and_keeps_provider_storage_off(vision):
    path, calls = vision
    checked = []
    description = image_description.describe_image(str(path), before_dispatch=lambda: checked.append(True))
    assert "red rectangle" in description
    assert checked == [True]
    assert calls[0]["model"] == "gpt-4o-mini"
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] == 1200
    content = calls[0]["input"][0]["content"]
    assert "untrusted" in content[0]["text"]
    url = content[1]["image_url"]
    assert url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as normalized:
        assert normalized.mode == "RGB"
        assert normalized.size == (96, 64)
        assert not normalized.getexif()


@pytest.mark.parametrize("failure", ["disabled", "invalid", "pixels", "bytes", "multiframe"])
def test_invalid_or_disabled_images_never_dispatch(vision, monkeypatch, failure):
    path, calls = vision
    if failure == "disabled":
        monkeypatch.setattr(config, "IMAGE_DESCRIPTION_ENABLED", False)
    elif failure == "invalid":
        path.write_bytes(b"not an image")
    elif failure == "pixels":
        monkeypatch.setattr(image_description, "MAX_IMAGE_PIXELS", 1)
    elif failure == "bytes":
        monkeypatch.setattr(image_description, "MAX_IMAGE_BYTES", 1)
    else:
        Image.new("RGB", (20, 20), "red").save(
            path, format="GIF", save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")],
        )
    with pytest.raises(IngestionError):
        image_description.describe_image(str(path), before_dispatch=lambda: None)
    assert calls == []


def test_revocation_before_dispatch_never_sends_image(vision):
    path, calls = vision
    def denied():
        raise HTTPException(403, "Access removed.")
    with pytest.raises(HTTPException):
        image_description.describe_image(str(path), before_dispatch=denied)
    assert calls == []


@pytest.mark.parametrize("response", [
    SimpleNamespace(status="completed", output_text="", output=[]),
    SimpleNamespace(status="incomplete", output_text="partial description", output=[]),
    SimpleNamespace(status="completed", output_text="refused", output=[
        SimpleNamespace(content=[SimpleNamespace(type="refusal")]),
    ]),
])
def test_empty_partial_and_refused_outputs_are_not_indexable(vision, monkeypatch, response):
    path, _ = vision
    monkeypatch.setattr(image_description, "_get_openai_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: response),
    ))
    with pytest.raises(IngestionError, match="usable image description"):
        image_description.describe_image(str(path), before_dispatch=lambda: None)


def test_provider_failure_is_sanitized(vision, monkeypatch, caplog):
    path, _ = vision
    def failed(**kwargs):
        raise OpenAIError("private-provider-details")
    monkeypatch.setattr(image_description, "_get_openai_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=failed),
    ))
    with pytest.raises(IngestionError) as error:
        image_description.describe_image(str(path), before_dispatch=lambda: None)
    assert error.value.code == "image_description_failed"
    assert "private-provider-details" not in str(error.value)
    assert "private-provider-details" not in caplog.text


def test_scoped_visual_upload_bypasses_ocr_and_labels_every_chunk(secured, vision, monkeypatch):
    client, keys, _, _ = secured
    _, calls = vision
    store = VectorStore(2, backend="faiss")
    monkeypatch.setattr(main, "vector_store", store)
    monkeypatch.setattr(main, "embed_text", lambda chunks: [[1, 0] for _ in chunks])
    monkeypatch.setattr(main, "extract_text", lambda path: pytest.fail("OCR must not run"))
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 10**9)
    result = client.post("/upload", headers={"Authorization": f"Bearer {keys['writer']}"}, data={
        "image_mode": "describe", "document_id": "synthetic",
    }, files={"file": ("synthetic.png", image_bytes(), "image/png")})
    assert result.status_code == 200, result.text
    assert result.json()["content_kind"] == "ai_image_description"
    assert "red rectangle" in result.json()["image_description"]
    records = store.search([1, 0], filters={"tenant_id": "tenant-a", "collection_id": "project-a"})
    assert records
    assert all(record.metadata["content_kind"] == "ai_image_description" for record in records)
    assert all(image_description.DESCRIPTION_WARNING in record.text for record in records)
    assert store.search([1, 0], filters={"tenant_id": "tenant-b", "collection_id": "project-b"}) == []
    assert len(calls) == 1


def test_upload_denials_and_unsupported_modes_do_not_dispatch(secured, vision, monkeypatch):
    client, keys, _, _ = secured
    _, calls = vision
    for name, data, filename, expected in [
        ("reader", {"image_mode": "describe"}, "image.png", 403),
        ("writer", {"image_mode": "describe", "tenant_id": "tenant-b"}, "image.png", 403),
        ("writer", {"image_mode": "describe"}, "document.txt", 422),
        ("writer", {"image_mode": "unknown"}, "image.png", 422),
    ]:
        result = client.post("/upload", headers={"Authorization": f"Bearer {keys[name]}"},
                             data=data, files={"file": (filename, image_bytes())})
        assert result.status_code == expected
    monkeypatch.setattr(config, "IMAGE_DESCRIPTION_ENABLED", False)
    result = client.post("/upload", headers={"Authorization": f"Bearer {keys['writer']}"},
                         data={"image_mode": "describe"}, files={"file": ("image.png", image_bytes())})
    assert result.status_code == 503
    assert result.json()["error_code"] == "image_description_disabled"
    assert calls == []


def test_busy_and_failed_visual_uploads_release_capacity_and_keep_old_index(secured, vision, monkeypatch):
    client, keys, _, _ = secured
    _, calls = vision
    store = VectorStore(2, backend="faiss")
    store.add([[1, 0]], ["original source"])
    monkeypatch.setattr(main, "vector_store", store)
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 10**9)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(main, "_answer_slots", slots)
    slots.acquire()
    def upload(payload):
        return client.post("/upload", headers={"Authorization": f"Bearer {keys['writer']}"},
                           data={"image_mode": "describe"}, files={"file": ("image.png", payload)})
    result = upload(image_bytes())
    assert result.status_code == 503
    assert result.json()["error_code"] == "image_description_busy"
    slots.release()
    assert upload(b"invalid image").status_code == 422
    assert slots.acquire(blocking=False)
    slots.release()
    assert store.search([1, 0])[0].text == "original source"
    assert calls == []


def test_ocr_missing_engine_reports_safe_actionable_code(tmp_path, monkeypatch):
    import pytesseract
    path = tmp_path / "text.png"
    path.write_bytes(image_bytes())
    def missing(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(pytesseract, "image_to_string", missing)
    with pytest.raises(IngestionError) as error:
        ingestion.extract_image(path)
    assert error.value.code == "ocr_unavailable"


def test_revocation_during_description_prevents_publication(secured, vision, monkeypatch):
    client, keys, policy, policy_path = secured
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 10**9)
    monkeypatch.setattr(main, "embed_text", lambda chunks: [[1, 0] for _ in chunks])
    store = VectorStore(2, backend="faiss")
    monkeypatch.setattr(main, "vector_store", store)
    def revoked(**kwargs):
        policy["users"][0]["roles"] = ["read"]
        policy_path.write_text(json.dumps(policy))
        return SimpleNamespace(status="completed", output_text="A red rectangle.", output=[])
    monkeypatch.setattr(image_description, "_get_openai_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=revoked),
    ))
    result = client.post("/upload", headers={"Authorization": f"Bearer {keys['writer']}"},
                         data={"image_mode": "describe"}, files={"file": ("image.png", image_bytes())})
    assert result.status_code == 403
    assert store.search([1, 0]) == []
