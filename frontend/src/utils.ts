/**
 * Utility functions for RAG Document QA Application
 * Mirrors Streamlit utility functions
 */

import { REGEX, SUPPORTED_FORMATS, MAX_FILE_SIZE } from "./constants";
import { FileValidationResult, DocumentState } from "./types";

/**
 * Derives a document ID from a filename
 * Converts to slug format (lowercase, replace special chars with underscore)
 * 
 * Mirrors Streamlit: _derive_document_id()
 * 
 * @param filename - The original filename
 * @returns The derived document ID
 */
export function deriveDocumentId(filename: string): string {
  if (!filename) return "document";

  // Extract stem (filename without extension)
  const stem = filename.split(".")[0];

  // Convert to slug: replace special chars with underscore, remove leading/trailing underscores
  const slug = stem
    .replace(REGEX.DOCUMENT_ID_PATTERN, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();

  return slug || "document";
}

/**
 * Derives a document ID from a document URL (Google Docs / SharePoint link)
 * by slugifying the last non-empty path segment.
 *
 * @param url - The document URL
 * @returns The derived document ID
 */
export function deriveDocumentIdFromUrl(url: string): string {
  if (!url) return "document";

  let path = url;
  try {
    path = new URL(url).pathname;
  } catch {
    // Not a fully-qualified URL — fall back to the raw string.
  }

  const lastSegment = path.split("/").filter(Boolean).pop() ?? "";
  return deriveDocumentId(decodeURIComponent(lastSegment));
}

/**
 * Formats current time in HH:MM:SS format
 * Mirrors Streamlit: time.strftime("%H:%M:%S")
 * 
 * @param date - Optional date to format (defaults to now)
 * @returns Formatted time string
 */
export function formatTimestamp(date: Date = new Date()): string {
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/**
 * Formats file size to human-readable format
 * 
 * @param bytes - Size in bytes
 * @param decimals - Number of decimal places
 * @returns Formatted size string (e.g., "2.50 KB")
 */
export function formatFileSize(bytes: number, decimals: number = 2): string {
  if (bytes === 0) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
}

/**
 * Validates a file for upload
 * Checks format, size, and basic validity
 * 
 * @param file - File to validate
 * @returns Validation result with error details if invalid
 */
export function validateFile(file: File): FileValidationResult {
  if (!file) {
    return {
      valid: false,
      error: "No file selected",
    };
  }

  // Check file extension
  const fileExtension = file.name.split(".").pop()?.toLowerCase();
  if (!fileExtension || !SUPPORTED_FORMATS.includes(fileExtension)) {
    return {
      valid: false,
      error: `Invalid file format. Supported: ${SUPPORTED_FORMATS.join(", ")}`,
    };
  }

  // Check file size
  if (file.size > MAX_FILE_SIZE) {
    return {
      valid: false,
      error: `File too large. Maximum size: ${formatFileSize(MAX_FILE_SIZE)}`,
    };
  }

  return {
    valid: true,
    file,
  };
}

/**
 * Creates initial document state
 * 
 * @returns Empty DocumentState
 */
export function createEmptyDocumentState(): DocumentState {
  return {
    uploaded: false,
    name: "",
    sizeKb: 0,
    id: "",
  };
}

/**
 * Resets document state
 * Called when file changes or upload fails
 * 
 * @param documentState - Current document state
 * @returns Reset document state with chat history cleared
 */
export function resetDocumentState(documentState: DocumentState): DocumentState {
  return {
    ...documentState,
    uploaded: false,
    name: "",
    sizeKb: 0,
    id: "",
  };
}

/**
 * Debounces a function
 * 
 * @param func - Function to debounce
 * @param delay - Delay in milliseconds
 * @returns Debounced function
 */
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout>;

  return function (...args: Parameters<T>) {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => {
      func(...args);
    }, delay);
  };
}

/**
 * Throttles a function
 * 
 * @param func - Function to throttle
 * @param limit - Time limit in milliseconds
 * @returns Throttled function
 */
export function throttle<T extends (...args: any[]) => any>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle: boolean;

  return function (...args: Parameters<T>) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

/**
 * Sanitizes error message for display
 * 
 * @param error - Error object or message
 * @returns User-friendly error message
 */
export function sanitizeErrorMessage(error: any): string {
  if (typeof error === "string") return error;
  if (error?.message) return error.message;
  if (error?.response?.data?.detail) return error.response.data.detail;
  if (error?.response?.text) return error.response.text;
  return "An unexpected error occurred";
}

