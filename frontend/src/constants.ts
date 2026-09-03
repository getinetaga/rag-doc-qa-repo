/**
 * Application constants and configuration
 * Mirrors Streamlit configuration settings
 */

import { AppConfig, ThemeConfig } from "./types";

/**
 * API Configuration
 */
export const API_URL = "http://127.0.0.1:8000";
export const UPLOAD_TIMEOUT = 60000; // 60 seconds
export const QUESTION_TIMEOUT = 60000; // 60 seconds
export const HEALTH_CHECK_INTERVAL = 5000; // 5 seconds
export const MAX_FILE_SIZE = 209715200; // 200 MiB

/**
 * Supported file formats
 */
export const SUPPORTED_FORMATS = ["pdf", "docx", "txt", "png", "jpg", "jpeg", "bmp", "tiff", "tif", "webp", "gif"];
export const SUPPORTED_FORMATS_LABEL = "PDF, DOCX, TXT, PNG, JPG, JPEG, BMP, TIFF, WebP, GIF";

/**
 * Tenant and collection defaults
 */
export const DEFAULT_TENANT_ID = "default";
export const DEFAULT_COLLECTION_ID = "default";
export const DEFAULT_DOCUMENT_ID = "default";

/**
 * UI Labels and Placeholders
 */
export const LABELS = {
  APP_TITLE: "📚 RAG Document QA System",
  APP_SUBTITLE: "Upload documents and ask AI-powered questions",
  
  UPLOAD_SECTION_TITLE: "📤 Upload Document",
  UPLOAD_SECTION_DESC: "Upload a PDF, DOCX, TXT, or image file — or link a SharePoint file — to get started",
  UPLOAD_BUTTON: "🚀 Process Document",
  UPLOAD_PROCESSING: "Processing...",

  SHAREPOINT_URL_PLACEHOLDER: "Or paste a SharePoint file URL",
  SHAREPOINT_BUTTON: "🗂️ Process SharePoint File",
  SHAREPOINT_PROCESSING: "Fetching from SharePoint...",
  
  QUESTION_SECTION_TITLE: "💬 Ask Questions",
  QUESTION_PLACEHOLDER: "e.g., What is the main topic of this document?",
  QUESTION_BUTTON: "🔍 Get Answer",
  QUESTION_SEARCHING: "Searching...",
  QUESTION_CLEAR: "🗑️ Clear",
  
  HISTORY_TITLE: "📝 Question History",
  
  ABOUT_TITLE: "ℹ️ About",
  STATUS_TITLE: "🛠️ System Status",
  DOCUMENT_TITLE: "📄 Document",
};

/**
 * Messages
 */
export const MESSAGES = {
  // Success messages
  UPLOAD_SUCCESS: "Document processed successfully!",
  
  // Error messages
  NO_FILE_SELECTED: "Please select a file first.",
  NO_SHAREPOINT_URL: "Enter a SharePoint file URL first.",
  EMPTY_QUESTION: "Enter a question before requesting an answer.",
  NO_DOCUMENT_UPLOADED: "Please upload a document first.",
  
  // Status messages
  SELECT_FILE_MESSAGE: "Please upload a document first",
  READY_FOR_QUESTIONS: "✓ Document is ready for questions!",
  
  // API messages
  API_CONNECTION_ERROR: "Connection error. Make sure the FastAPI server is running on",
  API_ONLINE: "✅ API Server: Online",
  API_OFFLINE: "❌ API Server: Offline",
  API_ERROR: "❌ API Server: Error",
  
  DOCUMENT_LOADED: "✅ Document: Loaded",
  DOCUMENT_NOT_LOADED: "⚠️ Document: Not loaded",
};

/**
 * Color scheme
 * Matches Streamlit CSS colors
 */
