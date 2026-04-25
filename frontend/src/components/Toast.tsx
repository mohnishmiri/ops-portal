/**
 * Shared Toast notification component.
 * Used across pages for consistent mutation feedback (success/error).
 *
 * Usage:
 *   const [toast, setToast] = useState<ToastState | null>(null);
 *   const showToast = useCallback((message: string, type: ToastType = "success") => setToast({ message, type }), []);
 *   // ... in JSX:
 *   {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
 */

import React from "react";

export type ToastType = "success" | "error" | "info" | "warning";
export interface ToastState {
  message: string;
  type: ToastType;
}

const TOAST_BG: Record<ToastType, string> = {
  success: "bg-green-600",
  error: "bg-red-600",
  info: "bg-blue-600",
  warning: "bg-yellow-500",
};

const TOAST_ICON: Record<ToastType, JSX.Element> = {
  success: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  ),
  error: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  ),
  info: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
  warning: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
};

interface ToastProps {
  message: string;
  type: ToastType;
  onClose: () => void;
  /** Auto-dismiss in ms (default 4000). Set 0 to disable. */
  duration?: number;
}

const Toast: React.FC<ToastProps> = ({ message, type, onClose, duration = 4000 }) => {
  React.useEffect(() => {
    if (duration <= 0) return;
    const t = setTimeout(onClose, duration);
    return () => clearTimeout(t);
  }, [onClose, duration]);

  return (
    <div
      className={`fixed bottom-6 right-6 z-[100] flex items-center gap-3 px-5 py-3 rounded-lg shadow-lg text-white text-sm font-medium animate-slide-up ${TOAST_BG[type]}`}
      role="alert"
    >
      {TOAST_ICON[type]}
      <span className="max-w-xs">{message}</span>
      <button onClick={onClose} className="ml-2 hover:opacity-80 text-lg leading-none">&times;</button>
    </div>
  );
};

export default Toast;
