/**
 * Shared Azure Key Vault target picker for certificate uploads.
 *
 * Cascade dropdowns: Subscription → Resource Group → Key Vault, then the entry
 * inside that vault. Reusing an existing entry name imports a new version of it,
 * which is what lets a renewed certificate replace the deployed one — AKV names
 * (e.g. opsportal-ingress-tls) rarely match the certificate common name, so the
 * matching entry is preselected by common name.
 */

import React, { useState, useMemo, useEffect, useRef } from "react";
import { fieldInput, fieldLabel } from "./CertificateModal";
import { useSubscriptionScope } from "../../contexts/SubscriptionContext";
import { useKeyVaults, useVaultCertificates } from "../../services/costApi";

export interface AkvTarget {
  subscriptionId: string;
  resourceGroup: string;
  vaultName: string;
  certificateNames: string[];
}

const AKV_NAME_RE = /^[a-zA-Z0-9-]+$/;

export const akvNameValid = (name: string): boolean => !name || AKV_NAME_RE.test(name.trim());

export const isAkvTargetComplete = (t: AkvTarget): boolean =>
  Boolean(
    t.subscriptionId.trim() &&
      t.resourceGroup.trim() &&
      t.vaultName.trim() &&
      t.certificateNames.length > 0 &&
      t.certificateNames.every((n) => n.trim() && AKV_NAME_RE.test(n.trim()))
  );

/** Sanitize a common name into a valid Key Vault certificate name. */
export const toAkvName = (commonName: string): string =>
  (commonName || "")
    .replace(/[^a-zA-Z0-9-]/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 127);

interface AkvTargetPickerProps {
  /** Preselects vault entries holding this certificate, so renewals update them in place. */
  commonName?: string;
  /** SANs of the certificate; a multi-SAN cert is often stored under one name per SAN. */
  sans?: string[];
  /** Current thumbprint — the strongest signal that an entry holds this same certificate. */
  thumbprint?: string;
  onChange: (target: AkvTarget) => void;
}

