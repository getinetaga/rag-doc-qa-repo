/**
 * Login Screen Component
 * Simple authentication UI for user login
 */

import React, { useState } from "react";
import { COLORS, SPACING, TYPOGRAPHY } from "./constants";

interface LoginProps {
  onLogin: (apiKey: string) => Promise<void>;
  authError?: string | null;
}

const loginStyles = {
  container: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    minHeight: "100vh",
    background: `linear-gradient(135deg, ${COLORS.PRIMARY} 0%, #0D47A1 100%)`,
    fontFamily: TYPOGRAPHY.FONT_FAMILY,
  },
  card: {
    background: COLORS.WHITE,
    padding: SPACING.PADDING_LARGE,
    borderRadius: SPACING.BORDER_RADIUS_LARGE,
    boxShadow: "0 8px 32px rgba(0, 0, 0, 0.1)",
    maxWidth: "400px",
    width: "90%",
  },
  header: {
    textAlign: "center" as const,
    marginBottom: SPACING.MARGIN_LARGE,
  },
  title: {
    fontSize: TYPOGRAPHY.FONT_SIZE_HEADER,
    color: COLORS.TEXT,
    margin: `${SPACING.MARGIN_NORMAL} 0`,
    fontWeight: "bold",
  },
  subtitle: {
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    color: COLORS.TEXT_LIGHT,
    margin: "0",
  },
  form: {
    display: "flex",
    flexDirection: "column" as const,
    gap: SPACING.MARGIN_NORMAL,
  },
  formGroup: {
    display: "flex",
    flexDirection: "column" as const,
    gap: SPACING.MARGIN_SMALL,
  },
  label: {
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    fontWeight: "500" as const,
    color: COLORS.TEXT,
  },
  input: {
    padding: SPACING.PADDING_NORMAL,
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    border: `2px solid ${COLORS.BORDER}`,
    borderRadius: SPACING.BORDER_RADIUS,
    fontFamily: TYPOGRAPHY.FONT_FAMILY,
    transition: "all 0.3s ease",
    boxSizing: "border-box" as const,
  },
  inputFocus: {
    borderColor: COLORS.PRIMARY,
    outline: "none",
    boxShadow: `0 0 0 3px rgba(30, 136, 229, 0.1)`,
  },
  button: {
    padding: SPACING.PADDING_NORMAL,
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    fontWeight: "bold" as const,
    border: "none",
    borderRadius: SPACING.BORDER_RADIUS,
    cursor: "pointer",
    transition: "all 0.3s ease",
    background: COLORS.PRIMARY,
    color: COLORS.WHITE,
    marginTop: SPACING.MARGIN_NORMAL,
  },
  buttonHover: {
    background: "#1565C0",
    transform: "translateY(-2px)",
    boxShadow: "0 4px 12px rgba(30, 136, 229, 0.3)",
  },
  error: {
    background: COLORS.ERROR,
    color: COLORS.ERROR_TEXT,
    padding: SPACING.PADDING_NORMAL,
    borderRadius: SPACING.BORDER_RADIUS,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    border: `1px solid ${COLORS.ERROR_BORDER}`,
  },
  demoHint: {
    marginTop: SPACING.MARGIN_LARGE,
    padding: SPACING.PADDING_NORMAL,
    background: COLORS.INFO,
    color: COLORS.INFO_TEXT,
    borderRadius: SPACING.BORDER_RADIUS,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    border: `1px solid ${COLORS.INFO_BORDER}`,
  },
};

export default function LoginScreen({ onLogin, authError }: LoginProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [passwordFocus, setPasswordFocus] = useState(false);
  const [buttonHover, setButtonHover] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    if (!password.trim()) {
      setError("Please enter your individual API key.");
      setIsLoading(false);
      return;
    }

    const key = password.trim();
    setPassword("");
    try {
      await onLogin(key);
    } catch {
      setError("Unable to sign in. Check your API key and server connection.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={loginStyles.container}>
      <div style={loginStyles.card}>
        <div style={loginStyles.header}>
          <div style={{ fontSize: "3rem", marginBottom: SPACING.MARGIN_NORMAL }}>
            📚
          </div>
          <h1 style={loginStyles.title}>RAG Document QA</h1>
          <p style={loginStyles.subtitle}>AI-Powered Question Answering</p>
        </div>

        <form style={loginStyles.form} onSubmit={handleSubmit}>
          {(error || authError) && <div role="alert" style={loginStyles.error}>❌ {error || authError}</div>}

          <div style={loginStyles.formGroup}>
            <label htmlFor="password" style={loginStyles.label}>
              🔒 Individual API key
            </label>
            <input
              id="password"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{
                ...loginStyles.input,
                ...(passwordFocus ? loginStyles.inputFocus : {}),
              }}
              onFocus={() => setPasswordFocus(true)}
              onBlur={() => setPasswordFocus(false)}
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            style={{
              ...loginStyles.button,
              ...(buttonHover ? loginStyles.buttonHover : {}),
              opacity: isLoading ? 0.7 : 1,
              cursor: isLoading ? "not-allowed" : "pointer",
            }}
            onMouseEnter={() => !isLoading && setButtonHover(true)}
            onMouseLeave={() => setButtonHover(false)}
            disabled={isLoading}
          >
            {isLoading ? "🔄 Logging in..." : "🚀 Login"}
          </button>

          <div style={loginStyles.demoHint}>
            Use the key issued by your administrator. It stays in memory only;
            refreshing this page signs you out.
          </div>
        </form>
      </div>
    </div>
  );
}
