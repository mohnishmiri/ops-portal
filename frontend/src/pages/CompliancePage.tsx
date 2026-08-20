/**
 * Compliance Page — Thin orchestrator for modular compliance sub-components.
 *
 * Module 3: Compliance & Drift Detection
 * - Delegates all logic to dedicated tab components under ./compliance/
 * - Manages only tab navigation state and toast notifications
 */

import React, { useState, useCallback } from "react";
import Toast, { type ToastState } from "../components/Toast";
import { ChecksumScheduleManagement } from "../features/checksum/ChecksumScheduleManagement";
import ComplianceDashboard from "../features/compliance/ComplianceDashboard";
import AKSChecksumTab from "../features/compliance/AKSChecksumTab";
import ChecksumVerificationTab from "../features/compliance/ChecksumVerificationTab";

/* ── SVG Icon Helpers ─────────────────────────────────────────────── */

const ShieldIcon: React.FC<{ cls?: string }> = ({ cls = "" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" width={20} height={20} className={cls}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

const SynapseIcon: React.FC<{ cls?: string }> = ({ cls = "" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" width={20} height={20} className={cls}>
    <path d="M5 3v4M3 5h4M6 17v4M4 19h4M13 3l4 4M17 3l-4 4M14 17l4 4M17 17l-4 4M12 8v8M8 12h8" />
  </svg>
);

const KubernetesIcon: React.FC<{ cls?: string }> = ({ cls = "" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" width={20} height={20} className={cls}>
    <path d="M12 2L2 7l10 5 10-5-10-5z" />
    <path d="M2 17l10 5 10-5" />
    <path d="M2 12l10 5 10-5" />
  </svg>
);

const ClockIcon: React.FC<{ cls?: string }> = ({ cls = "" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" width={20} height={20} className={cls}>
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

/* ── Tab Definitions ──────────────────────────────────────────────── */

type TabKey = "dashboard" | "synapse" | "aks" | "schedules";

interface TabDef {
  key: TabKey;
  label: string;
  icon: React.ReactNode;
}

const tabs: TabDef[] = [
  { key: "dashboard", label: "Dashboard", icon: <ShieldIcon /> },
  { key: "synapse", label: "Synapse", icon: <SynapseIcon /> },
  { key: "aks", label: "AKS", icon: <KubernetesIcon /> },
  { key: "schedules", label: "Schedules", icon: <ClockIcon /> },
];



/* ── Main Orchestrator ────────────────────────────────────────────── */

const CompliancePage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>("dashboard");
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = useCallback(
    (message: string, type: ToastState["type"] = "success") => {
      setToast({ message, type });
      setTimeout(() => setToast(null), 5000);
    },
    [],
  );

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <ShieldIcon cls="h-8 w-8 text-att-500" />
            Compliance & Drift Detection
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Monitor infrastructure drift, verify checksums, and track compliance
            scores
          </p>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="Compliance tabs">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === tab.key
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div>
        {activeTab === "dashboard" && (
          <ComplianceDashboard onShowToast={showToast} />
        )}

        {activeTab === "synapse" && (
          <ChecksumVerificationTab onShowToast={showToast} />
        )}

        {activeTab === "aks" && (
          <AKSChecksumTab
            onShowToast={showToast}
            onNavigateToSchedules={() => setActiveTab("schedules")}
          />
        )}

        {activeTab === "schedules" && (
          <ChecksumScheduleManagement onShowToast={showToast} />
        )}
      </div>

      {/* Toast */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
};

export default CompliancePage;
