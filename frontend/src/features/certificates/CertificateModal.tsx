/**
 * Professional modal shell for certificate feature dialogs.
 *
 * Features:
 * - Slide-in animation (CSS transition)
 * - Frosted-glass backdrop with smooth fade
 * - ATT-themed header with gradient accent bar
 * - Optional subtitle for context
 * - Keyboard accessible (Escape to close, focus trap intent)
 * - Responsive max-height with scroll
 */

import React, { ReactNode, useEffect, useState } from "react";

interface CertificateModalProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  widthClassName?: string;
  variant?: "default" | "danger" | "success";
}

const variantAccent = {
  default: "from-att-400 via-att-600 to-att-400",
  danger: "from-red-400 via-red-600 to-red-400",
  success: "from-green-400 via-green-600 to-green-400",
};

export const CertificateModal: React.FC<CertificateModalProps> = ({
  title,
  subtitle,
  icon,
  onClose,
  children,
  footer,
  widthClassName = "max-w-lg",
  variant = "default",
}) => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Trigger enter animation after mount
    requestAnimationFrame(() => setVisible(true));
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const titleId = `cert-modal-${title.replace(/\s+/g, "-").toLowerCase()}`;

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center p-4 transition-all duration-200 ${
        visible ? "bg-slate-900/50 backdrop-blur-sm" : "bg-transparent"
      }`}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`w-full ${widthClassName} transform overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-black/5 transition-all duration-200 ${
          visible ? "scale-100 opacity-100 translate-y-0" : "scale-95 opacity-0 translate-y-4"
        }`}
      >
        {/* Gradient accent bar */}
        <div className={`h-1 bg-gradient-to-r ${variantAccent[variant]}`} />

        {/* Header */}
        <div className="flex items-start justify-between border-b border-att-100 bg-gradient-to-b from-att-50/80 to-white px-6 py-4">
          <div className="flex items-center gap-3">
            {icon && (
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-att-100 text-att-700">
                {icon}
              </div>
            )}
            <div>
              <h2 id={titleId} className="text-lg font-semibold text-gray-900">
                {title}
              </h2>
              {subtitle && (
                <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>
              )}
            </div>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-400 transition hover:bg-att-100 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-att-300"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="max-h-[65vh] overflow-y-auto px-6 py-5">{children}</div>

        {/* Footer */}
        {footer ? (
          <div className="flex items-center justify-end gap-3 border-t border-att-100 bg-att-50/30 px-6 py-4">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
};

// ── Button styles ─────────────────────────────────────────────────────

export const modalButton = {
  primary:
    "inline-flex items-center gap-2 rounded-lg bg-att-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-att-700 focus:outline-none focus:ring-2 focus:ring-att-300 disabled:opacity-50 transition",
  danger:
    "inline-flex items-center gap-2 rounded-lg bg-red-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-300 disabled:opacity-50 transition",
  success:
    "inline-flex items-center gap-2 rounded-lg bg-green-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-300 disabled:opacity-50 transition",
  secondary:
    "inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700 shadow-sm hover:bg-att-50 focus:outline-none focus:ring-2 focus:ring-att-200 disabled:opacity-50 transition",
};

// ── Form field styles ─────────────────────────────────────────────────

export const fieldLabel = "mb-1.5 block text-xs font-semibold uppercase tracking-wide text-gray-600";
export const fieldInput =
  "w-full rounded-lg border border-att-200 bg-white px-3.5 py-2.5 text-sm text-gray-800 shadow-sm transition focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100 placeholder:text-gray-400";

// ── Info/Warning alert box ────────────────────────────────────────────

export const AlertBox: React.FC<{ variant: "info" | "warning" | "danger"; children: ReactNode }> = ({ variant, children }) => {
  const styles = {
    info: "border-blue-200 bg-blue-50 text-blue-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    danger: "border-red-200 bg-red-50 text-red-800",
  };
  return <div className={`rounded-lg border p-3.5 text-xs leading-relaxed ${styles[variant]}`}>{children}</div>;
};
