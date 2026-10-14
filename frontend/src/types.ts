/**
 * Type definitions for RAG Document QA Application
 * Mirrors Streamlit session state and data structures
 */

/**
 * Represents a single chat message in the conversation
 */
export interface ChatMessage {
  question: string;
  answer: string;
  timestamp: string;
}

/**
 * Status information for document processing or answer generation
 */
export interface ProcessStatus {
  type: "success" | "error" | "info";
  message: string;
}

/**
 * Document upload state
 */
export interface DocumentState {
  uploaded: boolean;
  name: string;
  sizeKb: number;
  id: string;
}

/**
 * API response from upload endpoint
 */
export interface UploadResponse {
  status: "success" | "error";
  document_id: string;
  chunks_indexed?: number;
  embedding_model?: string;
  processing_time_seconds?: number;
  error?: string;
}

/**
 * Request body for the SharePoint ingestion endpoint (/upload-sharepoint).
 * Provide either `sharepoint_url`, or `item_id` plus `drive_id` / `site_id`.
 */
export interface SharePointIngestRequest {
  sharepoint_url?: string;
  site_id?: string;
  drive_id?: string;
  item_id?: string;
  tenant_id: string;
  collection_id: string;
  document_id: string;
  source_system?: string;
}

/**
 * API response from ask endpoint
 */
export interface AskResponse {
  answer: string;
  references?: string[];
  retrieval_time_ms?: number;
  generation_time_ms?: number;
  chunks_used?: number;
  error?: string;
}

/**
 * API health check response
 */
export interface HealthCheckResponse {
  status: "online" | "offline" | "error";
}

/**
 * Application state snapshot
 */
export interface AppState {
  document: DocumentState;
  chatHistory: ChatMessage[];
  selectedFile: File | null;
  question: string;
  processStatus: ProcessStatus | null;
  questionError: string | null;
  isProcessing: boolean;
  isAsking: boolean;
  apiStatus: "online" | "offline" | "error";
}

/**
 * Configuration for the application
 */
export interface AppConfig {
  apiUrl: string;
  uploadTimeout: number;
  questionTimeout: number;
  maxFileSize: number;
  supportedFormats: string[];
  tenantId: string;
  collectionId: string;
  healthCheckInterval: number;
  enableDebug: boolean;
}

/**
 * Theme configuration
 */
export interface ThemeConfig {
  primaryColor: string;
  successColor: string;
  errorColor: string;
  infoColor: string;
  backgroundColor: string;
  textColor: string;
  borderRadius: string;
  fontFamily: string;
}

/**
 * Button properties
 */
export interface ButtonProps {
  onClick?: () => void | Promise<void>;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger";
  loading?: boolean;
  children?: React.ReactNode;
}

/**
 * Sidebar section properties
 */
export interface SidebarSection {
  title: string;
  icon: string;
  content: string | React.ReactNode;
}

/**
 * File upload validation result
 */
export interface FileValidationResult {
  valid: boolean;
  error?: string;
  file?: File;
}

/**
 * Request metadata
 */
export interface RequestMetadata {
  tenantId: string;
  collectionId: string;
  documentId: string;
  userId?: string;
  timestamp?: number;
}

/**
 * Error details
 */
export interface ErrorDetails {
  message: string;
  code?: string;
  statusCode?: number;
  timestamp: number;
}
