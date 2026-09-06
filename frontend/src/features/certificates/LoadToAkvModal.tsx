/**
 * Load Certificate to Azure Key Vault modal.
 *
 * Cascade dropdowns: Subscription → Resource Group → Key Vault
 * Data is served from the existing /keyvault/vaults endpoint (DB-cached).
 * Security: certificate_password is never logged or stored.
 */

import React, { useState, useMemo } from "react";
import {
  Certificate,
  AkvUploadRequest,
  AkvUploadResult,
  certificateErrorMessage,
  useLoadCertificateToAkv,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";
import { useSubscriptionScope } from "../../contexts/SubscriptionContext";
import { useKeyVaults } from "../../services/costApi";

interface LoadToAkvModalProps {
  certificate: Certificate;
  /** Pre-filled base64 certificate data (e.g. from a renewal PFX). */
  certificateData?: string;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

const AkvIcon = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

export const LoadToAkvModal: React.FC<LoadToAkvModalProps> = ({
  certificate,
  certificateData = "",
  onClose,
  onSuccess,
  onError,
}) => {
  const load = useLoadCertificateToAkv();
  const { effectiveSubscriptionIds, availableSubscriptions } = useSubscriptionScope();
  const { data: allVaults = [], isLoading: vaultsLoading } = useKeyVaults();

  // Cascade selection state
  const [selectedSubId, setSelectedSubId] = useState("");
  const [selectedRg, setSelectedRg] = useState("");
  const [selectedVaultName, setSelectedVaultName] = useState("");

  // Form fields (auto-populated from cascade selection)
  const [subscriptionId, setSubscriptionId] = useState("");
  const [resourceGroup, setResourceGroup] = useState("");
  const [vaultName, setVaultName] = useState("");
  const [certName, setCertName] = useState(
    (certificate.common_name || "").replace(/[^a-zA-Z0-9-]/g, "-").replace(/^-+|-+$/g, "").slice(0, 127)
  );
  const [certData, setCertData] = useState(certificateData);
  const [certPassword, setCertPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [result, setResult] = useState<AkvUploadResult | null>(null);

  // Filter vaults to effective subscription scope
  const scopedVaults = useMemo(() => {
    if (!effectiveSubscriptionIds.length) return allVaults;
    return allVaults.filter((v) => effectiveSubscriptionIds.includes(v.subscription_id));
  }, [allVaults, effectiveSubscriptionIds]);

  // Unique subscriptions from scoped vaults (enriched with name from SubscriptionContext)
  const uniqueSubscriptions = useMemo(() => {
    const seen = new Set<string>();
    const subs: { id: string; name: string }[] = [];
    for (const v of scopedVaults) {
      if (v.subscription_id && !seen.has(v.subscription_id)) {
        seen.add(v.subscription_id);
        const found = availableSubscriptions.find((s) => s.subscription_id === v.subscription_id);
        subs.push({ id: v.subscription_id, name: found?.subscription_name || v.subscription_id });
      }
    }
    return subs.sort((a, b) => a.name.localeCompare(b.name));
  }, [scopedVaults, availableSubscriptions]);

  // Unique RGs for selected subscription
  const filteredRgs = useMemo(() => {
    if (!selectedSubId) return [];
    const seen = new Set<string>();
    const rgs: string[] = [];
    for (const v of scopedVaults) {
      if (v.subscription_id === selectedSubId && v.resource_group && !seen.has(v.resource_group)) {
        seen.add(v.resource_group);
        rgs.push(v.resource_group);
      }
    }
    return rgs.sort();
  }, [scopedVaults, selectedSubId]);

  // Vaults for selected subscription + RG
  const filteredVaults = useMemo(() => {
    if (!selectedSubId || !selectedRg) return [];
    return scopedVaults
      .filter((v) => v.subscription_id === selectedSubId && v.resource_group === selectedRg)
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [scopedVaults, selectedSubId, selectedRg]);

  // Cascade handlers
  const handleSubChange = (subId: string) => {
    setSelectedSubId(subId);
    setSelectedRg("");
    setSelectedVaultName("");
    setSubscriptionId(subId);
    setResourceGroup("");
    setVaultName("");
  };

  const handleRgChange = (rg: string) => {
    setSelectedRg(rg);
    setSelectedVaultName("");
    setResourceGroup(rg);
    setVaultName("");
  };

  const handleVaultChange = (vName: string) => {
    setSelectedVaultName(vName);
    setVaultName(vName);
  };

  const certNameValid = !certName || /^[a-zA-Z0-9-]+$/.test(certName.trim());
  const isValid =
    subscriptionId.trim() &&
    resourceGroup.trim() &&
    vaultName.trim() &&
    certName.trim() &&
    certNameValid &&
    certData.trim();

  const handleSubmit = async () => {
    if (!isValid) return;
    try {
      const uploadRequest: AkvUploadRequest = {
        subscription_id: subscriptionId.trim(),
        resource_group: resourceGroup.trim(),
        vault_name: vaultName.trim(),
        certificate_name: certName.trim(),
        certificate_data: certData.trim(),
        ...(certPassword ? { certificate_password: certPassword } : {}),
      };
      const res = await load.mutateAsync({ id: certificate.id, data: uploadRequest });
      setResult(res);
      onSuccess(`Certificate loaded to AKV: ${vaultName.trim()}/${certName.trim()}`);
    } catch (err) {
      onError(certificateErrorMessage(err, "Failed to load certificate into Azure Key Vault"));
    }
  };

  // Success view
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
              <p className="text-sm text-green-700">The certificate was imported into Azure Key Vault.</p>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-3 rounded-xl border border-att-100 bg-att-50/30 p-4 text-sm">
            <div><dt className="text-xs font-semibold uppercase text-gray-400">Key Vault</dt><dd className="font-mono text-gray-800">{result.vault_name}</dd></div>
            <div><dt className="text-xs font-semibold uppercase text-gray-400">Certificate Name</dt><dd className="font-mono text-gray-800">{result.certificate_name}</dd></div>
            <div><dt className="text-xs font-semibold uppercase text-gray-400">Status</dt><dd><span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">Active</span></dd></div>
            {result.akv_id && <div className="col-span-2"><dt className="text-xs font-semibold uppercase text-gray-400">AKV Resource ID</dt><dd className="break-all font-mono text-xs text-gray-600">{result.akv_id}</dd></div>}
          </dl>
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

        {/* Cascade: Subscription → RG → Vault */}
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Target Azure Key Vault</p>

          {vaultsLoading ? (
            <p className="text-sm text-gray-400">Loading available Key Vaults…</p>
          ) : scopedVaults.length === 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
              No Key Vaults found in your subscription scope. Enter the details manually below.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {/* Subscription */}
              <div>
                <label className={fieldLabel} htmlFor="akv-sub-dd">Subscription</label>
                <select
                  id="akv-sub-dd"
                  className={fieldInput}
                  value={selectedSubId}
                  onChange={(e) => handleSubChange(e.target.value)}
                >
                  <option value="">Select subscription…</option>
                  {uniqueSubscriptions.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>

              {/* Resource Group */}
              <div>
                <label className={fieldLabel} htmlFor="akv-rg-dd">Resource Group</label>
                <select
                  id="akv-rg-dd"
                  className={fieldInput}
                  value={selectedRg}
                  onChange={(e) => handleRgChange(e.target.value)}
                  disabled={!selectedSubId}
                >
                  <option value="">{selectedSubId ? "Select resource group…" : "Select subscription first"}</option>
                  {filteredRgs.map((rg) => (
                    <option key={rg} value={rg}>{rg}</option>
                  ))}
                </select>
              </div>

              {/* Key Vault */}
              <div>
                <label className={fieldLabel} htmlFor="akv-vault-dd">Key Vault</label>
                <select
                  id="akv-vault-dd"
                  className={fieldInput}
                  value={selectedVaultName}
                  onChange={(e) => handleVaultChange(e.target.value)}
                  disabled={!selectedRg}
                >
                  <option value="">{selectedRg ? "Select vault…" : "Select resource group first"}</option>
                  {filteredVaults.map((v) => (
                    <option key={v.name} value={v.name}>{v.name}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Manual override / display of selected values */}
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className={fieldLabel} htmlFor="akv-sub-txt">
                Subscription ID <span className="text-red-500">*</span>
                <span className="ml-1 text-xs font-normal text-gray-400">(auto-filled from dropdown)</span>
              </label>
              <input
                id="akv-sub-txt"
                className={fieldInput}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                value={subscriptionId}
                onChange={(e) => setSubscriptionId(e.target.value)}
              />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="akv-rg-txt">
                Resource Group <span className="text-red-500">*</span>
              </label>
              <input
                id="akv-rg-txt"
                className={fieldInput}
                placeholder="my-resource-group"
                value={resourceGroup}
                onChange={(e) => setResourceGroup(e.target.value)}
              />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="akv-vault-txt">
                Key Vault Name <span className="text-red-500">*</span>
              </label>
              <input
                id="akv-vault-txt"
                className={fieldInput}
                placeholder="my-key-vault"
                value={vaultName}
                onChange={(e) => setVaultName(e.target.value)}
              />
            </div>
            <div className="col-span-2">
              <label className={fieldLabel} htmlFor="akv-certname">
                Certificate Name in AKV <span className="text-red-500">*</span>
              </label>
              <input
                id="akv-certname"
                className={fieldInput + (!certName || certNameValid ? "" : " border-red-400")}
                placeholder="my-certificate"
                value={certName}
                onChange={(e) => setCertName(e.target.value)}
              />
              {certName && !certNameValid && (
                <p className="mt-1 text-xs text-red-600">Only alphanumeric characters and hyphens allowed.</p>
              )}
            </div>
          </div>
        </div>

        {/* Certificate Data */}
        <div>
          <label className={fieldLabel} htmlFor="akv-data">
            Certificate Data (Base64) <span className="text-red-500">*</span>
          </label>
          <textarea
            id="akv-data"
            className={`${fieldInput} h-24 font-mono text-xs`}
            placeholder="Base64-encoded PFX or PEM certificate data"
            value={certData}
            onChange={(e) => setCertData(e.target.value)}
          />
          <p className="mt-1 text-xs text-gray-500">Paste the base64-encoded certificate (PFX or PEM).</p>
        </div>

        {/* Certificate Password (optional for PFX) */}
        <div>
          <label className={fieldLabel} htmlFor="akv-certpw">Certificate Password (if PFX)</label>
          <div className="relative">
            <input
              id="akv-certpw"
              type={showPassword ? "text" : "password"}
              className={fieldInput + " pr-10"}
              placeholder="Leave blank for PEM certificates"
              value={certPassword}
              onChange={(e) => setCertPassword(e.target.value)}
              autoComplete="new-password"
            />
            <button
              type="button"
              className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600"
              onClick={() => setShowPassword((v) => !v)}
              tabIndex={-1}
            >
              {showPassword ? (
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" /><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" /><line x1="1" y1="1" x2="23" y2="23" /></svg>
              ) : (
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
              )}
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-400">Never logged or stored.</p>
        </div>
      </div>
    </CertificateModal>
  );
};
