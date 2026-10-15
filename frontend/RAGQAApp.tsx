/**
 * RAG Document QA Application - Main Component
 * 
 * Complete TypeScript/React implementation of the Streamlit RAG QA system.
 * All functionality from streamlit_app.py has been migrated to TypeScript.
 * 
 * Features:
 * - Multi-user support with authentication
 * - Per-user document isolation via tenant_id
 * - In-memory API-key authentication with server-granted scopes
 * 
 * @see MIGRATION_COMPLETE.md for detailed migration guide
 */

import React, { useState, useEffect, useRef } from "react";
import { styles } from "./src/styles";
import { ChatMessage, DocumentState, ProcessStatus } from "./src/types";
import { formatTimestamp, deriveDocumentId, deriveDocumentIdFromUrl } from "./src/utils";
import LoginScreen from "./src/LoginScreen";
import {
  loginUser, logoutUser, getCurrentUser, getCurrentScope, getSessionGeneration,
  isCurrentSession, selectScope, subscribeSession, User, Scope,
} from "./src/auth";
import apiService from "./src/services";
import { API_URL } from "./src/constants";

// ── Balloons Animation Component ────────────────────────────────────────────

function Balloons({ active }: { active: boolean }) {
  if (!active) return null;

  const COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6", "#e67e22"];
  const balloons = Array.from({ length: 18 }, (_, i) => ({
    id: i,
    color: COLORS[i % COLORS.length],
    left: `${5 + (i * 5.5) % 90}%`,
    delay: `${(i * 0.12).toFixed(2)}s`,
    size: 28 + (i % 4) * 8,
  }));

  return (
    <div style={styles.balloonsOverlay} aria-hidden>
      <style>{`
        @keyframes float-up {
          0% {
            bottom: -80px;
            opacity: 1;
          }
          100% {
            bottom: 100vh;
            opacity: 0;
          }
        }
        .balloon {
          animation: float-up 4s ease-in infinite;
        }
      `}</style>
      {balloons.map((b) => (
        <div
          key={b.id}
          className="balloon"
          style={{
            position: "absolute",
            left: b.left,
            width: b.size,
            height: b.size * 1.2,
            backgroundColor: b.color,
            borderRadius: "50% 50% 50% 50% / 60% 60% 40% 40%",
            animationDelay: b.delay,
            bottom: "-80px",
          }}
        />
      ))}
    </div>
  );
}

// ── Main RAG QA App Component ────────────────────────────────────────────────

