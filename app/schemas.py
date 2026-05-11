"""Pydantic request/response schemas used by the RAG API and demo.

This module defines small, explicit schemas for the service API:
- `QuestionRequest` — request body containing the user's question.
- `AnswerResponse` — response body containing the model's answer.

Keeping these schemas minimal keeps the example app easy to extend
for additional metadata (e.g., provenance, confidence) in the future.
"""

from pydantic import BaseModel 
# BaseModel is used as the base class for defining the Pydantic models (schemas) for request and response 
# bodies in the FastAPI application. It provides data validation and serialization capabilities, ensuring that 
# incoming requests and outgoing responses conform to the defined structure.


class QuestionRequest(BaseModel):
    """Request body for asking a question.

    Attributes:
        question: The user's natural-language question as a string.
    """

    question: str


class AnswerResponse(BaseModel):
    """Response body returned by the RAG endpoint.

    Attributes:
        answer: The text answer produced by the model. The application
            currently returns a plain string; consider extending this
            schema to include `sources` or `confidence` if desired.
    """

    answer: str
