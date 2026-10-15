import { UploadResponse, AskResponse, IngestionJob } from "./types";
import { API_URL } from "./constants";
import {
  authenticatedFetch, getCurrentScope, getCurrentUser,
  getSessionGeneration, isCurrentSession,
} from "./auth";

interface ApiConfig { apiUrl?: string; timeout?: number; }
type Metadata = { document_date?: string; author?: string; tag?: string; source_system?: string };

class ApiService {
  private apiUrl: string;
  private timeout: number;

  constructor(config?: ApiConfig) {
    this.apiUrl = config?.apiUrl || API_URL;
    this.timeout = config?.timeout || 60000;
  }

  private scope(tenantId?: string, collectionId?: string) {
    const grant = getCurrentScope();
    if (!grant || (tenantId !== undefined && tenantId !== grant.tenant_id) ||
        (collectionId !== undefined && collectionId !== grant.collection_id)) {
      throw new Error("Select an authorized tenant/project.");
    }
    return grant;
  }

  private requireRole(role: "read" | "ingest" | "admin") {
    const roles = getCurrentUser()?.roles || [];
    if (!roles.includes(role)) {
      throw new Error(`This action requires the ${role} role.`);
    }
  }

  private async request<T>(path: string, init: RequestInit = {}, timeout = this.timeout): Promise<T> {
    const version = getSessionGeneration();
    const response = await authenticatedFetch(`${this.apiUrl}${path}`, init, timeout);
    if (!response.ok) {
      if (response.status === 503) {
        throw new Error("The server is busy or temporarily unavailable. Please retry shortly.");
      }
      // Do not reflect server bodies, which may contain operator-only details.
      throw new Error(`Request failed (${response.status}). Please check your permissions and try again.`);
    }
    const data = await response.json();
    if (!isCurrentSession(version) || init.signal?.aborted) throw new Error("Request cancelled.");
    return data;
  }

  async uploadDocument(
    file: File, documentId: string, tenantId?: string, collectionId?: string,
    signal?: AbortSignal, metadata: Metadata = {}
  ): Promise<UploadResponse> {
    this.requireRole("ingest");
    const version = getSessionGeneration();
    const grant = this.scope(tenantId, collectionId);
    const formData = new FormData();
    formData.append("file", file);
    Object.entries({ ...metadata, ...grant, document_id: documentId }).forEach(
      ([key, value]) => { if (value !== undefined) formData.append(key, value); }
    );
    const data = await this.request<UploadResponse>("/upload", {
      method: "POST", body: formData, signal,
    });
    return this.finishIngestion(data, version, signal);
  }

  async uploadSharePoint(
    sharepointUrl: string, documentId: string, tenantId?: string, collectionId?: string,
    signal?: AbortSignal, metadata: Metadata = {}
  ): Promise<UploadResponse> {
    this.requireRole("ingest");
    this.requireRole("admin");
    const version = getSessionGeneration();
    const data = await this.request<UploadResponse>("/upload-sharepoint", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal,
      body: JSON.stringify({
        ...metadata, ...this.scope(tenantId, collectionId),
        sharepoint_url: sharepointUrl, document_id: documentId,
      }),
    });
    return this.finishIngestion(data, version, signal);
  }

  private async finishIngestion(
    data: UploadResponse, version: number, signal?: AbortSignal
  ): Promise<UploadResponse> {
    if (!isCurrentSession(version) || signal?.aborted) throw new Error("Processing cancelled.");
    if (data.status === "error") throw new Error("Document processing failed. Please try again.");
    if (data.status !== "queued") return data;
    if (!data.job_id) throw new Error("The server did not return an ingestion job ID.");
    const deadline = Date.now() + 300000;
    while (Date.now() < deadline) {
      if (!isCurrentSession(version) || signal?.aborted) throw new Error("Processing cancelled.");
      const job = await this.request<IngestionJob>(
        `/ingestion-jobs/${encodeURIComponent(data.job_id)}`, { signal },
        Math.min(10000, deadline - Date.now())
      );
      if (!isCurrentSession(version)) throw new Error("Processing cancelled.");
      if (job.status === "completed") return job.result || { status: "success", document_id: data.document_id };
      if (job.status === "failed") throw new Error("Document processing failed. Please try again or contact an administrator.");
      if (job.status !== "queued" && job.status !== "running") throw new Error("Unexpected ingestion job status.");
      await new Promise<void>((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(new Error("Processing cancelled.")); };
        const timer = setTimeout(() => {
          signal?.removeEventListener("abort", abort);
          resolve();
        }, Math.min(1500, Math.max(0, deadline - Date.now())));
        signal?.addEventListener("abort", abort, { once: true });
        if (signal?.aborted) abort();
      });
    }
    throw new Error("Document processing timed out after five minutes. It may still finish on the server; check before retrying.");
  }

  async askQuestion(
    question: string, documentId: string, tenantId?: string, collectionId?: string,
    signal?: AbortSignal, metadata: Metadata = {}
  ): Promise<AskResponse> {
    this.requireRole("read");
    return this.request<AskResponse>("/ask", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal,
      body: JSON.stringify({
        ...metadata, ...this.scope(tenantId, collectionId), question, document_id: documentId,
      }),
    });
  }

  async checkHealth(): Promise<boolean> {
    try { await this.request("/session", {}, 2000); return true; }
    catch { return false; }
  }

  async getDocs(): Promise<string> {
    const version = getSessionGeneration();
    const response = await authenticatedFetch(`${this.apiUrl}/docs`, {}, this.timeout);
    if (!response.ok) throw new Error("Failed to fetch API docs.");
    const text = await response.text();
    if (!isCurrentSession(version)) throw new Error("Request cancelled.");
    return text;
  }

  setApiUrl(url: string): void { this.apiUrl = url; }
  setTimeout(timeout: number): void { this.timeout = timeout; }
}

export default new ApiService();