export const COLORS = {
  PRIMARY: "#1E88E5",
  SUCCESS: "#D4EDDA",
  SUCCESS_TEXT: "#155724",
  SUCCESS_BORDER: "#C3E6CB",
  
  ERROR: "#F8D7DA",
  ERROR_TEXT: "#721C24",
  ERROR_BORDER: "#F5C6CB",
  
  INFO: "#D1ECF1",
  INFO_TEXT: "#0C5460",
  INFO_BORDER: "#BEE5EB",
  
  ANSWER_BG: "#F8F9FA",
  ANSWER_BORDER: "#1E88E5",
  
  BACKGROUND: "#F5F5F5",
  WHITE: "#FFFFFF",
  TEXT: "#333333",
  TEXT_LIGHT: "#666666",
  TEXT_GRAY: "#999999",
  BORDER: "#DDDDDD",
};

/**
 * Typography
 */
export const TYPOGRAPHY = {
  FONT_FAMILY: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
  FONT_SIZE_TITLE: "2.5rem",
  FONT_SIZE_HEADER: "1.5rem",
  FONT_SIZE_SUBTITLE: "1.1rem",
  FONT_SIZE_NORMAL: "1rem",
  FONT_SIZE_SMALL: "0.95rem",
  FONT_SIZE_TINY: "0.85rem",
};

/**
 * Spacing and Layout
 */
export const SPACING = {
  PADDING_SMALL: "12px",
  PADDING_NORMAL: "16px",
  PADDING_LARGE: "24px",
  
  MARGIN_SMALL: "8px",
  MARGIN_NORMAL: "16px",
  MARGIN_LARGE: "20px",
  
  BORDER_RADIUS: "6px",
  BORDER_RADIUS_LARGE: "8px",
};

/**
 * Animations
 */
export const ANIMATIONS = {
  TRANSITION_NORMAL: "0.3s",
  BALLOON_DURATION: "4s",
};

/**
 * Default app configuration
 */
export const DEFAULT_APP_CONFIG: AppConfig = {
  apiUrl: API_URL,
  uploadTimeout: UPLOAD_TIMEOUT,
  questionTimeout: QUESTION_TIMEOUT,
  maxFileSize: MAX_FILE_SIZE,
  supportedFormats: SUPPORTED_FORMATS,
  /**
   * Supported formats detail:
   * - Documents: PDF (pdfplumber), DOCX (python-docx), TXT (plain text)
   * - Images: PNG, JPG, JPEG, BMP, TIFF, WebP, GIF (OCR with pytesseract)
   */
  tenantId: DEFAULT_TENANT_ID,
  collectionId: DEFAULT_COLLECTION_ID,
  healthCheckInterval: HEALTH_CHECK_INTERVAL,
  enableDebug: false,
};

/**
 * Default theme configuration
 */
export const DEFAULT_THEME: ThemeConfig = {
  primaryColor: COLORS.PRIMARY,
  successColor: COLORS.SUCCESS,
  errorColor: COLORS.ERROR,
  infoColor: COLORS.INFO,
  backgroundColor: COLORS.BACKGROUND,
  textColor: COLORS.TEXT,
  borderRadius: SPACING.BORDER_RADIUS,
  fontFamily: TYPOGRAPHY.FONT_FAMILY,
};

/**
 * About section content
 */
export const ABOUT_CONTENT = `
This **RAG (Retrieval-Augmented Generation)** system allows you to:

1. 📤 **Upload** your documents
2. 🔍 **Ask** questions about them
3. 🤖 **Get** AI-powered answers

The system uses:
- **Sentence Transformers** for embeddings
- **pgvector** for vector search
- **OpenAI GPT** or **Hugging Face** for answer generation
`;

/**
 * Regular expressions
 */
export const REGEX = {
  DOCUMENT_ID_PATTERN: /[^A-Za-z0-9_-]+/g,
  WHITESPACE: /\s+/g,
};

/**
 * Debug configuration
 */
export const DEBUG = {
  LOG_API_CALLS: false,
  LOG_STATE_CHANGES: false,
  LOG_ERRORS: true,
  LOG_TIMINGS: false,
};

/**
 * Feature flags
 */
export const FEATURES = {
  ENABLE_BALLOONS: true,
  ENABLE_AUTO_SCROLL: true,
  ENABLE_HEALTH_CHECK: true,
  ENABLE_RESPONSE_CACHING: false,
  ENABLE_OFFLINE_MODE: false,
};
