/**
 * Download Certificate modal — matches Keyfactor Command download dialog.
 *
 * Formats: PEM, CER, CRT, DER, P7B, PFX/PKCS#12.
 * PFX downloads require WRITE role and a password (min 12 chars).
 * Options: Include Chain toggle, Chain Order, Include Subject Header toggle.
 */

import React, { useState } from "react";
import {
  Certificate,
  DOWNLOAD_FORMATS,
  DownloadFormat,
  ChainOrder,
  certificateErrorMessage,
  useDownloadCertificate,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";

interface DownloadCertificateModalProps {
  certificate: Certificate;
  collectionId?: number;
  canWrite?: boolean;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

const FORMAT_DESCRIPTIONS: Record<DownloadFormat, string> = {
  PEM: "Base64-encoded, human-readable",
  CER: "DER or PEM-encoded certificate",
  CRT: "Base64-encoded certificate",
  DER: "Binary DER-encoded certificate",
  P7B: "PKCS#7 certificate chain",
  PFX: "PKCS#12 — includes private key (requires password)",
};

export const DownloadCertificateModal: React.FC<DownloadCertificateModalProps> = ({
  certificate,
  collectionId,
  canWrite = false,
  onClose,
  onSuccess,
  onError,
}) => {
  const download = useDownloadCertificate();
  const [format, setFormat] = useState<DownloadFormat>("PEM");
  const [includeChain, setIncludeChain] = useState(true);
  const [chainOrder, setChainOrder] = useState<ChainOrder>("EndEntityFirst");
  const [includeSubjectHeader, setIncludeSubjectHeader] = useState(true);
  const [pfxPassword, setPfxPassword] = useState("");
  const [showPfxPassword, setShowPfxPassword] = useState(false);

  const isPfx = format === "PFX";
  const pfxPasswordValid = !isPfx || pfxPassword.trim().length >= 12;
  const canDownloadPfx = isPfx ? canWrite : true;

  // PFX needs WRITE role and a private key the backend can reach: either one
  // Keyfactor still holds, or the escrowed copy kept at issuance.
  const isEscrowed = certificate.key_escrowed === true;
  const hasPfxAvailable = isEscrowed || certificate.has_private_key !== false;
  const availableFormats = DOWNLOAD_FORMATS.filter(
    (f) => f !== "PFX" || (canWrite && hasPfxAvailable)
  );

  const handleDownload = async () => {
    if (!canDownloadPfx) return;
    try {
      const blob = await download.mutateAsync({
        id: certificate.id,
        data: {
          file_format: format,
          include_chain: isPfx ? false : includeChain,
          chain_order: chainOrder,
          include_subject_header: isPfx ? false : includeSubjectHeader,
          collection_id: collectionId,
          ...(isPfx ? { pfx_password: pfxPassword } : {}),
        },
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${certificate.common_name || "certificate"}.${format.toLowerCase()}`;
      a.click();
      URL.revokeObjectURL(url);
      onSuccess(`Certificate downloaded as ${format}`);
      onClose();
    } catch (err) {
      onError(certificateErrorMessage(err, "Download failed"));
    }
  };

  return (
    <CertificateModal
      title="Download Certificate"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={onClose}>
            CANCEL
          </button>
          <button
            type="button"
            className={modalButton.primary}
            disabled={download.isPending || !pfxPasswordValid || !canDownloadPfx}
            onClick={handleDownload}
          >
            {download.isPending ? "Downloading…" : "DOWNLOAD"}
          </button>
        </>
      }
    >
      <div className="space-y-5">
        {/* Format selector */}
        <div>
          <label className={fieldLabel} htmlFor="dl-format">
            File Format
          </label>
          <select
            id="dl-format"
            className={fieldInput}
            value={format}
            onChange={(e) => {
              const newFmt = e.target.value as DownloadFormat;
              setFormat(newFmt);
              if (newFmt !== "PFX") setPfxPassword("");
            }}
          >
            {availableFormats.map((f) => (
              <option key={f} value={f}>
                {f} — {FORMAT_DESCRIPTIONS[f]}
              </option>
            ))}
          </select>
          {!canWrite && hasPfxAvailable && (
            <p className="mt-1 text-xs text-amber-600">
              PFX (private key) format requires WRITE permission.
            </p>
          )}
          {!hasPfxAvailable && (
            <p className="mt-1 text-xs text-gray-400">
              PFX format is not available — no private key is retrievable for this certificate.
              Renewing it through the portal escrows the key and enables PFX download.
            </p>
          )}
        </div>

        {/* PFX password */}
        {isPfx && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
            <div className="flex items-start gap-2">
              <svg className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <p className="text-xs text-amber-800">
                <strong>PFX/PKCS#12</strong> contains the private key. Set a strong password and store it securely. The password is never logged.
                {isEscrowed && " The escrowed key is re-protected with this password, so it is the one that opens the file."}
              </p>
            </div>
            <div>
              <label className={fieldLabel} htmlFor="pfx-password">
                PFX Password <span className="text-red-500">*</span> (min 12 characters)
              </label>
              <div className="relative">
                <input
                  id="pfx-password"
                  type={showPfxPassword ? "text" : "password"}
                  className={fieldInput + " pr-10"}
                  value={pfxPassword}
                  onChange={(e) => setPfxPassword(e.target.value)}
                  placeholder="Enter a strong password"
                  minLength={12}
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600"
                  onClick={() => setShowPfxPassword((v) => !v)}
                  tabIndex={-1}
                >
                  {showPfxPassword ? (
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" /><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" /><line x1="1" y1="1" x2="23" y2="23" /></svg>
                  ) : (
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
                  )}
                </button>
              </div>
              {pfxPassword.length > 0 && pfxPassword.trim().length < 12 && (
                <p className="mt-1 text-xs text-red-600">Password must be at least 12 characters.</p>
              )}
            </div>
          </div>
        )}

        {/* Chain options — not applicable for PFX */}
        {!isPfx && (
          <>
            <div className="border-t border-att-100 pt-4">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-600">
                Chain Options
              </h3>
              <label className="flex items-center gap-3 cursor-pointer">
                <div
                  role="switch"
                  aria-checked={includeChain}
                  tabIndex={0}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    includeChain ? "bg-att-500" : "bg-gray-300"
                  }`}
                  onClick={() => setIncludeChain(!includeChain)}
                  onKeyDown={(e) => e.key === "Enter" && setIncludeChain(!includeChain)}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      includeChain ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </div>
                <span className="text-sm text-gray-700">Include Chain</span>
              </label>
            </div>

            {includeChain && (
              <div className="pl-4">
                <span className={fieldLabel}>Chain Order</span>
                <div className="mt-1 flex gap-4">
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="radio"
                      name="chain-order"
                      checked={chainOrder === "EndEntityFirst"}
                      onChange={() => setChainOrder("EndEntityFirst")}
                      className="accent-att-500"
                    />
                    End Entity First
                  </label>
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="radio"
                      name="chain-order"
                      checked={chainOrder === "RootFirst"}
                      onChange={() => setChainOrder("RootFirst")}
                      className="accent-att-500"
                    />
                    Root First
                  </label>
                </div>
              </div>
            )}

            <div className="border-t border-att-100 pt-4">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-600">
                Additional Options
              </h3>
              <label className="flex items-center gap-3 cursor-pointer">
                <div
                  role="switch"
                  aria-checked={includeSubjectHeader}
                  tabIndex={0}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    includeSubjectHeader ? "bg-att-500" : "bg-gray-300"
                  }`}
                  onClick={() => setIncludeSubjectHeader(!includeSubjectHeader)}
                  onKeyDown={(e) => e.key === "Enter" && setIncludeSubjectHeader(!includeSubjectHeader)}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      includeSubjectHeader ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </div>
                <span className="text-sm text-gray-700">Include Subject Header</span>
              </label>
            </div>
          </>
        )}
      </div>
    </CertificateModal>
  );
};
