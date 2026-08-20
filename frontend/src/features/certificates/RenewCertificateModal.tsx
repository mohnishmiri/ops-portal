/**
 * Renew/Reissue Certificate modal — matches Keyfactor Command renewal dialog.
 *
 * Offers three renewal modes:
 * - CONTINUE (one-click renewal using existing cert parameters)
 * - CONFIGURE WITH PFX (opens PFX config options)
 * - CONFIGURE WITH CSR (paste a new CSR)
 */

import React, { useState } from "react";
import {
  Certificate,
  certificateErrorMessage,
  useRenewCertificate,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";

type RenewMode = "select" | "one_click" | "pfx" | "csr";

interface RenewCertificateModalProps {
  certificate: Certificate;
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

export const RenewCertificateModal: React.FC<RenewCertificateModalProps> = ({
  certificate,
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const renew = useRenewCertificate();
  const [mode, setMode] = useState<RenewMode>("select");
  const [ca, setCa] = useState(certificate.certificate_authority || "");
  const [template, setTemplate] = useState(certificate.template || "");
  const [password, setPassword] = useState("");
  const [keyType] = useState("RSA");
  const [keyLength, setKeyLength] = useState(4096);
  const [ownerRoleName, setOwnerRoleName] = useState("");
  const [csr, setCsr] = useState("");
  const pfxPasswordValid = password.trim().length >= 12;

  const handleSubmit = async (submitMode: "one_click" | "pfx" | "csr") => {
    try {
      await renew.mutateAsync({
        id: certificate.id,
        data: {
          mode: submitMode,
          certificate_authority: ca.trim() || undefined,
          template: template.trim() || undefined,
          collection_id: collectionId,
          ...(submitMode === "pfx"
            ? {
                password,
                key_type: keyType,
                key_length: keyLength,
                ...(ownerRoleName.trim() ? { owner_role_name: ownerRoleName.trim() } : {}),
              }
            : {}),
          ...(submitMode === "csr" ? { csr: csr.trim() } : {}),
        },
      });
      onSuccess(`Certificate ${certificate.id} renewed`);
      onClose();
    } catch (err) {
      onError(certificateErrorMessage(err, "Renewal failed"));
    }
  };

  // Mode selection view (matches Keyfactor's "Renew/Reissue Certificate" dialog)
  if (mode === "select") {
    return (
      <CertificateModal title="Renew/Reissue Certificate" onClose={onClose}>
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            One click renewal is available for this certificate.
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              className="rounded-lg border-2 border-att-500 bg-white px-5 py-2.5 text-sm font-semibold text-att-700 hover:bg-att-50"
              disabled={renew.isPending}
              onClick={() => handleSubmit("one_click")}
            >
              {renew.isPending ? "Renewing…" : "CONTINUE"}
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

  // PFX configuration
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
              <label className={fieldLabel} htmlFor="renew-pfx-password">Password (min 12 chars)</label>
              <input id="renew-pfx-password" type="password" className={fieldInput} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="PFX password" minLength={12} required />
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

  // CSR configuration
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
