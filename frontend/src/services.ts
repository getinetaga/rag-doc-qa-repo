/**
 * API Service for RAG Document QA Application
 * Handles all HTTP communication with the FastAPI backend
 */

import { UploadResponse, AskResponse, SharePointIngestRequest } from "./types";
import { DEFAULT_TENANT_ID, DEFAULT_COLLECTION_ID, API_URL } from "./constants";
import { debugLog, debugError } from "./utils";

/**
 * Interface for API configuration
 */
interface ApiConfig {
  apiUrl?: string;
  timeout?: number;
}

/**
 * API Service class
 * Provides methods for uploading documents and asking questions
 */
class ApiService {
  private apiUrl: string;
  private timeout: number;

  constructor(config?: ApiConfig) {
    this.apiUrl = config?.apiUrl || API_URL;
    this.timeout = config?.timeout || 60000;
  }

  /**
   * Uploads a document to the backend
   * 
   * @param file - File to upload
   * @param documentId - Document identifier
 * @param userId - User identifier (maps to tenant_id for document isolation)
 * @param collectionId - Collection identifier (default: "default")
 * @returns Upload response with document ID and chunk count
 */
  async uploadDocument(
    file: File,
    documentId: string,
    userId: string = DEFAULT_TENANT_ID,
    collectionId: string = DEFAULT_COLLECTION_ID
  ): Promise<UploadResponse> {
    debugLog("Uploading document", {
      fileName: file.name,
      fileSize: file.size,
      documentId,
      userId,
      collectionId,
    });

    const formData = new FormData();
    formData.append("file", file);
    formData.append("tenant_id", userId);  // Use userId as tenant_id for multi-user isolation
    formData.append("collection_id", collectionId);
    formData.append("document_id", documentId);

    try {
      const response = await fetch(`${this.apiUrl}/upload`, {
        method: "POST",
        body: formData,
        signal: AbortSignal.timeout(this.timeout),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Upload failed: ${errorText}`);
      }

      const data: UploadResponse = await response.json();
      debugLog("Document uploaded successfully", data);
      return data;
    } catch (error) {
      debugError("Document upload error", error);
      throw error;
    }
  }

  /**
   * Ingests a SharePoint / OneDrive-for-Business file via the backend
   * (`/upload-sharepoint`), which downloads it through Microsoft Graph and
   * indexes it like a direct upload.
   *
   * @param sharepointUrl - Shareable link to the SharePoint file
   * @param documentId - Document identifier
   * @param userId - User identifier (maps to tenant_id for document isolation)
   * @param collectionId - Collection identifier (default: "default")
   * @returns Upload response with document ID and chunk count
   */
  async uploadSharePoint(
    sharepointUrl: string,
    documentId: string,
    userId: string = DEFAULT_TENANT_ID,
    collectionId: string = DEFAULT_COLLECTION_ID
  ): Promise<UploadResponse> {
    debugLog("Ingesting SharePoint file", {
      sharepointUrl,
      documentId,
      userId,
      collectionId,
    });

    const payload: SharePointIngestRequest = {
      sharepoint_url: sharepointUrl,
      tenant_id: userId,
      collection_id: collectionId,
      document_id: documentId,
    };

    try {
      const response = await fetch(`${this.apiUrl}/upload-sharepoint`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(this.timeout),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`SharePoint ingestion failed: ${errorText}`);
      }

      const data: UploadResponse = await response.json();
      debugLog("SharePoint file ingested successfully", data);
      return data;
    } catch (error) {
      debugError("SharePoint ingestion error", error);
      throw error;
    }
  }

  /**
   * Asks a question about an uploaded document
   *
   * @param question - The question to ask
   * @param documentId - Document identifier
   * @param userId - User identifier (maps to tenant_id for document isolation)
   * @param collectionId - Collection identifier (default: "default")
   * @returns Answer response with answer text and references
   */
  async askQuestion(
    question: string,
    documentId: string,
    userId: string = DEFAULT_TENANT_ID,
    collectionId: string = DEFAULT_COLLECTION_ID
  ): Promise<AskResponse> {
    debugLog("Asking question", {
      question,
      documentId,
      userId,
      collectionId,
    });

    try {
      const response = await fetch(`${this.apiUrl}/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question,
          tenant_id: userId,  // Use userId as tenant_id for multi-user isolation
          collection_id: collectionId,
          document_id: documentId,
        }),
        signal: AbortSignal.timeout(this.timeout),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Question failed: ${errorText}`);
      }

      const data: AskResponse = await response.json();
      debugLog("Answer received", data);
      return data;
    } catch (error) {
      debugError("Question error", error);
      throw error;
    }
  }

  /**
   * Checks if the API is available
   * 
   * @returns True if API is online
   */
  async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/docs`, {
        signal: AbortSignal.timeout(2000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Gets API documentation
   * 
   * @returns API documentation
   */
  async getDocs(): Promise<any> {
    try {
      const response = await fetch(`${this.apiUrl}/docs`, {
        signal: AbortSignal.timeout(this.timeout),
      });

      if (!response.ok) {
        throw new Error("Failed to fetch API docs");
      }

      return await response.json();
    } catch (error) {
      debugError("Failed to get API docs", error);
      throw error;
    }
  }

  /**
   * Updates the API URL
   * 
   * @param url - New API URL
   */
  setApiUrl(url: string): void {
    this.apiUrl = url;
    debugLog("API URL updated", url);
  }

  /**
   * Updates the request timeout
   * 
   * @param timeout - New timeout in milliseconds
   */
  setTimeout(timeout: number): void {
    this.timeout = timeout;
    debugLog("Timeout updated", timeout);
  }
}

/**
 * Singleton instance of ApiService
 */
const apiService = new ApiService();

export default apiService;
