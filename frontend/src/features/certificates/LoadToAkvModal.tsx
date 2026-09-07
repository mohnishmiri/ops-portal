/**
 * Load Certificate to Azure Key Vault modal.
 *
 * Cascade dropdowns: Subscription → Resource Group → Key Vault
 * Data is served from the existing /keyvault/vaults endpoint (DB-cached).
 *
 * AKV only accepts a certificate that carries its private key, so the portal
 * sources the key material itself, in order of preference: the escrowed key
 * (kept at issuance, so it still works months later and for a second vault),
 * a live PFX export from Keyfactor, or a newly generated PFX certificate.
 * Security: PFX passwords are single-use and never logged or stored.
 */

import React, { useState } from "react";
import {
  Certificate,
  AkvUploadRequest,
  AkvUploadResult,
  certificateErrorMessage,
  useLoadCertificateToAkv,
  useRenewCertificate,
} from "../../services/certificatesApi";
import { CertificateModal, modalButton } from "./CertificateModal";
import { AkvTarget, AkvTargetPicker, isAkvTargetComplete } from "./AkvTargetPicker";

interface LoadToAkvModalProps {
  certificate: Certificate;
  /** Pre-filled base64 certificate data (e.g. from a renewal PFX). */
  certificateData?: string;
  /** Collection context used when exporting the PFX from Keyfactor. */
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

type CertificateSource = "escrow" | "existing" | "generate";

const RSA_KEY_SIZES = [2048, 3072, 4096, 8192];

/** Single-use password protecting the PFX only in transit to Key Vault. */
const generatePfxPassword = (): string => {
  const bytes = new Uint8Array(24);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
};

const AkvIcon = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

export const LoadToAkvModal: React.FC<LoadToAkvModalProps> = ({
  certificate,
  certificateData = "",
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const load = useLoadCertificateToAkv();
  const renew = useRenewCertificate();

  const [target, setTarget] = useState<AkvTarget>({
    subscriptionId: "",
    resourceGroup: "",
    vaultName: "",
    certificateNames: [],
  });
  const [result, setResult] = useState<AkvUploadResult | null>(null);

  // Certificate (private key) source
  const preSuppliedData = certificateData.trim();
  // Only Keyfactor's positive "HasPrivateKey" makes a PFX export possible; unknown
  // (never-synced) must not offer an export that Keyfactor will refuse.
  const hasPrivateKey = certificate.has_private_key === true;
  // An escrowed key is the only source that survives past issuance, so it wins
  // whenever it exists — it is what makes loading into a further vault possible.
  const hasEscrowedKey = certificate.key_escrowed === true;
  const [source, setSource] = useState<CertificateSource>(
    hasEscrowedKey ? "escrow" : hasPrivateKey ? "existing" : "generate"
  );
  const [generated, setGenerated] = useState<{ data: string; password: string; certificateId?: number } | null>(null);

  // "escrow" and "existing" need no local data: the backend reads the escrowed
  // key or exports the PFX from Keyfactor.
  const sourceReady =
    Boolean(preSuppliedData) || source === "escrow" || source === "existing" || generated !== null;
  const isValid = isAkvTargetComplete(target) && sourceReady;

  const handleGenerate = async () => {
    const password = generatePfxPassword();
    try {
      const res = await renew.mutateAsync({
        id: certificate.id,
        data: {
          mode: "pfx",
          certificate_authority: certificate.certificate_authority || undefined,
          template: certificate.template || undefined,
          collection_id: collectionId,
          password,
          // Keyfactor reports KeyType as a numeric enum, which it rejects on enrollment.
          key_type: "RSA",
          key_length: RSA_KEY_SIZES.includes(certificate.key_size) ? certificate.key_size : 4096,
        },
      });
      if (!res.pfx_base64) {
        onError("The new certificate was issued without PFX data. Try the Renew flow instead.");
        return;
      }
      setGenerated({ data: res.pfx_base64, password, certificateId: res.certificate_id });
      onSuccess("New certificate with private key generated.");
    } catch (err) {
      onError(certificateErrorMessage(err, "Failed to generate a new certificate with PFX"));
    }
  };

  const handleSubmit = async () => {
    if (!isValid) return;
    const localData = preSuppliedData || generated?.data || "";
    const localPassword = preSuppliedData ? "" : generated?.password || "";
    try {
      const uploadRequest: AkvUploadRequest = {
        subscription_id: target.subscriptionId.trim(),
        resource_group: target.resourceGroup.trim(),
        vault_name: target.vaultName.trim(),
        certificate_names: target.certificateNames.map((n) => n.trim()),
        ...(localData ? { certificate_data: localData } : {}),
        ...(localPassword ? { certificate_password: localPassword } : {}),
        ...(collectionId ? { collection_id: collectionId } : {}),
        // Only meaningful when no local PFX is attached. "escrow" fails loudly
        // rather than silently falling back to a Keyfactor export that would
        // succeed only for key-archived certificates.
        ...(localData ? {} : { key_source: source === "escrow" ? ("escrow" as const) : ("keyfactor" as const) }),
      };
      const res = await load.mutateAsync({ id: generated?.certificateId ?? certificate.id, data: uploadRequest });
      setResult(res);
      onSuccess(
        `Certificate loaded to AKV: ${target.vaultName.trim()} (${res.certificates.length} entr${
          res.certificates.length === 1 ? "y" : "ies"
        })`
      );
    } catch (err) {
      // 409 = Keyfactor holds no exportable key, so only a freshly issued PFX can work.
      if ((err as { response?: { status?: number } })?.response?.status === 409) setSource("generate");
      onError(certificateErrorMessage(err, "Failed to load certificate into Azure Key Vault"));
    }
  };
  if (result) {
    return (
      <CertificateModal
        title="Loaded to Azure Key Vault"
        onClose={onClose}
        footer={
          <button type="button" className={modalButton.primary} onClick={onClose}>Close</button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-xl border border-green-200 bg-green-50 p-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-green-100 text-green-600">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
            </div>
            <div>
              <p className="font-semibold text-green-900">Certificate Successfully Loaded</p>
              <p className="text-sm text-green-700">
                Imported into {result.certificates.length} Key Vault entr
                {result.certificates.length === 1 ? "y" : "ies"}.
              </p>
            </div>
          </div>
          <dl className="grid grid-cols-1 gap-3 rounded-xl border border-att-100 bg-att-50/30 p-4 text-sm">
            <div><dt className="text-xs font-semibold uppercase text-gray-400">Key Vault</dt><dd className="font-mono text-gray-800">{result.vault_name}</dd></div>
            <div>
              <dt className="text-xs font-semibold uppercase text-gray-400">Certificates</dt>
              <dd className="space-y-1">
                {result.certificates.map((c) => (
                  <p key={c.certificate_name} className="font-mono text-gray-800">{c.certificate_name}</p>
                ))}
              </dd>
            </div>
            {result.key_source && (
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-400">Key Source</dt>
                <dd className="text-gray-800">
                  {result.key_source === "escrow"
                    ? "Escrowed key — loadable into further vaults at any time"
                    : result.key_source === "keyfactor"
                      ? "Live Keyfactor PFX export"
                      : "Newly issued PFX"}
                </dd>
              </div>
            )}
          </dl>
          {result.failed.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">
              <p className="font-semibold text-amber-900">Some entries were not updated</p>
              {result.failed.map((f) => (
                <p key={f.certificate_name} className="mt-1 text-xs text-amber-800">
                  <span className="font-mono">{f.certificate_name}</span>: {f.error}
                </p>
              ))}
            </div>
          )}
        </div>
      </CertificateModal>
    );
  }

  return (
    <CertificateModal
      title="Load Certificate to Azure Key Vault"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={onClose}>Cancel</button>
          <button
            type="button"
            className={modalButton.primary}
            disabled={load.isPending || !isValid}
            onClick={handleSubmit}
          >
            {load.isPending ? "Loading…" : "Load to AKV"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* Certificate Info */}
        <div className="rounded-lg border border-att-100 bg-att-50/40 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-att-700">
            {AkvIcon}
            <span className="font-semibold">{certificate.common_name || `Certificate #${certificate.id}`}</span>
          </div>
          {certificate.thumbprint && (
            <p className="mt-1 font-mono text-xs text-gray-500">{certificate.thumbprint}</p>
          )}
        </div>

        <AkvTargetPicker
          commonName={certificate.common_name}
          sans={certificate.sans}
          thumbprint={certificate.thumbprint}
          onChange={setTarget}
        />

        {/* Certificate material (private key) */}
        {preSuppliedData ? (
          <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
            Using the PFX from the completed renewal. No certificate data entry is needed.
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Certificate Source</p>
            <p className="text-xs text-gray-500">
              Azure Key Vault requires a certificate with its private key. The portal supplies the key
              material — nothing needs to be pasted.
            </p>

            {!hasEscrowedKey && !hasPrivateKey && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
                No escrowed key for this certificate, and Keyfactor has no retrievable private key
                either, so it cannot be exported as a PFX. This is normal even just after a renewal:
                Keyfactor returns the PFX only at the moment of issuance unless key archival is
                enabled on the template. Generate a new certificate with PFX below — with escrow
                enabled its key is kept, so it can then be loaded into further vaults later.
              </div>
            )}

            {hasEscrowedKey && (
              <label
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                  source === "escrow" ? "border-att-300 bg-att-50/40" : "border-gray-200"
                }`}
              >
                <input
                  type="radio"
                  name="akv-cert-source"
                  className="mt-1"
                  checked={source === "escrow"}
                  onChange={() => setSource("escrow")}
                />
                <span>
                  <span className="block text-sm font-medium text-att-700">Use escrowed key</span>
                  <span className="block text-xs text-gray-500">
                    Reads the private key captured when this certificate was issued. Works any time
                    and any number of times, so the same certificate can be loaded into each
                    environment&apos;s vault.
                  </span>
                </span>
              </label>
            )}

            <label
              className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                source === "existing" ? "border-att-300 bg-att-50/40" : "border-gray-200"
              } ${hasPrivateKey ? "" : "cursor-not-allowed opacity-60"}`}
            >
              <input
                type="radio"
                name="akv-cert-source"
                className="mt-1"
                checked={source === "existing"}
                disabled={!hasPrivateKey}
                onChange={() => setSource("existing")}
              />
              <span>
                <span className="block text-sm font-medium text-att-700">Use existing certificate</span>
                <span className="block text-xs text-gray-500">
                  {hasPrivateKey
                    ? "Exports the PFX from Keyfactor. Works only while Keyfactor still holds an exportable key (key archival)."
                    : "Unavailable — Keyfactor cannot export a private key for this certificate."}
                </span>
              </span>
            </label>

            <label
              className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                source === "generate" ? "border-att-300 bg-att-50/40" : "border-gray-200"
              }`}
            >
              <input
                type="radio"
                name="akv-cert-source"
                className="mt-1"
                checked={source === "generate"}
                onChange={() => setSource("generate")}
              />
              <span>
                <span className="block text-sm font-medium text-att-700">Generate new certificate with PFX</span>
                <span className="block text-xs text-gray-500">
                  Issues a new certificate with a private key via PFX renewal, then loads it.
                </span>
              </span>
            </label>

            {source === "generate" && (
              <div className="rounded-lg border border-att-100 bg-att-50/30 p-3">
                {generated ? (
                  <p className="text-sm text-green-700">
                    New certificate with private key is ready to load.
                  </p>
                ) : (
                  <>
                    <button
                      type="button"
                      className={modalButton.secondary}
                      disabled={renew.isPending}
                      onClick={handleGenerate}
                    >
                      {renew.isPending ? "Generating…" : "Generate certificate with PFX"}
                    </button>
                    <p className="mt-2 text-xs text-gray-500">
                      Uses CA "{certificate.certificate_authority || "—"}" and template "
                      {certificate.template || "—"}". The PFX password is single-use and never stored.
                    </p>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </CertificateModal>
  );
};