/**
 * Checks if running in debug mode
 * 
 * @returns True if debug is enabled
 */
export function isDebugMode(): boolean {
  // Vite injects `import.meta.env`; cast avoids needing the vite/client types.
  try {
    return (import.meta as any)?.env?.DEV === true;
  } catch {
    return false;
  }
}

/**
 * Logs message if debug mode is enabled
 * 
 * @param message - Log message
 * @param data - Optional data to log
 */
export function debugLog(message: string, data?: any): void {
  if (isDebugMode()) {
    console.log(`[RAG Debug] ${message}`, data);
  }
}

/**
 * Logs error if debug mode is enabled
 * 
 * @param message - Error message
 * @param error - Error object
 */
export function debugError(message: string, error?: any): void {
  if (isDebugMode()) {
    console.error(`[RAG Error] ${message}`, error);
  }
}

/**
 * Gets initialization data from localStorage
 * 
 * @param key - Local storage key
 * @param defaultValue - Default value if not found
 * @returns Stored value or default
 */
export function getFromStorage<T>(key: string, defaultValue: T): T {
  try {
    const item = localStorage.getItem(key);
    return item ? JSON.parse(item) : defaultValue;
  } catch {
    return defaultValue;
  }
}

/**
 * Saves data to localStorage
 * 
 * @param key - Local storage key
 * @param value - Value to store
 */
export function saveToStorage<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    debugError("Failed to save to localStorage", error);
  }
}

/**
 * Removes item from localStorage
 * 
 * @param key - Local storage key
 */
export function removeFromStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    debugError("Failed to remove from localStorage", error);
  }
}

/**
 * Creates a delay promise
 * 
 * @param ms - Milliseconds to delay
 * @returns Promise that resolves after delay
 */
export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Truncates text to specified length
 * 
 * @param text - Text to truncate
 * @param length - Max length
 * @param suffix - Suffix to add (default "...")
 * @returns Truncated text
 */
export function truncateText(
  text: string,
  length: number,
  suffix: string = "..."
): string {
  if (text.length <= length) return text;
  return text.slice(0, length) + suffix;
}

/**
 * Extracts error code from error response
 * 
 * @param error - Error object
 * @returns Error code or "UNKNOWN_ERROR"
 */
export function getErrorCode(error: any): string {
  return (
    error?.code ||
    error?.response?.status ||
    error?.statusCode ||
    "UNKNOWN_ERROR"
  );
}

/**
 * Checks if error is a network error
 * 
 * @param error - Error object
 * @returns True if network error
 */
export function isNetworkError(error: any): boolean {
  return (
    !error?.response ||
    error?.message?.includes("fetch") ||
    error?.message?.includes("network")
  );
}

/**
 * Checks if error is a timeout
 * 
 * @param error - Error object
 * @returns True if timeout error
 */
export function isTimeoutError(error: any): boolean {
  return (
    error?.message?.includes("timeout") ||
    error?.code === "ECONNABORTED" ||
    error?.name === "AbortError"
  );
}

/**
 * Generates a unique ID
 * 
 * @returns Unique identifier string
 */
export function generateId(): string {
  return Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
}

/**
 * Converts markdown-like text to plain text
 * Removes bold, italic markers
 * 
 * @param text - Text to convert
 * @returns Plain text
 */
export function stripMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1") // **bold** → bold
    .replace(/\*(.+?)\*/g, "$1") // *italic* → italic
    .replace(/__(.+?)__/g, "$1") // __bold__ → bold
    .replace(/_(.+?)_/g, "$1") // _italic_ → italic
    .replace(/\[(.+?)\]\(.+?\)/g, "$1"); // [link](url) → link
}

/**
 * Highlights keywords in text
 * 
 * @param text - Text to highlight
 * @param keywords - Keywords to highlight
 * @returns Text with highlighted keywords (wrapped in <mark>)
 */
export function highlightKeywords(text: string, keywords: string[]): string {
  let result = text;
  for (const keyword of keywords) {
    const regex = new RegExp(`\\b${keyword}\\b`, "gi");
    result = result.replace(regex, `<mark>$&</mark>`);
  }
  return result;
}

/**
 * Validates email format
 * 
 * @param email - Email to validate
 * @returns True if valid email
 */
export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

/**
 * Converts seconds to readable time format
 * 
 * @param seconds - Seconds
 * @returns Formatted time string
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}
