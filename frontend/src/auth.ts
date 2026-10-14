/**
 * Authentication and User Management
 * Handles user login, session storage, and user context
 */

export interface User {
  id: string;
  name: string;
  email: string;
  loginTime: number;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  error: string | null;
}

const STORAGE_KEY = "rag_user_session";
const SESSION_TIMEOUT = 24 * 60 * 60 * 1000; // 24 hours

/**
 * Save user session to localStorage
 */
export function saveSession(user: User): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  } catch (e) {
    console.error("Failed to save session:", e);
  }
}

/**
 * Load user session from localStorage
 */
export function loadSession(): User | null {
  try {
    const data = localStorage.getItem(STORAGE_KEY);
    if (!data) return null;

    const user: User = JSON.parse(data);
    const now = Date.now();
    
    // Check if session expired
    if (now - user.loginTime > SESSION_TIMEOUT) {
      clearSession();
      return null;
    }

    return user;
  } catch (e) {
    console.error("Failed to load session:", e);
    clearSession();
    return null;
  }
}

/**
 * Clear user session
 */
export function clearSession(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (e) {
    console.error("Failed to clear session:", e);
  }
}

/**
 * Validate email format
 */
export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

/**
 * Generate user ID from email
 * In production, this would be handled by backend authentication
 */
export function generateUserId(email: string): string {
  return email.toLowerCase().replace(/[^a-z0-9]/g, "_");
}

/**
 * Login user (simple client-side for demo)
 * In production, this would validate against a backend auth service
 */
export function loginUser(email: string, password: string): User | null {
  // Basic validation
  if (!email || !password) {
    return null;
  }

  if (!isValidEmail(email)) {
    return null;
  }

  // In production: verify against backend
  // For now: accept any valid email/password combination
  if (password.length < 4) {
    return null;
  }

  const user: User = {
    id: generateUserId(email),
    name: email.split("@")[0], // Use email prefix as display name
    email: email,
    loginTime: Date.now(),
  };

  saveSession(user);
  return user;
}

/**
 * Logout user
 */
export function logoutUser(): void {
  clearSession();
}

/**
 * Get current user
 */
export function getCurrentUser(): User | null {
  return loadSession();
}
