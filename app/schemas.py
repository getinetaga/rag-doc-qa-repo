"""Pydantic request/response schemas used by the RAG API and demo.

This module defines small, explicit schemas for the service API:
- `QuestionRequest` — request body containing the user's question.
- `AnswerResponse` — response body containing the model's answer.

Keeping these schemas minimal keeps the example app easy to extend
for additional metadata (e.g., provenance, confidence) in the future.
"""

from typing import Literal

from pydantic import BaseModel, model_validator
# BaseModel is used as the base class for defining the Pydantic models (schemas) for request and response 
# bodies in the FastAPI application. It provides data validation and serialization capabilities, ensuring that 
# incoming requests and outgoing responses conform to the defined structure.


class QuestionRequest(BaseModel):
    """Request body for asking a question.

    Attributes:
        question: The user's natural-language question as a string.
    """

    question: str
    tenant_id: str = "default"
    collection_id: str = "default"
    document_id: str = "default"
    document_date: str | None = None
    author: str | None = None
    tag: str | None = None
    source_system: str | None = None


class AnswerResponse(BaseModel):
    """Response body returned by the RAG endpoint.

    Attributes:
        answer: The text answer produced by the model. The application
            currently returns a plain string; consider extending this
            schema to include `sources` or `confidence` if desired.
    """

    answer: str
    question_domain: str | None = None


class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: Literal["up", "down"]
    correction: str | None = None
    tenant_id: str = "default"
    collection_id: str = "default"
    document_id: str = "default"
    document_date: str | None = None
    author: str | None = None
    tag: str | None = None
    source_system: str | None = None


class FeedbackResponse(BaseModel):
    feedback_id: int
    status: str


class GoogleDocIngestRequest(BaseModel):
    google_doc_url: str
    tenant_id: str = "default"
    collection_id: str = "default"
    document_id: str = "default"
    document_date: str | None = None
    author: str | None = None
    tag: str | None = None
    source_system: str = "google_docs"


class SharePointIngestRequest(BaseModel):
    """Ingest a SharePoint document via Microsoft Graph.

    Supply either ``sharepoint_url`` (a shareable link to the file) or
    ``item_id`` together with one of ``drive_id`` / ``site_id``.
    """

    sharepoint_url: str | None = None
    site_id: str | None = None
    drive_id: str | None = None
    item_id: str | None = None
    tenant_id: str = "default"
    collection_id: str = "default"
    document_id: str = "default"
    document_date: str | None = None
    author: str | None = None
    tag: str | None = None
    source_system: str = "sharepoint"

    @model_validator(mode="after")
    def _require_locator(self) -> "SharePointIngestRequest":
        if not self.sharepoint_url and not (
            self.item_id and (self.drive_id or self.site_id)
        ):
            raise ValueError(
                "Provide 'sharepoint_url', or 'item_id' plus 'drive_id' or 'site_id'."
            )
        return self


class DatabaseIngestRequest(BaseModel):
    """Ingest rows from a SQL database via a single read-only ``SELECT``.

    Supply exactly one of ``table`` or ``query``. ``connection_string`` may be
    omitted to fall back to the ``DB_INGESTION_DSN`` environment variable.
    """

    connection_string: str | None = None
    query: str | None = None
    table: str | None = None
    max_rows: int | None = None
    tenant_id: str = "default"
    collection_id: str = "default"
    document_id: str = "default"
    document_date: str | None = None
    author: str | None = None
    tag: str | None = None
    source_system: str = "database"

    @model_validator(mode="after")
    def _require_query_xor_table(self) -> "DatabaseIngestRequest":
        if bool(self.query) == bool(self.table):
            raise ValueError("Provide exactly one of 'query' or 'table'.")
        return self


class IngestResponse(BaseModel):
    message: str
    chunks: int


class QuestionDomainItem(BaseModel):
    id: str
    name: str
    description: str
    retrieval_quality_focus: str
    sample_questions: list[str]


class QuestionDomainCatalogResponse(BaseModel):
    domains: list[QuestionDomainItem]
