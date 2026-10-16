"""Allowlisted ingestion failures safe to return without exception details."""

ERRORS = {
    "ocr_unavailable": (503, "Image text extraction requires Pillow, pytesseract and the Tesseract OCR engine. Choose AI visual description instead, or ask an operator to configure OCR."),
    "image_invalid": (422, "Upload a valid single-frame image. Animated images and multi-page TIFFs are not supported for visual description."),
    "image_too_large": (413, "AI visual description supports images up to 20 MiB and 25 million pixels."),
    "image_description_disabled": (503, "AI visual description is not enabled on this server."),
    "image_description_busy": (503, "AI processing is busy. Please retry shortly."),
    "image_description_failed": (502, "AI visual description failed. Please retry or contact an operator."),
    "image_description_empty": (422, "The AI service did not return a usable image description."),
}


class IngestionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        self.status_code, self.public_message = ERRORS[code]
        super().__init__(self.public_message)
