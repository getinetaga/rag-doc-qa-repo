/**
 * RAG Document QA Application - Main Component
 * 
 * Complete TypeScript/React implementation of the Streamlit RAG QA system.
 * All functionality from streamlit_app.py has been migrated to TypeScript.
 * 
 * Features:
 * - Multi-user support with authentication
 * - Per-user document isolation via tenant_id
 * - Session-based login with localStorage persistence
 * 
 * @see MIGRATION_COMPLETE.md for detailed migration guide
 */

import React, { useState, useEffect, useRef } from "react";
import { styles } from "./src/styles";
import { ChatMessage, DocumentState, ProcessStatus } from "./src/types";
import { formatTimestamp, deriveDocumentId, deriveDocumentIdFromUrl } from "./src/utils";
import LoginScreen from "./src/LoginScreen";
import { loginUser, logoutUser, loadSession, User } from "./src/auth";

const API_URL = "http://127.0.0.1:8000";

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

  // Load user session on mount
  useEffect(() => {
    const savedUser = loadSession();
    if (savedUser) {
      setUser(savedUser);
    }
  }, []);

  // Check API Health
  useEffect(() => {
    const checkApiHealth = async () => {
      try {
        const response = await fetch(`${API_URL}/docs`, {
          signal: AbortSignal.timeout(2000),
        });
        setApiStatus(response.ok ? "online" : "error");
      } catch {
        setApiStatus("offline");
      }
    };

    checkApiHealth();
    const interval = setInterval(checkApiHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  // Handle Login
  const handleLogin = (email: string) => {
    const newUser = loginUser(email, "demo");
    if (newUser) {
      setUser(newUser);
      setAuthError(null);
      setChatHistory([]);
      setDocument({ uploaded: false, name: "", sizeKb: 0, id: "" });
    } else {
      setAuthError("Login failed. Please try again.");
    }
  };

  // Handle Logout
  const handleLogout = () => {
    logoutUser();
    setUser(null);
    setChatHistory([]);
    setDocument({ uploaded: false, name: "", sizeKb: 0, id: "" });
  };

  // If not authenticated, show login screen
  if (!user) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  // Handle File Selection
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
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
    if (!selectedFile) {
      setProcessStatus({ type: "error", message: "Please select a file first." });
      return;
    }

    setIsProcessing(true);
    setProcessStatus(null);

    try {
      const documentId = deriveDocumentId(selectedFile.name);
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("tenant_id", user.id);  // Use user ID for document isolation
      formData.append("collection_id", "default");
      formData.append("document_id", documentId);

      const response = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
        signal: AbortSignal.timeout(60000),
      });

      if (response.ok) {
        setDocument({
          uploaded: true,
          name: selectedFile.name,
          sizeKb: selectedFile.size / 1024,
          id: documentId,
        });
        setChatHistory([]);
        setProcessStatus({ type: "success", message: "Document processed successfully!" });
        setShowBalloons(true);
        setTimeout(() => setShowBalloons(false), 4000);
      } else {
        const text = await response.text();
        setProcessStatus({ type: "error", message: `Error: ${text}` });
      }
    } catch (error: any) {
      setProcessStatus({
        type: "error",
        message: `Connection error: ${error.message}. Make sure the FastAPI server is running on ${API_URL}`,
      });
    } finally {
      setIsProcessing(false);
    }
  };

  // Process a SharePoint file by URL (downloaded server-side via Microsoft Graph)
  const handleProcessSharePoint = async () => {
    const url = sharepointUrl.trim();
    if (!url) {
      setProcessStatus({ type: "error", message: "Enter a SharePoint file URL first." });
      return;
    }

    setIsProcessing(true);
    setProcessStatus(null);

    try {
      const documentId = deriveDocumentIdFromUrl(url);
      const response = await fetch(`${API_URL}/upload-sharepoint`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sharepoint_url: url,
          tenant_id: user.id, // Use user ID for document isolation
          collection_id: "default",
          document_id: documentId,
        }),
        signal: AbortSignal.timeout(60000),
      });

      if (response.ok) {
        const data = await response.json().catch(() => ({}));
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
        setTimeout(() => setShowBalloons(false), 4000);
      } else {
        const text = await response.text();
        setProcessStatus({ type: "error", message: `Error: ${text}` });
      }
    } catch (error: any) {
      setProcessStatus({
        type: "error",
        message: `Connection error: ${error.message}. Make sure the FastAPI server is running on ${API_URL}`,
      });
    } finally {
      setIsProcessing(false);
    }
  };

  // Submit Question
  const handleSubmitQuestion = async (e: React.FormEvent) => {
    e.preventDefault();

    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setQuestionError("Please enter a question before requesting an answer.");
      return;
    }

    setIsAsking(true);
    setQuestionError(null);

    try {
      const response = await fetch(`${API_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmedQuestion,
          tenant_id: user.id,  // Use user ID for document isolation
          collection_id: "default",
          document_id: document.id || "default",
        }),
        signal: AbortSignal.timeout(60000),
      });

      if (response.ok) {
        const data = await response.json();
        const answer = data.answer || "";
        setChatHistory([
          ...chatHistory,
          {
            question: trimmedQuestion,
            answer,
            timestamp: formatTimestamp(),
          },
        ]);
        setQuestion("");
      } else {
        const text = await response.text();
        setQuestionError(`Error: ${text}`);
      }
    } catch (error: any) {
      setQuestionError(`Connection error: ${error.message}`);
    } finally {
      setIsAsking(false);
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
            <p style={styles.sectionDescription}>
              Upload a PDF, DOCX, TXT, or image file — or link a SharePoint file — to get started
            </p>

            <div style={styles.fileInputWrapper}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.bmp,.tiff,.tif,.webp,.gif"
                onChange={handleFileChange}
                style={styles.fileInput}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
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

            <div style={{ margin: "16px 0 8px", color: "#999", fontSize: "0.85rem" }}>
              — or —
            </div>
            <input
              type="url"
              value={sharepointUrl}
              onChange={(e) => {
                setSharePointUrl(e.target.value);
                if (e.target.value) setSelectedFile(null);
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
                {processStatus.type === "success" ? "✅" : "❌"} {processStatus.message}
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

            {!document.uploaded ? (
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
          <p style={styles.sidebarText}><strong>Name:</strong> {user.name}</p>
          <p style={{ ...styles.sidebarText, fontSize: "0.85rem", color: "#666", marginBottom: "12px" }}>
            <strong>Email:</strong> {user.email}
          </p>
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
