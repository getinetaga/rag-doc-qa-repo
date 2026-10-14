/**
 * Custom React Hooks for RAG Document QA Application
 * Encapsulates state and side effects logic
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { API_URL, HEALTH_CHECK_INTERVAL } from "./constants";
import { debugLog } from "./utils";

/**
 * Hook for API health checks
 * Periodically checks if the backend API is available
 * 
 * @param interval - Check interval in milliseconds
 * @returns API status: "online" | "offline" | "error"
 */
export function useApiHealth(interval: number = HEALTH_CHECK_INTERVAL) {
  const [apiStatus, setApiStatus] = useState<"online" | "offline" | "error">(
    "offline"
  );

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch(`${API_URL}/docs`, {
          signal: AbortSignal.timeout(2000),
        });
        setApiStatus(response.ok ? "online" : "error");
      } catch {
        setApiStatus("offline");
      }
    };

    checkHealth();
    const intervalId = setInterval(checkHealth, interval);

    return () => clearInterval(intervalId);
  }, [interval]);

  return apiStatus;
}

/**
 * Hook for auto-scrolling to a DOM element
 * Useful for auto-scrolling chat to bottom
 * 
 * @param dependency - Dependency to trigger scroll
 * @returns Ref to attach to scrollable element
 */
export function useAutoScroll<T extends HTMLElement>(
  dependency?: any
): React.RefObject<T> {
  const ref = useRef<T>(null);

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth" });
  }, [dependency]);

  return ref;
}

/**
 * Hook for persisting state to localStorage
 * 
 * @param key - Storage key
 * @param initialValue - Initial value
 * @returns [value, setValue] tuple like useState
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((val: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    try {
      const item = window.localStorage.getItem(key);
      return item ? JSON.parse(item) : initialValue;
    } catch (error) {
      debugLog("Failed to read from localStorage", error);
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T | ((val: T) => T)) => {
      try {
        const valueToStore =
          value instanceof Function ? value(storedValue) : value;
        setStoredValue(valueToStore);
        window.localStorage.setItem(key, JSON.stringify(valueToStore));
      } catch (error) {
        debugLog("Failed to write to localStorage", error);
      }
    },
    [key, storedValue]
  );

  return [storedValue, setValue];
}

/**
 * Hook for debounced values
 * Useful for debouncing search input or auto-save
 * 
 * @param value - Value to debounce
 * @param delay - Debounce delay in milliseconds
 * @returns Debounced value
 */
export function useDebouncedValue<T>(value: T, delay: number = 300): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => clearTimeout(handler);
  }, [value, delay]);

  return debouncedValue;
}

/**
 * Hook for throttled callback
 * Useful for preventing rapid function calls
 * 
 * @param callback - Callback to throttle
 * @param delay - Throttle delay in milliseconds
 * @returns Throttled callback
 */
export function useThrottledCallback<T extends (...args: any[]) => any>(
  callback: T,
  delay: number = 300
): T {
  const throttledRef = useRef<boolean>(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  return useCallback(
    ((...args) => {
      if (throttledRef.current) return;

      throttledRef.current = true;
      callback(...args);

      timeoutRef.current = setTimeout(() => {
        throttledRef.current = false;
      }, delay);
    }) as T,
    [callback, delay]
  );
}

/**
 * Hook for detecting outside click
 * Useful for closing modals or dropdowns
 * 
 * @param ref - Ref to element
 * @param callback - Callback on outside click
 */
export function useClickOutside(
  ref: React.RefObject<HTMLElement>,
  callback: () => void
): void {
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        callback();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [ref, callback]);
}

/**
 * Hook for keyboard shortcuts
 * 
 * @param key - Key to listen for
 * @param callback - Callback on key press
 * @param ctrlKey - Require Ctrl key
 */
export function useKeyboardShortcut(
  key: string,
  callback: () => void,
  ctrlKey: boolean = false
): void {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isCorrectKey = event.key.toLowerCase() === key.toLowerCase();
      const hasCtrl = ctrlKey ? event.ctrlKey || event.metaKey : true;

      if (isCorrectKey && hasCtrl) {
        event.preventDefault();
        callback();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [key, callback, ctrlKey]);
}

/**
 * Hook for async operations with loading and error states
 * 
 * @param asyncFunction - Async function to call
 * @param dependencies - Dependencies array
 * @returns { data, loading, error }
 */
export function useAsync<T>(
  asyncFunction: () => Promise<T>,
  dependencies: any[] = []
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let isMounted = true;

    const fetchData = async () => {
      try {
        setLoading(true);
        const result = await asyncFunction();
        if (isMounted) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err : new Error("Unknown error"));
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      isMounted = false;
    };
  }, dependencies);

  return { data, loading, error };
}

/**
 * Hook for tracking previous value
 * 
 * @param value - Current value
 * @returns Previous value
 */
export function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T>();

  useEffect(() => {
    ref.current = value;
  }, [value]);

  return ref.current;
}

/**
 * Hook for mounting state
 * Useful for animations or initial load checks
 * 
 * @returns Boolean indicating if component is mounted
 */
export function useMounted(): boolean {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  return isMounted;
}

/**
 * Hook for window resize listener
 * 
 * @returns { width, height }
 */
export function useWindowSize(): { width: number; height: number } {
  const [windowSize, setWindowSize] = useState({
    width: typeof window !== "undefined" ? window.innerWidth : 0,
    height: typeof window !== "undefined" ? window.innerHeight : 0,
  });

  useEffect(() => {
    const handleResize = () => {
      setWindowSize({
        width: window.innerWidth,
        height: window.innerHeight,
      });
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return windowSize;
}

/**
 * Hook for page visibility (tab focus)
 * 
 * @returns Boolean indicating if page is visible
 */
export function usePageVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsVisible(!document.hidden);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  return isVisible;
}

/**
 * Hook for form state management
 * 
 * @param initialValues - Initial form values
 * @returns { values, handleChange, handleSubmit, reset }
 */
export function useForm<T extends Record<string, any>>(initialValues: T) {
  const [values, setValues] = useState(initialValues);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const { name, value, type } = e.target;
      setValues((prev) => ({
        ...prev,
        [name]: type === "checkbox" ? (e.target as HTMLInputElement).checked : value,
      }));
    },
    []
  );

  const reset = useCallback(() => {
    setValues(initialValues);
  }, [initialValues]);

  return {
    values,
    handleChange,
    reset,
    setValues,
  };
}

/**
 * Hook for performance monitoring
 * 
 * @param componentName - Name of component
 */
export function usePerformanceMonitor(componentName: string): void {
  useEffect(() => {
    const startTime = performance.now();

    return () => {
      const endTime = performance.now();
      debugLog(
        `${componentName} render time: ${(endTime - startTime).toFixed(2)}ms`
      );
    };
  });
}
