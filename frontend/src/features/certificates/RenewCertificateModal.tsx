/**
 * Renew/Reissue Certificate modal — multi-step flow.
 *
 * Step 1: Select renewal mode (one-click, PFX, or CSR)
 * Step 2 (optional): Configure PFX or CSR parameters
 * Step 3: Show renewal result + offer Load to AKV
 *
 * If renewal succeeds but AKV upload fails, clearly separates the two outcomes
 * and allows AKV upload retry without re-renewing.
 */

import React, { useState } from "react";
import {
  Certificate,
  EnrollResult,
  AkvUploadRequest,
  certificateErrorMessage,
  useRenewCertificate,
  useLoadCertificateToAkv,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";
import { AkvTarget, AkvTargetPicker, isAkvTargetComplete } from "./AkvTargetPicker";
import { formatDate } from "../../utils/dateFormat";

type RenewMode = "select" | "one_click" | "pfx" | "csr";
type Step = "configure" | "result";

interface RenewCertificateModalProps {
  certificate: Certificate;
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

// ── AKV upload sub-form (with cascade Subscription → RG → Vault) ────────────

interface AkvFormProps {
  certificateId: number;
  commonName: string;
  sans: string[];
  /** Thumbprint of the certificate being replaced — AKV still holds that one. */
  thumbprint: string;
  renewalResult: EnrollResult;
  /** Password the PFX was renewed with; required to import that PFX. */
  pfxPassword?: string;
  onSuccess: () => void;
  onFailure: (msg: string) => void;
}

const AkvUploadForm: React.FC<AkvFormProps> = ({
  certificateId,
  commonName,
  sans,
  thumbprint,
  renewalResult,
  pfxPassword,
  onSuccess,
  onFailure,
}) => {
  const load = useLoadCertificateToAkv();
  const [target, setTarget] = useState<AkvTarget>({
    subscriptionId: "",
    resourceGroup: "",
    vaultName: "",
    certificateNames: [],
  });

  const certData = renewalResult.pfx_base64 || renewalResult.certificate || "";
  const isValid = isAkvTargetComplete(target) && Boolean(certData);

  const handleUpload = async () => {
    if (!isValid) return;
    try {
      await load.mutateAsync({
        id: renewalResult.certificate_id ?? certificateId,
        data: {
          subscription_id: target.subscriptionId.trim(),
          resource_group: target.resourceGroup.trim(),
          vault_name: target.vaultName.trim(),
          certificate_names: target.certificateNames.map((n) => n.trim()),
          certificate_data: certData,
          ...(renewalResult.pfx_base64 && pfxPassword ? { certificate_password: pfxPassword } : {}),
        },
      });
      onSuccess();
    } catch (err) {
      onFailure(certificateErrorMessage(err, "Failed to load certificate into Azure Key Vault"));
    }
  };

  if (!certData) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
        Certificate data is not available for AKV upload. Download the certificate and upload manually.
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-xl border border-att-100 bg-att-50/30 p-4">
      <AkvTargetPicker
        commonName={commonName}
        sans={sans}
        thumbprint={thumbprint}
        onChange={setTarget}
      />
      <button
        type="button"
        className={modalButton.primary + " w-full"}
        disabled={load.isPending || !isValid}
        onClick={handleUpload}
      >
        {load.isPending ? "Loading to AKV…" : "Load to Azure Key Vault"}
      </button>
    </div>
  );
};

// ── Main component ─────────────────────────────────────────────────────

export const RenewCertificateModal: React.FC<RenewCertificateModalProps> = ({
  certificate,
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const renew = useRenewCertificate();
  const [mode, setMode] = useState<RenewMode>("select");
  const [step, setStep] = useState<Step>("configure");
  const [ca, setCa] = useState(certificate.certificate_authority || "");
  const [template, setTemplate] = useState(certificate.template || "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [keyLength, setKeyLength] = useState(4096);
  const [ownerRoleName, setOwnerRoleName] = useState("");
  const [csr, setCsr] = useState("");
  const [renewalResult, setRenewalResult] = useState<EnrollResult | null>(null);
  const [akvStatus, setAkvStatus] = useState<"idle" | "success" | "failed">("idle");
  const [akvError, setAkvError] = useState("");

  const pfxPasswordValid = password.trim().length >= 12;

  const handleSubmit = async (submitMode: "one_click" | "pfx" | "csr") => {
    try {
      const result = await renew.mutateAsync({
        id: certificate.id,
        data: {
          mode: submitMode,
          certificate_authority: ca.trim() || undefined,
          template: template.trim() || undefined,
          collection_id: collectionId,
          ...(submitMode === "pfx"
            ? { password, key_type: "RSA", key_length: keyLength, ...(ownerRoleName.trim() ? { owner_role_name: ownerRoleName.trim() } : {}) }
            : {}),
          ...(submitMode === "csr" ? { csr: csr.trim() } : {}),
        },
      });
      setRenewalResult(result);
      setStep("result");
      onSuccess(`Certificate ${certificate.common_name} renewed successfully`);
    } catch (err) {
      onError(certificateErrorMessage(err, "Renewal failed"));
    }
  };

  // ── Result / AKV upload step ───────────────────────────────────────────
  if (step === "result" && renewalResult) {
    return (
      <CertificateModal
        title="Renewal Result"
        onClose={onClose}
        footer={
          <button type="button" className={modalButton.primary} onClick={onClose}>Done</button>
        }
      >
        <div className="space-y-4">
          {/* Renewal success card */}
          <div className="flex items-start gap-3 rounded-xl border border-green-200 bg-green-50 p-4">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-green-100 text-green-600">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
            </div>
            <div>
              <p className="font-semibold text-green-900">Certificate Renewed Successfully</p>
              <p className="text-sm text-green-700">{certificate.common_name}</p>
            </div>
          </div>

          {/* Renewal details */}
          <dl className="grid grid-cols-2 gap-3 rounded-xl border border-att-100 bg-att-50/30 p-4 text-sm">
            {renewalResult.thumbprint && (
              <div className="col-span-2">
                <dt className="text-xs font-semibold uppercase text-gray-400">New Thumbprint</dt>
                <dd className="font-mono text-xs text-gray-700 break-all">{renewalResult.thumbprint}</dd>
              </div>
            )}
            {renewalResult.serial_number && (
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-400">Serial Number</dt>
                <dd className="font-mono text-xs text-gray-700">{renewalResult.serial_number}</dd>
              </div>
            )}
            {renewalResult.certificate_id != null && (
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-400">Keyfactor ID</dt>
                <dd className="font-mono text-xs text-gray-700">{renewalResult.certificate_id}</dd>
              </div>
            )}
          </dl>

          {/* AKV upload status */}
          {akvStatus === "success" && (
            <div className="flex items-start gap-3 rounded-xl border border-green-200 bg-green-50 p-3">
              <svg className="mt-0.5 h-5 w-5 shrink-0 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
              <div>
                <span className="text-sm font-medium text-green-800">Certificate loaded to Azure Key Vault successfully.</span>
                {renewalResult.key_escrowed && (
                  <p className="mt-1 text-xs text-green-700">
                    The private key is escrowed, so this certificate can be loaded into further
                    vaults at any time from the certificate&apos;s Load to AKV action — no second
                    renewal needed.
                  </p>
                )}
              </div>
            </div>
          )}

          {akvStatus === "failed" && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-2">
              <div className="flex items-center gap-2 text-amber-800">
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
                <span className="font-semibold text-sm">Certificate renewed successfully, but loading into Azure Key Vault failed.</span>
              </div>
              <p className="text-xs text-amber-700">{akvError}</p>
            </div>
          )}

          {/* AKV upload form (shown when not yet succeeded) */}
          {akvStatus !== "success" && (
            <>
              <div className="border-t border-att-100 pt-4">
                <p className="mb-3 text-sm font-semibold text-gray-700">
                  {akvStatus === "failed" ? "Retry: Load to Azure Key Vault" : "Load to Azure Key Vault (optional)"}
                </p>
                <AkvUploadForm
                  certificateId={certificate.id}
                  commonName={certificate.common_name}
                  sans={certificate.sans}
                  thumbprint={certificate.thumbprint}
                  renewalResult={renewalResult}
                  pfxPassword={password}
                  onSuccess={() => setAkvStatus("success")}
                  onFailure={(msg) => { setAkvStatus("failed"); setAkvError(msg); }}
                />
              </div>
            </>
          )}
        </div>
      </CertificateModal>
    );
  }

  // ── Mode selection ─────────────────────────────────────────────────────
  if (mode === "select") {
    return (
      <CertificateModal title="Renew/Reissue Certificate" onClose={onClose}>
        <div className="space-y-4">
          {/* Certificate summary */}
          <div className="rounded-lg border border-att-100 bg-att-50/40 p-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div><span className="text-xs font-semibold uppercase text-gray-400">Common Name</span><p className="font-medium text-gray-800">{certificate.common_name}</p></div>
              <div><span className="text-xs font-semibold uppercase text-gray-400">Expires</span><p className="font-medium text-gray-800">{formatDate(certificate.not_after)}</p></div>
              <div><span className="text-xs font-semibold uppercase text-gray-400">Issuer</span><p className="text-xs text-gray-600 truncate">{certificate.certificate_authority || certificate.issuer_dn}</p></div>
              <div><span className="text-xs font-semibold uppercase text-gray-400">Thumbprint</span><p className="font-mono text-xs text-gray-600 truncate">{certificate.thumbprint}</p></div>
            </div>
          </div>

          <p className="text-sm text-gray-700">Select the renewal method:</p>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              className="rounded-lg border-2 border-att-500 bg-white px-5 py-2.5 text-sm font-semibold text-att-700 hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={renew.isPending}
              onClick={() => handleSubmit("one_click")}
            >
              {renew.isPending ? "Renewing…" : "ONE-CLICK RENEW"}
            </button>
            <button
              type="button"
              className="rounded-lg border-2 border-gray-300 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
              onClick={() => setMode("pfx")}
            >
              CONFIGURE WITH PFX
            </button>
            <button
              type="button"
              className="rounded-lg border-2 border-gray-300 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
              onClick={() => setMode("csr")}
            >
              CONFIGURE WITH CSR
            </button>
            <button
              type="button"
              className="rounded-lg border-2 border-gray-300 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
              onClick={onClose}
            >
              CANCEL
            </button>
          </div>
        </div>
      </CertificateModal>
    );
  }

  // ── PFX configuration ──────────────────────────────────────────────────
  if (mode === "pfx") {
    return (
      <CertificateModal
        title="Renew with PFX"
        onClose={onClose}
        footer={
          <>
            <button type="button" className={modalButton.secondary} onClick={() => setMode("select")}>Back</button>
            <button type="button" className={modalButton.primary} disabled={renew.isPending || !pfxPasswordValid} onClick={() => handleSubmit("pfx")}>
              {renew.isPending ? "Renewing…" : "Renew"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            Renewing <span className="font-semibold">{certificate.common_name}</span> with a new PFX key pair.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={fieldLabel}>Certificate Authority</label>
              <input className={fieldInput} value={ca} onChange={(e) => setCa(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel}>Template</label>
              <input className={fieldInput} value={template} onChange={(e) => setTemplate(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel}>Key Size</label>
              <select className={fieldInput} value={keyLength} onChange={(e) => setKeyLength(Number(e.target.value))}>
                <option value={2048}>2048</option>
                <option value={3072}>3072</option>
                <option value={4096}>4096</option>
              </select>
            </div>
            <div>
              <label className={fieldLabel} htmlFor="renew-pfx-password">Password (min 12 chars) <span className="text-red-500">*</span></label>
              <div className="relative">
                <input
                  id="renew-pfx-password"
                  type={showPassword ? "text" : "password"}
                  className={fieldInput + " pr-10"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="PFX password"
                  minLength={12}
                  autoComplete="new-password"
                  required
                />
                <button type="button" className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600" onClick={() => setShowPassword((v) => !v)} tabIndex={-1}>
                  {showPassword ? (
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" /><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" /><line x1="1" y1="1" x2="23" y2="23" /></svg>
                  ) : (
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
                  )}
                </button>
              </div>
              {password.length > 0 && !pfxPasswordValid && (
                <p className="mt-1 text-xs text-red-600">Password must be at least 12 characters.</p>
              )}
            </div>
            <div className="col-span-2">
              <label className={fieldLabel} htmlFor="renew-owner-role">Owner Role Name</label>
              <input id="renew-owner-role" className={fieldInput} value={ownerRoleName} onChange={(e) => setOwnerRoleName(e.target.value)} placeholder="Uses the current certificate owner when blank" />
            </div>
          </div>
        </div>
      </CertificateModal>
    );
  }

  // ── CSR configuration ──────────────────────────────────────────────────
  return (
    <CertificateModal
      title="Renew with CSR"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={() => setMode("select")}>Back</button>
          <button type="button" className={modalButton.primary} disabled={renew.isPending || !csr.trim()} onClick={() => handleSubmit("csr")}>
            {renew.isPending ? "Renewing…" : "Renew"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-gray-700">
          Paste a new CSR to renew <span className="font-semibold">{certificate.common_name}</span>.
        </p>
        <div>
          <label className={fieldLabel}>Certificate Authority</label>
          <input className={fieldInput} value={ca} onChange={(e) => setCa(e.target.value)} />
        </div>
        <div>
          <label className={fieldLabel}>PEM-encoded CSR</label>
          <textarea className={`${fieldInput} h-32 font-mono text-xs`} value={csr} onChange={(e) => setCsr(e.target.value)} placeholder="-----BEGIN CERTIFICATE REQUEST-----" />
        </div>
      </div>
    </CertificateModal>
  );
};