export const AkvTargetPicker: React.FC<AkvTargetPickerProps> = ({
  commonName = "",
  sans = [],
  thumbprint = "",
  onChange,
}) => {
  const { effectiveSubscriptionIds, availableSubscriptions } = useSubscriptionScope();
  const { data: allVaults = [], isLoading: vaultsLoading } = useKeyVaults();

  const [selectedSubId, setSelectedSubId] = useState("");
  const [selectedRg, setSelectedRg] = useState("");
  const [selectedVaultName, setSelectedVaultName] = useState("");
  const [nameMode, setNameMode] = useState<"existing" | "new">("existing");
  const [existingCertNames, setExistingCertNames] = useState<string[]>([]);
  const [newCertName, setNewCertName] = useState(toAkvName(commonName));

  const scopedVaults = useMemo(() => {
    if (!effectiveSubscriptionIds.length) return allVaults;
    return allVaults.filter((v) => effectiveSubscriptionIds.includes(v.subscription_id));
  }, [allVaults, effectiveSubscriptionIds]);

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

  const filteredVaults = useMemo(() => {
    if (!selectedSubId || !selectedRg) return [];
    return scopedVaults
      .filter((v) => v.subscription_id === selectedSubId && v.resource_group === selectedRg)
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [scopedVaults, selectedSubId, selectedRg]);

  const selectedVault = useMemo(
    () => filteredVaults.find((v) => v.name === selectedVaultName) ?? null,
    [filteredVaults, selectedVaultName]
  );
  const { data: vaultCerts = [], isLoading: vaultCertsLoading } = useVaultCertificates(
    selectedVault?.vault_uri ?? null
  );

  // Every vault entry holding this certificate: same thumbprint, or a CN/SAN match.
  const matchingVaultCerts = useMemo(() => {
    const identities = new Set(
      [commonName, ...sans].map((s) => s.trim().toLowerCase()).filter(Boolean)
    );
    const thumb = thumbprint.trim().toLowerCase();
    return vaultCerts.filter((c) => {
      if (thumb && (c.thumbprint || "").trim().toLowerCase() === thumb) return true;
      const cn = (c.cn_name || "").trim().toLowerCase();
      if (cn && identities.has(cn)) return true;
      return (c.san || []).some((s) => identities.has(s.trim().toLowerCase()));
    });
  }, [vaultCerts, commonName, sans, thumbprint]);

  // Which certificate(s) the caller is asking about. Fixed for the whole life
  // of the "Load to AKV" modal, but it changes in the auto-renewal form as the
  // schedule's certificates are picked — so detection is keyed on it rather
  // than latched after the first run, which would leave the entries matching
  // whatever happened to be selected first.
  const identityKey = useMemo(
    () =>
      [
        thumbprint.trim().toLowerCase(),
        ...[commonName, ...sans]
          .map((s) => s.trim().toLowerCase())
          .filter(Boolean)
          .sort(),
      ].join("|"),
    [commonName, sans, thumbprint]
  );

  const autoAppliedFor = useRef<string | null>(null);
  useEffect(() => {
    const key = `${selectedVaultName}::${identityKey}`;
    if (autoAppliedFor.current === key) return;
    // Nothing matched yet — the vault's certificates may still be loading, so
    // this is not recorded as applied and will be reconsidered.
    if (matchingVaultCerts.length === 0) return;
    setExistingCertNames(matchingVaultCerts.map((c) => c.name));
    autoAppliedFor.current = key;
  }, [matchingVaultCerts, identityKey, selectedVaultName]);

  const toggleExistingName = (name: string) =>
    setExistingCertNames((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );

  const certificateNames = useMemo(
    () => (nameMode === "existing" ? existingCertNames : newCertName.trim() ? [newCertName.trim()] : []),
    [nameMode, existingCertNames, newCertName]
  );

  // Ref keeps the parent callback out of the effect deps so it can stay inline.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  useEffect(() => {
    onChangeRef.current({
      subscriptionId: selectedSubId,
      resourceGroup: selectedRg,
      vaultName: selectedVaultName,
      certificateNames,
    });
  }, [selectedSubId, selectedRg, selectedVaultName, certificateNames]);

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Target Azure Key Vault</p>

      {vaultsLoading ? (
        <p className="text-sm text-gray-400">Loading available Key Vaults…</p>
      ) : scopedVaults.length === 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
          No Key Vaults found in your subscription scope.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className={fieldLabel} htmlFor="akv-sub-dd">Subscription</label>
            <select
              id="akv-sub-dd"
              className={fieldInput}
              value={selectedSubId}
              onChange={(e) => {
                setSelectedSubId(e.target.value);
                setSelectedRg("");
                setSelectedVaultName("");
                setExistingCertNames([]);
              }}
            >
              <option value="">Select subscription…</option>
              {uniqueSubscriptions.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className={fieldLabel} htmlFor="akv-rg-dd">Resource Group</label>
            <select
              id="akv-rg-dd"
              className={fieldInput}
              value={selectedRg}
              onChange={(e) => {
                setSelectedRg(e.target.value);
                setSelectedVaultName("");
                setExistingCertNames([]);
              }}
              disabled={!selectedSubId}
            >
              <option value="">{selectedSubId ? "Select resource group…" : "Select subscription first"}</option>
              {filteredRgs.map((rg) => (
                <option key={rg} value={rg}>{rg}</option>
              ))}
            </select>
          </div>

          <div>
            <label className={fieldLabel} htmlFor="akv-vault-dd">Key Vault</label>
            <select
              id="akv-vault-dd"
              className={fieldInput}
              value={selectedVaultName}
              onChange={(e) => {
                setSelectedVaultName(e.target.value);
                setExistingCertNames([]);
              }}
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

      <div className="space-y-2">
        <label className={fieldLabel}>
          Certificates in AKV <span className="text-red-500">*</span>
        </label>

        <div className="flex gap-4 text-sm">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="radio"
              name="akv-name-mode"
              checked={nameMode === "existing"}
              onChange={() => setNameMode("existing")}
            />
            <span className="text-gray-700">Update existing</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="radio"
              name="akv-name-mode"
              checked={nameMode === "new"}
              onChange={() => setNameMode("new")}
            />
            <span className="text-gray-700">Create new</span>
          </label>
        </div>

        {nameMode === "existing" ? (
          <>
            {!selectedVaultName ? (
              <p className="text-sm text-gray-400">Select a Key Vault first.</p>
            ) : vaultCertsLoading ? (
              <p className="text-sm text-gray-400">Loading certificates…</p>
            ) : vaultCerts.length === 0 ? (
              <p className="text-sm text-gray-400">This vault has no certificates yet.</p>
            ) : (
              <div className="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-att-100 p-2">
                {vaultCerts.map((c) => {
                  const isMatch = matchingVaultCerts.some((m) => m.name === c.name);
                  return (
                    <label
                      key={c.name}
                      className="flex cursor-pointer items-start gap-2 rounded px-2 py-1 text-sm hover:bg-att-50"
                    >
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={existingCertNames.includes(c.name)}
                        onChange={() => toggleExistingName(c.name)}
                      />
                      <span>
                        <span className="font-medium text-gray-800">{c.name}</span>
                        {isMatch && (
                          <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-800">
                            holds this certificate
                          </span>
                        )}
                        {c.cn_name && <span className="block text-xs text-gray-500">{c.cn_name}</span>}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
            {matchingVaultCerts.length > 1 ? (
              <p className="mt-1 text-xs text-green-700">
                {matchingVaultCerts.length} entries hold this certificate (one per SAN). All are
                selected so a single load updates every one — the PFX cannot be exported again later.
              </p>
            ) : (
              <p className="mt-1 text-xs text-gray-500">
                Importing over an existing name adds a new version; earlier versions are kept.
              </p>
            )}
          </>
        ) : (
          <>
            <input
              className={fieldInput + (akvNameValid(newCertName) ? "" : " border-red-400")}
              placeholder="my-certificate"
              value={newCertName}
              onChange={(e) => setNewCertName(e.target.value)}
            />
            {!akvNameValid(newCertName) && (
              <p className="mt-1 text-xs text-red-600">Only alphanumeric characters and hyphens allowed.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
};
