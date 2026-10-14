/**
 * Reusable CSS styles for RAG Document QA Application
 * Mirrors Streamlit CSS styling
 */

import { COLORS, SPACING, TYPOGRAPHY, ANIMATIONS } from "./constants";

/**
 * Base styles
 */
export const styles = {
  container: {
    minHeight: "100vh",
    backgroundColor: COLORS.BACKGROUND,
    fontFamily: TYPOGRAPHY.FONT_FAMILY,
    padding: SPACING.PADDING_LARGE,
  } as React.CSSProperties,

  header: {
    textAlign: "center" as const,
    marginBottom: SPACING.MARGIN_LARGE,
    paddingBottom: SPACING.PADDING_NORMAL,
    borderBottom: `2px solid ${COLORS.PRIMARY}`,
  } as React.CSSProperties,

  title: {
    fontSize: TYPOGRAPHY.FONT_SIZE_TITLE,
    color: COLORS.PRIMARY,
    margin: "0 0 10px 0",
    fontWeight: 600,
  } as React.CSSProperties,

  subtitle: {
    fontSize: TYPOGRAPHY.FONT_SIZE_SUBTITLE,
    color: COLORS.TEXT_LIGHT,
    margin: 0,
  } as React.CSSProperties,

  // Layout
  mainContent: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: SPACING.MARGIN_NORMAL,
    marginBottom: SPACING.MARGIN_LARGE,
    maxWidth: "1200px",
    margin: "0 auto 40px auto",
  } as React.CSSProperties,

  column: {
    display: "flex",
    flexDirection: "column" as const,
  } as React.CSSProperties,

  card: {
    backgroundColor: COLORS.WHITE,
    borderRadius: SPACING.BORDER_RADIUS_LARGE,
    padding: SPACING.PADDING_LARGE,
    boxShadow: "0 2px 8px rgba(0, 0, 0, 0.1)",
    display: "flex",
    flexDirection: "column" as const,
    gap: SPACING.MARGIN_NORMAL,
  } as React.CSSProperties,

  // Typography
  sectionTitle: {
    fontSize: TYPOGRAPHY.FONT_SIZE_HEADER,
    color: COLORS.TEXT,
    margin: "0 0 8px 0",
    fontWeight: 600,
  } as React.CSSProperties,

  sectionDescription: {
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    color: COLORS.TEXT_LIGHT,
    margin: "0 0 16px 0",
  } as React.CSSProperties,

  // File Input
  fileInputWrapper: {
    display: "flex",
    gap: SPACING.MARGIN_NORMAL,
    alignItems: "center",
  } as React.CSSProperties,

  fileInput: {
    display: "none",
  } as React.CSSProperties,

  fileButton: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    backgroundColor: COLORS.PRIMARY,
    color: COLORS.WHITE,
    border: "none",
    borderRadius: SPACING.BORDER_RADIUS,
    cursor: "pointer",
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    fontWeight: 500,
    transition: `background-color ${ANIMATIONS.TRANSITION_NORMAL}`,
  } as React.CSSProperties,

  // Alert Boxes
  infoBox: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    borderRadius: SPACING.BORDER_RADIUS,
    backgroundColor: COLORS.INFO,
    border: `1px solid ${COLORS.INFO_BORDER}`,
    color: COLORS.INFO_TEXT,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
  } as React.CSSProperties,

  successBox: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    borderRadius: SPACING.BORDER_RADIUS,
    backgroundColor: COLORS.SUCCESS,
    border: `1px solid ${COLORS.SUCCESS_BORDER}`,
    color: COLORS.SUCCESS_TEXT,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
  } as React.CSSProperties,

  errorBox: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    borderRadius: SPACING.BORDER_RADIUS,
    backgroundColor: COLORS.ERROR,
    border: `1px solid ${COLORS.ERROR_BORDER}`,
    color: COLORS.ERROR_TEXT,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
  } as React.CSSProperties,

  // Buttons
  primaryButton: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    backgroundColor: COLORS.PRIMARY,
    color: COLORS.WHITE,
    border: "none",
    borderRadius: SPACING.BORDER_RADIUS,
    cursor: "pointer",
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    fontWeight: 600,
    transition: `background-color ${ANIMATIONS.TRANSITION_NORMAL}`,
  } as React.CSSProperties,

  secondaryButton: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    backgroundColor: "#f44336",
    color: COLORS.WHITE,
    border: "none",
    borderRadius: SPACING.BORDER_RADIUS,
    cursor: "pointer",
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    fontWeight: 600,
    transition: `background-color ${ANIMATIONS.TRANSITION_NORMAL}`,
  } as React.CSSProperties,

  buttonDisabled: {
    opacity: 0.6,
    cursor: "not-allowed",
  } as React.CSSProperties,

  // Form
  form: {
    display: "flex",
    flexDirection: "column" as const,
    gap: SPACING.MARGIN_NORMAL,
  } as React.CSSProperties,

  questionInput: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    borderRadius: SPACING.BORDER_RADIUS,
    border: `1px solid ${COLORS.BORDER}`,
    fontSize: TYPOGRAPHY.FONT_SIZE_NORMAL,
    fontFamily: "inherit",
    boxSizing: "border-box" as const,
    transition: `border-color ${ANIMATIONS.TRANSITION_NORMAL}`,
  } as React.CSSProperties,

  buttonGroup: {
    display: "flex",
    gap: SPACING.MARGIN_NORMAL,
  } as React.CSSProperties,

  // History
  historySection: {
    maxWidth: "1200px",
    margin: "0 auto 40px auto",
    backgroundColor: COLORS.WHITE,
    borderRadius: SPACING.BORDER_RADIUS_LARGE,
    padding: SPACING.PADDING_LARGE,
    boxShadow: "0 2px 8px rgba(0, 0, 0, 0.1)",
  } as React.CSSProperties,

  chatHistoryContainer: {
    display: "flex",
    flexDirection: "column" as const,
    gap: SPACING.MARGIN_LARGE,
  } as React.CSSProperties,

  chatMessage: {
    paddingBottom: SPACING.MARGIN_LARGE,
    borderBottom: `1px solid #eee`,
  } as React.CSSProperties,

  questionText: {
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    color: COLORS.TEXT,
    marginBottom: SPACING.MARGIN_NORMAL,
    fontWeight: 500,
  } as React.CSSProperties,

  answerBox: {
    padding: SPACING.PADDING_NORMAL,
    borderRadius: SPACING.BORDER_RADIUS,
    backgroundColor: COLORS.ANSWER_BG,
    borderLeft: `4px solid ${COLORS.ANSWER_BORDER}`,
    marginBottom: SPACING.MARGIN_NORMAL,
  } as React.CSSProperties,

  answerBoxText: {
    margin: 0,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    lineHeight: 1.6,
  } as React.CSSProperties,

  timestamp: {
    fontSize: TYPOGRAPHY.FONT_SIZE_TINY,
    color: COLORS.TEXT_GRAY,
  } as React.CSSProperties,

  // Sidebar
  sidebar: {
    position: "fixed" as const,
    right: SPACING.MARGIN_LARGE,
    top: "120px",
    width: "280px",
    display: "flex",
    flexDirection: "column" as const,
    gap: SPACING.MARGIN_NORMAL,
    maxHeight: "calc(100vh - 140px)",
    overflowY: "auto" as const,
  } as React.CSSProperties,

  sidebarCard: {
    backgroundColor: COLORS.WHITE,
    borderRadius: SPACING.BORDER_RADIUS_LARGE,
    padding: SPACING.PADDING_NORMAL,
    boxShadow: "0 2px 8px rgba(0, 0, 0, 0.1)",
  } as React.CSSProperties,

  sidebarTitle: {
    fontSize: TYPOGRAPHY.FONT_SIZE_SUBTITLE,
    color: COLORS.TEXT,
    margin: "0 0 12px 0",
    fontWeight: 600,
  } as React.CSSProperties,

  sidebarText: {
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    color: COLORS.TEXT_LIGHT,
    margin: "0 0 12px 0",
  } as React.CSSProperties,

  list: {
    margin: "0 0 12px 20px",
    paddingLeft: 0,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    color: COLORS.TEXT_LIGHT,
  } as React.CSSProperties,

  statusIndicator: {
    padding: `${SPACING.PADDING_SMALL} ${SPACING.PADDING_NORMAL}`,
    borderRadius: SPACING.BORDER_RADIUS,
    marginBottom: SPACING.MARGIN_NORMAL,
    fontSize: TYPOGRAPHY.FONT_SIZE_SMALL,
    fontWeight: 500,
  } as React.CSSProperties,

  // Animations
  balloonsOverlay: {
    position: "fixed" as const,
    bottom: 0,
    left: 0,
    width: "100%",
    height: "100%",
    pointerEvents: "none" as const,
    zIndex: 9999,
    overflow: "hidden",
  } as React.CSSProperties,

  // Spinners and Loading
  spinner: {
    display: "inline-block",
    width: "20px",
    height: "20px",
    border: `3px solid rgba(0, 0, 0, 0.1)`,
    borderTop: `3px solid ${COLORS.PRIMARY}`,
    borderRadius: "50%",
    animation: "spin 1s linear infinite",
  } as React.CSSProperties,

  // Responsive
  responsiveHidden: {
    display: "none",
  } as React.CSSProperties,
};

/**
 * Mobile-responsive style utilities
 */
export const mediaQueries = {
  mobile: "(max-width: 768px)",
  tablet: "(min-width: 769px) and (max-width: 1024px)",
  desktop: "(min-width: 1025px)",
};

/**
 * Dynamic style generator
 */
export function getStatusBoxStyle(
  status: "success" | "error" | "info"
): React.CSSProperties {
  switch (status) {
    case "success":
      return styles.successBox;
    case "error":
      return styles.errorBox;
    case "info":
    default:
      return styles.infoBox;
  }
}

/**
 * Button style with state
 */
export function getButtonStyle(
  disabled: boolean = false,
  variant: "primary" | "secondary" = "primary"
): React.CSSProperties {
  const baseStyle =
    variant === "primary" ? styles.primaryButton : styles.secondaryButton;
  return {
    ...baseStyle,
    ...(disabled && styles.buttonDisabled),
  };
}
