export interface Scope {
  tenant_id: string;
  collection_id: string;
}

export interface User {
  user_id: string;
  roles: ("read" | "ingest" | "admin")[];
  scopes: Scope[];
}

let apiKey = "";
let user: User | null = null;
let scope: Scope | null = null;
let generation = 0;
let controller = new AbortController();
const listeners = new Set<(message?: string) => void>();

export function getCurrentUser() { return user; }
export function getCurrentScope() { return scope; }
export function getSessionGeneration() { return generation; }
export function isCurrentSession(value: number) { return value === generation; }

export function subscribeSession(listener: (message?: string) => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function invalidate(message?: string) {
  generation++;
  controller.abort();
  controller = new AbortController();
  listeners.forEach((listener) => listener(message));
}

export function logoutUser(message?: string) {
  apiKey = "";
  user = null;
  scope = null;
  invalidate(message);
}

export function selectScope(next: Scope) {
  const grant = user?.scopes.find(
    (item) => item.tenant_id === next.tenant_id && item.collection_id === next.collection_id
  );
  if (!grant) throw new Error("Select an authorized tenant/project.");
  scope = grant;
  invalidate();
}

export async function loginUser(key: string, apiUrl: string): Promise<User> {
  logoutUser();
  const version = generation;
  const request = new AbortController();
  const boundary = controller.signal;
  const abort = () => request.abort();
  boundary.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 15000);
  let data: User;
  try {
    const response = await fetch(`${apiUrl}/session`, {
      headers: { Authorization: `Bearer ${key}` },
      signal: request.signal,
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) throw new Error(
      response.status === 401 ? "Invalid API key. Please sign in again." : "Unable to validate API key."
    );
    data = await response.json();
  } finally {
    clearTimeout(timer);
    boundary.removeEventListener("abort", abort);
  }
  if (!isCurrentSession(version)) throw new Error("Sign-in cancelled.");
  if (!data.user_id || !Array.isArray(data.roles) ||
      !data.roles.every((role) => ["read", "ingest", "admin"].includes(role)) ||
      !Array.isArray(data.scopes) || !data.scopes.length ||
      !data.scopes.every((grant) => typeof grant.tenant_id === "string" &&
        !!grant.tenant_id && typeof grant.collection_id === "string" && !!grant.collection_id)) {
    throw new Error("No valid tenant/project grants were returned for this key.");
  }
  apiKey = key;
  user = data;
  scope = data.scopes[0];
  invalidate();
  return data;
}

// All protected requests share an abort boundary with the current identity/scope.
export async function authenticatedFetch(
  url: string, init: RequestInit = {}, timeout = 60000
): Promise<Response> {
  if (!apiKey || !user) throw new Error("Please sign in with your API key.");
  const version = generation;
  const boundary = controller.signal;
  const request = new AbortController();
  const abort = () => request.abort();
  boundary.addEventListener("abort", abort, { once: true });
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) request.abort();
  const timer = setTimeout(abort, timeout);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${apiKey}`);
  try {
    const response = await fetch(url, {
      ...init, headers, signal: request.signal, cache: "no-store", redirect: "error",
    });
    if (!isCurrentSession(version)) throw new Error("Request cancelled.");
    if (response.status === 401) {
      logoutUser("Your API key was rejected or expired. Please sign in again.");
      throw new Error("Your API key was rejected or expired. Please sign in again.");
    }
    const body = await response.blob();
    if (!isCurrentSession(version)) throw new Error("Request cancelled.");
    return new Response(body, {
      status: response.status, statusText: response.statusText, headers: response.headers,
    });
  } catch (error) {
    if (request.signal.aborted && isCurrentSession(version)) {
      throw new Error(init.signal?.aborted ? "Request cancelled." : "Request timed out. Please try again.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
    boundary.removeEventListener("abort", abort);
    init.signal?.removeEventListener("abort", abort);
  }
}