export default function RAGQAApp() {
  // Authentication State
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope | null>(null);

  // State Management
  const [document, setDocument] = useState<DocumentState>({
    uploaded: false,
    name: "",
    sizeKb: 0,
    id: "",
  });

  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [sharepointUrl, setSharePointUrl] = useState("");
  const [question, setQuestion] = useState("");
  const [processStatus, setProcessStatus] = useState<ProcessStatus | null>(null);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [apiStatus, setApiStatus] = useState<"online" | "offline" | "error">("offline");
  const [showBalloons, setShowBalloons] = useState(false);
  const [isAboutExpanded, setIsAboutExpanded] = useState(true);
  const [isSystemStatusExpanded, setIsSystemStatusExpanded] = useState(true);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const workRef = useRef(new AbortController());
  const balloonTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const resetWorkspace = () => {
    workRef.current.abort();
    workRef.current = new AbortController();
    clearTimeout(balloonTimerRef.current);
    setDocument({ uploaded: false, name: "", sizeKb: 0, id: "" });
    setChatHistory([]);
    setSelectedFile(null);
    setSharePointUrl("");
    setQuestion("");
    setProcessStatus(null);
    setQuestionError(null);
    setIsProcessing(false);
    setIsAsking(false);
    setShowBalloons(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  useEffect(() => {
    const unsubscribe = subscribeSession((message) => {
      resetWorkspace();
      setUser(getCurrentUser());
      setScope(getCurrentScope());
      setAuthError(message || null);
      setApiStatus("offline");
    });
    return () => {
      unsubscribe();
      workRef.current.abort();
      clearTimeout(balloonTimerRef.current);
    };
  }, []);

  // Check API Health
  useEffect(() => {
    if (!user) return;
    let active = true;
    const version = getSessionGeneration();
    const checkApiHealth = async () => {
      const online = await apiService.checkHealth();
      if (active && isCurrentSession(version)) setApiStatus(online ? "online" : "offline");
    };

    checkApiHealth();
    const interval = setInterval(checkApiHealth, 5000);
    return () => { active = false; clearInterval(interval); };
  }, [user, scope]);

  // Auto-scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  // Handle Login
  const handleLogin = async (key: string) => {
    try {
      await loginUser(key, API_URL);
    } catch {
      setAuthError("Unable to sign in. Check your individual API key and server connection.");
      throw new Error("Sign-in failed.");
    }
  };

  // Handle Logout
  const handleLogout = () => {
    logoutUser();
  };

  // If not authenticated, show login screen
  if (!user) {
    return <LoginScreen onLogin={handleLogin} authError={authError} />;
  }

  const canIngest = user.roles.includes("ingest");
  const canRead = user.roles.includes("read");
  const isAdmin = user.roles.includes("admin");

  // Handle File Selection
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      resetWorkspace();
      setSelectedFile(file);
      setSharePointUrl("");
      setDocument({ uploaded: false, name: "", sizeKb: 0, id: "" });
      setChatHistory([]);
      setProcessStatus(null);
      setQuestionError(null);
    }
  };

  // Process Document
  const handleProcessDocument = async () => {
    if (!canIngest || !scope || isProcessing) return;
    if (!selectedFile) {
      setProcessStatus({ type: "error", message: "Please select a file first." });
      return;
    }

    setIsProcessing(true);
    setDocument({ uploaded: false, name: "", sizeKb: 0, id: "" });
    setChatHistory([]);
    setProcessStatus({ type: "info", message: "Processing document. Queued uploads are checked until indexing completes." });
    const version = getSessionGeneration();
    const signal = workRef.current.signal;

    try {
      const documentId = deriveDocumentId(selectedFile.name);
      await apiService.uploadDocument(
        selectedFile, documentId, scope.tenant_id, scope.collection_id, signal
      );
      if (!isCurrentSession(version) || signal.aborted) return;
      setDocument({
        uploaded: true,
        name: selectedFile.name,
        sizeKb: selectedFile.size / 1024,
        id: documentId,
      });
      setChatHistory([]);
      setProcessStatus({ type: "success", message: "Document processed successfully!" });
      setShowBalloons(true);
      balloonTimerRef.current = setTimeout(() => setShowBalloons(false), 4000);
    } catch (error) {
      if (isCurrentSession(version) && !signal.aborted) setProcessStatus({
        type: "error",
        message: error instanceof Error ? error.message : "Document processing failed.",
      });
    } finally {
      if (isCurrentSession(version) && !signal.aborted) setIsProcessing(false);
    }
  };

  // Process a SharePoint file by URL (downloaded server-side via Microsoft Graph)
  const handleProcessSharePoint = async () => {
    if (!canIngest || !isAdmin || !scope || isProcessing) return;
    const url = sharepointUrl.trim();
    if (!url) {
      setProcessStatus({ type: "error", message: "Enter a SharePoint file URL first." });
      return;
    }

    setIsProcessing(true);
    setDocument({ uploaded: false, name: "", sizeKb: 0, id: "" });
    setChatHistory([]);
    setProcessStatus({ type: "info", message: "Processing SharePoint file. Waiting for indexing to complete." });
    const version = getSessionGeneration();
    const signal = workRef.current.signal;

    try {
      const documentId = deriveDocumentIdFromUrl(url);
      const data = await apiService.uploadSharePoint(
        url, documentId, scope.tenant_id, scope.collection_id, signal
      );
      if (!isCurrentSession(version) || signal.aborted) return;
      setSelectedFile(null);
      setDocument({
        uploaded: true,
        name: url.split("/").filter(Boolean).pop() || url,
        sizeKb: 0,
        id: documentId,
      });
      setChatHistory([]);
      setProcessStatus({
        type: "success",
        message: `SharePoint file indexed${data.chunks ? ` (${data.chunks} chunks)` : ""}!`,
      });
      setShowBalloons(true);
      balloonTimerRef.current = setTimeout(() => setShowBalloons(false), 4000);
    } catch (error) {
      if (isCurrentSession(version) && !signal.aborted) setProcessStatus({
        type: "error",
        message: error instanceof Error ? error.message : "SharePoint processing failed.",
      });
    } finally {
      if (isCurrentSession(version) && !signal.aborted) setIsProcessing(false);
    }
  };

  // Submit Question
  const handleSubmitQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canRead || !scope || isAsking) return;

    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setQuestionError("Please enter a question before requesting an answer.");
      return;
    }

    setIsAsking(true);
    setQuestionError(null);
    const version = getSessionGeneration();
    const signal = workRef.current.signal;

    try {
      const data = await apiService.askQuestion(
        trimmedQuestion, document.id || "default", scope.tenant_id, scope.collection_id, signal
      );
      if (!isCurrentSession(version) || signal.aborted) return;
      const answer = data.answer || "";
      setChatHistory((history) => [
        ...history,
        {
          question: trimmedQuestion,
          answer,
          timestamp: formatTimestamp(),
        },
      ]);
      setQuestion("");
    } catch (error) {
      if (isCurrentSession(version) && !signal.aborted) {
        setQuestionError(error instanceof Error ? error.message : "Question failed.");
      }
    } finally {
      if (isCurrentSession(version) && !signal.aborted) setIsAsking(false);
    }
  };

  // Clear Chat History
  const handleClearChat = () => {
    setChatHistory([]);
    setQuestionError(null);
  };

  // Render Component
  return (
    <div style={styles.container}>
      <Balloons active={showBalloons} />

      {/* Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>📚 RAG Document QA System</h1>
        <p style={styles.subtitle}>Upload documents and ask AI-powered questions</p>
      </header>

      <div style={styles.mainContent}>
        {/* Left Column - Document Upload */}
        <div style={styles.column}>
          <div style={styles.card}>
            <h2 style={styles.sectionTitle}>📤 Upload Document</h2>
            {canIngest ? <>
            <p style={styles.sectionDescription}>
              Upload a PDF, DOCX, TXT, or image file{isAdmin ? " — or link a SharePoint file" : ""} to get started
            </p>

            <div style={styles.fileInputWrapper}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.bmp,.tiff,.tif,.webp,.gif"
                onChange={handleFileChange}
                disabled={isProcessing}
                style={styles.fileInput}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isProcessing}
                style={styles.fileButton}
              >
                Choose File
              </button>
            </div>

            {selectedFile && (
              <>
                <div style={styles.infoBox}>
                  <strong>Selected file:</strong> {selectedFile.name}
                </div>
                <div style={styles.infoBox}>
                  <strong>File size:</strong> {(selectedFile.size / 1024).toFixed(2)} KB
                </div>

                <button
                  onClick={handleProcessDocument}
                  disabled={isProcessing}
                  style={{
                    ...styles.primaryButton,
                    opacity: isProcessing ? 0.6 : 1,
                    cursor: isProcessing ? "not-allowed" : "pointer",
                  }}
                >
                  {isProcessing ? "Processing..." : "🚀 Process Document"}
                </button>
              </>
            )}

            {isAdmin && <>
            <div style={{ margin: "16px 0 8px", color: "#999", fontSize: "0.85rem" }}>
              — or —
            </div>
            <input
              type="url"
              value={sharepointUrl}
              onChange={(e) => {
                resetWorkspace();
                setSharePointUrl(e.target.value);
              }}
              placeholder="Paste a SharePoint file URL"
              style={styles.questionInput}
              disabled={isProcessing}
            />
            {sharepointUrl.trim() && (
              <button
                onClick={handleProcessSharePoint}
                disabled={isProcessing}
                style={{
                  ...styles.primaryButton,
                  marginTop: "8px",
                  opacity: isProcessing ? 0.6 : 1,
                  cursor: isProcessing ? "not-allowed" : "pointer",
                }}
              >
                {isProcessing ? "Fetching from SharePoint..." : "🗂️ Process SharePoint File"}
              </button>
            )}
            </>}
            </> : (
              <div style={styles.infoBox}>
                {canRead
                  ? "Read-only access. Ask questions about documents already indexed in your selected project."
                  : "Your key does not have permission to ingest documents."}
                {canRead && <>
                <label htmlFor="existing-document" style={{ display: "block", marginTop: "8px" }}>
                  Document ID (optional)
                </label>
                <input
                  id="existing-document"
                  value={document.id}
                  onChange={(e) => {
                    resetWorkspace();
                    setDocument({ uploaded: false, name: "", sizeKb: 0, id: e.target.value });
                  }}
                  placeholder="Leave blank to search the project"
                  style={styles.questionInput}
                />
                </>}
              </div>
            )}

            {isProcessing && (
              <button style={styles.secondaryButton} onClick={() => {
                resetWorkspace();
                setProcessStatus({ type: "info", message: "Stopped waiting. An accepted job may still finish on the server." });
              }}>
                Cancel waiting
              </button>
            )}

            {processStatus && (
              <div
                style={
                  processStatus.type === "success"
                    ? styles.successBox
                    : processStatus.type === "error"
                    ? styles.errorBox
                    : styles.infoBox
                }
              >
                {processStatus.type === "success" ? "✅" : processStatus.type === "info" ? "ℹ️" : "❌"} {processStatus.message}
              </div>
            )}

            {document.uploaded && (
              <div style={styles.successBox}>
                ✓ Document is ready for questions!
              </div>
            )}
          </div>
        </div>

        {/* Right Column - Ask Questions */}
        <div style={styles.column}>
          <div style={styles.card}>
            <h2 style={styles.sectionTitle}>💬 Ask Questions</h2>

            {!canRead ? (
              <div style={styles.infoBox}>Your key does not have permission to ask questions.</div>
            ) : !document.uploaded && canIngest ? (
              <div style={styles.infoBox}>
                ⚠️ Please upload a document first
              </div>
            ) : (
              <>
                <form onSubmit={handleSubmitQuestion} style={styles.form}>
                  <input
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder="e.g., What is the main topic of this document?"
                    style={styles.questionInput}
                    disabled={isAsking}
                  />
                  <div style={styles.buttonGroup}>
                    <button
                      type="submit"
                      disabled={isAsking}
                      style={{
                        ...styles.primaryButton,
                        opacity: isAsking ? 0.6 : 1,
                        cursor: isAsking ? "not-allowed" : "pointer",
                        flex: 3,
                      }}
                    >
                      {isAsking ? "Searching..." : "🔍 Get Answer"}
                    </button>
                    <button
                      type="button"
                      onClick={handleClearChat}
                      style={{
                        ...styles.secondaryButton,
                        flex: 1,
                      }}
                    >
                      🗑️ Clear
                    </button>
                  </div>
                </form>

                {questionError && (
                  <div style={styles.errorBox}>
                    ❌ {questionError}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Chat History */}
      {chatHistory.length > 0 && (
        <div style={styles.historySection}>
          <h2 style={styles.sectionTitle}>📝 Question History</h2>
          <div style={styles.chatHistoryContainer}>
            {[...chatHistory].reverse().map((chat, idx) => (
              <div key={idx} style={styles.chatMessage}>
                <div style={styles.questionText}>
                  <strong>Q{chatHistory.length - idx}:</strong> {chat.question}
                </div>
                <div style={styles.answerBox}>
                  <strong>Answer:</strong>
                  <p>{chat.answer}</p>
                </div>
                <div style={styles.timestamp}>⏰ {chat.timestamp}</div>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
        </div>
      )}

      {/* Sidebar Toggle Button */}
      <button
        onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        style={{
          position: "fixed" as const,
          right: "15px",
          top: "15px",
          width: "36px",
          height: "36px",
          background: "#3498db",
          color: "white",
          border: "none",
          borderRadius: "6px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "1.1rem",
          zIndex: 1001,
          transition: "all 0.3s ease",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "#2980b9";
          e.currentTarget.style.transform = "scale(1.1)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "#3498db";
          e.currentTarget.style.transform = "scale(1)";
        }}
        title={isSidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
        aria-label="Toggle sidebar"
      >
        {isSidebarCollapsed ? "◀" : "▶"}
      </button>

      {/* Sidebar - Status Information */}
      <aside style={{
        ...styles.sidebar,
        transform: isSidebarCollapsed ? "translateX(calc(100% + 20px))" : "translateX(0)",
        opacity: isSidebarCollapsed ? 0 : 1,
        pointerEvents: isSidebarCollapsed ? "none" : "auto",
        transition: "transform 0.3s ease, opacity 0.3s ease",
      } as React.CSSProperties}>
        {/* User Info Card */}
        <div style={styles.sidebarCard}>
          <h3 style={styles.sidebarTitle}>👤 User</h3>
          <p style={styles.sidebarText}><strong>User:</strong> {user.user_id}</p>
          <p style={{ ...styles.sidebarText, fontSize: "0.85rem", color: "#666", marginBottom: "12px" }}>
            <strong>Roles:</strong> {user.roles.join(", ")}
          </p>
          <label htmlFor="project-scope" style={styles.sidebarText}>Tenant / project</label>
          <select
            id="project-scope"
            style={{ ...styles.questionInput, marginBottom: "12px" }}
            value={user.scopes.findIndex((grant) =>
              grant.tenant_id === scope?.tenant_id && grant.collection_id === scope?.collection_id)}
            onChange={(e) => selectScope(user.scopes[Number(e.target.value)])}
            disabled={user.scopes.length < 2}
          >
            {user.scopes.map((grant, index) => (
              <option key={index} value={index}>{grant.tenant_id} / {grant.collection_id}</option>
            ))}
          </select>
          <button
            onClick={handleLogout}
            style={{
              width: "100%",
              padding: "8px 12px",
              background: "#e74c3c",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.9rem",
              fontWeight: "bold",
              transition: "all 0.3s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#c0392b";
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#e74c3c";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            🚪 Logout
          </button>
        </div>

        <div style={styles.sidebarCard}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", userSelect: "none" }} onClick={() => setIsAboutExpanded(!isAboutExpanded)}>
            <h3 style={styles.sidebarTitle}>ℹ️ About</h3>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsAboutExpanded(!isAboutExpanded);
              }}
              style={{
                background: "none",
                border: "none",
                fontSize: "1.2rem",
                cursor: "pointer",
                padding: "0 8px",
                transition: "transform 0.3s ease",
                transform: isAboutExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
              aria-label="Toggle About section"
            >
              ▼
            </button>
          </div>
          <div
            style={{
              maxHeight: isAboutExpanded ? "500px" : "0px",
              overflow: "hidden",
              transition: "max-height 0.3s ease, opacity 0.3s ease",
              opacity: isAboutExpanded ? 1 : 0,
            }}
          >
            <p style={styles.sidebarText}>
              This <strong>RAG (Retrieval-Augmented Generation)</strong> system allows you to:
            </p>
            <ul style={styles.list}>
              <li>📤 <strong>Upload</strong> your documents</li>
              <li>🔍 <strong>Ask</strong> questions about them</li>
              <li>🤖 <strong>Get</strong> AI-powered answers</li>
            </ul>
            <p style={styles.sidebarText}>The system uses:</p>
            <ul style={styles.list}>
              <li><strong>Sentence Transformers</strong> for embeddings</li>
              <li><strong>pgvector</strong> for vector search</li>
              <li><strong>OpenAI GPT</strong> for answer generation</li>
            </ul>
          </div>
        </div>

        <div style={styles.sidebarCard}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", userSelect: "none" }} onClick={() => setIsSystemStatusExpanded(!isSystemStatusExpanded)}>
            <h3 style={styles.sidebarTitle}>🛠️ System Status</h3>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsSystemStatusExpanded(!isSystemStatusExpanded);
              }}
              style={{
                background: "none",
                border: "none",
                fontSize: "1.2rem",
                cursor: "pointer",
                padding: "0 8px",
                transition: "transform 0.3s ease",
                transform: isSystemStatusExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
              aria-label="Toggle System Status section"
            >
              ▼
            </button>
          </div>
          <div
            style={{
              maxHeight: isSystemStatusExpanded ? "500px" : "0px",
              overflow: "hidden",
              transition: "max-height 0.3s ease, opacity 0.3s ease",
              opacity: isSystemStatusExpanded ? 1 : 0,
            }}
          >
            <div style={{
              ...styles.statusIndicator,
              backgroundColor: apiStatus === "online" ? "#d4edda" : apiStatus === "error" ? "#f8d7da" : "#e2e3e5",
            }}>
              {apiStatus === "online" ? "✅" : "❌"} API Server:{" "}
              {apiStatus === "online" ? "Online" : apiStatus === "error" ? "Error" : "Offline"}
            </div>

            <div style={{
              ...styles.statusIndicator,
              backgroundColor: document.uploaded ? "#d4edda" : "#e2e3e5",
            }}>
              {document.uploaded ? "✅" : "⚠️"} Document:{" "}
              {document.uploaded ? "Loaded" : "Not loaded"}
            </div>
          </div>
        </div>

        {document.uploaded && document.name && (
          <div style={styles.sidebarCard}>
            <h3 style={styles.sidebarTitle}>📄 Document</h3>
            <p><strong>Name:</strong> {document.name}</p>
            <p><strong>Size:</strong> {document.sizeKb.toFixed(2)} KB</p>
          </div>
        )}
      </aside>
    </div>
  );
}
