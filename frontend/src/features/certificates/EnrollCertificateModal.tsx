/**
 * Enroll Certificate modal — full Keyfactor PFX/CSR enrollment form.
 *
 * Matches the Keyfactor Command PFX Enrollment UI with sections:
 * - Enrollment Profile (saved defaults, so a request only needs a CN and SANs)
 * - Certificate Authority Information (enrollment pattern, key algorithm, key size / curve, CA)
 * - Certificate Subject Information (CN, O, OU, L, ST, C, Email)
 * - Custom Friendly Name
 * - Subject Alternative Names (add/remove table)
 * - Certificate Metadata (fields, allowed values and validation read from Keyfactor)
 * - Password & Delivery options
 *
 * The enrollment pattern drives the key algorithm, key size/curve and CA choices,
 * exactly as Keyfactor's own form does; "Auto-Select" leaves the CA to the pattern.
 */

import React, { useMemo, useState } from "react";
import {
  EnrollRequest,
  EnrollResult,
  EnrollmentPattern,
  EnrollmentPatternKeyAlgorithm,
  EnrollmentProfile,
  EnrollmentProfileDefaults,
  EnrollmentType,
  MetadataField,
  certificateErrorMessage,
  useCreateEnrollmentProfile,
  useDeleteEnrollmentProfile,
  useEnrollCertificate,
  useEnrollmentPatterns,
  useEnrollmentProfiles,
  useLoadCertificateToAkv,
  useMetadataFields,
  useUpdateEnrollmentProfile,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";
import { AkvTarget, AkvTargetPicker, isAkvTargetComplete } from "./AkvTargetPicker";

interface EnrollCertificateModalProps {
  defaultCa?: string;
  defaultTemplate?: string;
  /** Selected collection; only it is re-synced after enrollment. */
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

interface SanEntry { type: string; value: string; }

type ProfileAction = "create" | "update" | "delete" | null;

// Used when the selected pattern's key policy is unknown (e.g. a manually entered ID).
const FALLBACK_KEY_ALGORITHMS: EnrollmentPatternKeyAlgorithm[] = [
  { name: "RSA", key_sizes: [2048, 3072, 4096], curves: [] },
  { name: "ECC", key_sizes: [], curves: ["1.2.840.10045.3.1.7", "1.3.132.0.34", "1.3.132.0.35"] },
];
const CURVES: Record<string, { label: string; bits: number }> = {
  "1.2.840.10045.3.1.7": { label: "P-256/prime256v1", bits: 256 },
  "1.3.132.0.34": { label: "P-384/secp384r1", bits: 384 },
  "1.3.132.0.35": { label: "P-521/secp521r1", bits: 521 },
};
// Profiles saved before metadata came from Keyfactor stored these per-field keys.
const LEGACY_METADATA_KEYS: Record<string, string> = {
  mots_profile_id: "MOTS-Profile-ID",
  requester_att_user_id: "Requester-ATT-User-ID",
  requester_att_manager_user_id: "Requester-ATT-Manager-User-ID",
  server_type: "Server-Type",
  environment: "Environment",
  tls_port_services_internet_traffic: "TLS-Port-Services-Internet-Traffic",
  port: "Port",
  pci_data: "PCI-Data",
};

// Exactly 64 characters, so the modulo below is unbiased. Ambiguous glyphs
// (l, I, O, 0, 1) are left out because this password is read off the screen.
const PFX_PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&";

/** Keyfactor requires a PFX password of at least 12 characters. */
const randomPfxPassword = (): string => {
  const bytes = new Uint32Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => PFX_PASSWORD_ALPHABET[b % PFX_PASSWORD_ALPHABET.length]).join("");
};

export const EnrollCertificateModal: React.FC<EnrollCertificateModalProps> = ({
  defaultCa = "",
  defaultTemplate = "",
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const enroll = useEnrollCertificate();
  const { data: patterns, isLoading: patternsLoading } = useEnrollmentPatterns();
  const { data: metadataFields, isLoading: metadataLoading } = useMetadataFields();
  const { data: profiles } = useEnrollmentProfiles();
  const createProfile = useCreateEnrollmentProfile();
  const updateProfile = useUpdateEnrollmentProfile();
  const removeProfile = useDeleteEnrollmentProfile();

  const [type, setType] = useState<EnrollmentType>("pfx");
  const [template, setTemplate] = useState(defaultTemplate);
  const [enrollmentPatternId, setEnrollmentPatternId] = useState("");
  const [keyAlgorithm, setKeyAlgorithm] = useState("RSA");
  const [keySize, setKeySize] = useState(4096);
  const [curve, setCurve] = useState("");
  const [ca, setCa] = useState(defaultCa);

  const [profileId, setProfileId] = useState<number | "">("");
  const [profileAction, setProfileAction] = useState<ProfileAction>(null);
  const [profileName, setProfileName] = useState("");
  const [profileShared, setProfileShared] = useState(true);
  const [manualPattern, setManualPattern] = useState(false);

  const [commonName, setCommonName] = useState("");
  const [organization, setOrganization] = useState("AT&T Services, Inc.");
  const [orgUnit, setOrgUnit] = useState("");
  const [city, setCity] = useState("Dallas");
  const [state, setState] = useState("Texas");
  const [country, setCountry] = useState("US");
  const [email, setEmail] = useState("");
  const [friendlyName, setFriendlyName] = useState("");

  const [sans, setSans] = useState<SanEntry[]>([]);
  const [newSanType, setNewSanType] = useState("DNS");
  const [newSanValue, setNewSanValue] = useState("");

  const [metadataValues, setMetadataValues] = useState<Record<string, string>>({});

  const [password, setPassword] = useState("");
  const [useCustomPassword, setUseCustomPassword] = useState(false);
  // The password the PFX was actually protected with — generated when the user
  // supplies none, and needed again to download it or load it into a vault.
  const [issuedPassword, setIssuedPassword] = useState("");
  const [ownerRoleName, setOwnerRoleName] = useState("");
  const [includeChain, setIncludeChain] = useState(true);
  const [useLegacyEncryption, setUseLegacyEncryption] = useState(true);

  const [csr, setCsr] = useState("");
  const [result, setResult] = useState<EnrollResult | null>(null);
  const loadToAkv = useLoadCertificateToAkv();
  const [akvTarget, setAkvTarget] = useState<AkvTarget>({
    subscriptionId: "",
    resourceGroup: "",
    vaultName: "",
    certificateNames: [],
  });
  const [akvLoaded, setAkvLoaded] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const selectedProfile = profiles?.find((p) => p.id === profileId);
  const patternIdValue = enrollmentPatternId.trim() ? Number(enrollmentPatternId.trim()) : undefined;

  // A value Keyfactor no longer offers (e.g. from an old profile) counts as unset.
  const metadataValue = (field: MetadataField): string => {
    const value = (metadataValues[field.name] ?? field.default_value).trim();
    const choices = field.data_type === "boolean" && field.options.length === 0 ? ["True", "False"] : field.options;
    return choices.length > 0 && !choices.includes(value) ? "" : value;
  };

  const metadataPayload = (): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const field of metadataFields ?? []) {
      const value = metadataValue(field);
      if (value) out[field.name] = value;
    }
    return out;
  };

  const metadataError = (field: MetadataField): string | undefined => {
    const value = metadataValue(field);
    if (!value) return field.required ? `${field.name} is required` : undefined;
    if (!field.validation) return undefined;
    try {
      return new RegExp(field.validation).test(value) ? undefined : `${field.name} is not in the expected format`;
    } catch {
      return undefined;
    }
  };

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (patternIdValue === undefined) {
      next.enrollmentPatternId = "Enrollment Pattern is required";
    } else if (!Number.isInteger(patternIdValue) || patternIdValue < 1) {
      next.enrollmentPatternId = "Enrollment Pattern ID must be a positive whole number";
    }
    if (!ownerRoleName.trim()) next.ownerRoleName = "Owner Role Name is required by Keyfactor policy";
    for (const field of metadataFields ?? []) {
      const message = metadataError(field);
      if (message) next[`md:${field.name}`] = message;
    }
    if (type === "pfx") {
      if (!commonName.trim()) next.commonName = "Common Name is required";
      if (useCustomPassword && !password.trim()) next.password = "Password is required (min 12 characters)";
      if (password.trim() && password.length < 12) next.password = "Password must be at least 12 characters";
    }
    if (type === "csr" && !csr.trim()) next.csr = "CSR is required";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const sansPayload = useMemo(() => {
    if (sans.length === 0) return undefined;
    const grouped: Record<string, string[]> = {};
    for (const s of sans) {
      const key = s.type.toLowerCase();
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(s.value);
    }
    return grouped;
  }, [sans]);

  const patternsUnavailable = !patternsLoading && (patterns?.length ?? 0) === 0;
  const showPatternInput = manualPattern || patternsUnavailable;
  const selectedPattern = patterns?.find((p) => String(p.id) === enrollmentPatternId);

  // Keyfactor groups patterns by AD forest / CA tenant in its dropdown.
  const patternGroups = useMemo(() => {
    const groups = new Map<string, EnrollmentPattern[]>();
    for (const p of patterns ?? []) {
      const key = p.group || "Other";
      groups.set(key, [...(groups.get(key) ?? []), p]);
    }
    return Array.from(groups.entries());
  }, [patterns]);

  const keyAlgorithms = selectedPattern?.key_algorithms.length
    ? selectedPattern.key_algorithms
    : FALLBACK_KEY_ALGORITHMS;
  const currentAlgorithm = keyAlgorithms.find((a) => a.name === keyAlgorithm) ?? keyAlgorithms[0];
  const usesCurve = currentAlgorithm.curves.length > 0;

  // A saved profile may hold a CA outside the pattern's list, so it is still offered.
  const caOptions = useMemo(() => {
    const opts = selectedPattern?.certificate_authorities ?? [];
    return ca && !opts.includes(ca) ? [ca, ...opts] : opts;
  }, [selectedPattern, ca]);

  const applyAlgorithm = (algo: EnrollmentPatternKeyAlgorithm) => {
    setKeyAlgorithm(algo.name);
    if (algo.curves.length > 0) {
      const nextCurve = algo.curves[0];
      setCurve(nextCurve);
      setKeySize(CURVES[nextCurve]?.bits ?? algo.key_sizes[0] ?? 384);
    } else {
      setCurve("");
      setKeySize(algo.key_sizes.includes(keySize) ? keySize : (algo.key_sizes[algo.key_sizes.length - 1] ?? 4096));
    }
  };

  const selectPattern = (value: string) => {
    setEnrollmentPatternId(value);
    const picked = patterns?.find((p) => String(p.id) === value);
    if (!picked) return;
    setTemplate(picked.template_name);
    setCa("");
    applyAlgorithm(picked.key_algorithms[0] ?? FALLBACK_KEY_ALGORITHMS[0]);
  };

  const selectCurve = (value: string) => {
    setCurve(value);
    setKeySize(CURVES[value]?.bits ?? keySize);
  };

  const renderPatternField = (compact: boolean) => (
    <div className={compact ? "min-w-[16rem] flex-1" : "col-span-2"}>
      <label className={fieldLabel}>Enrollment Pattern{compact ? "" : " *"}</label>
      {showPatternInput ? (
        <input
          className={fieldInput}
          inputMode="numeric"
          value={enrollmentPatternId}
          onChange={(e) => setEnrollmentPatternId(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder="Enrollment Pattern ID, e.g. 28"
        />
      ) : (
        <select className={fieldInput} value={enrollmentPatternId} onChange={(e) => selectPattern(e.target.value)}>
          <option value="">{patternsLoading ? "Loading patterns…" : "Select…"}</option>
          {enrollmentPatternId && !selectedPattern && (
            <option value={enrollmentPatternId}>Pattern ID {enrollmentPatternId}</option>
          )}
          {patternGroups.map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items.map((p) => (
                <option key={p.id} value={String(p.id)}>{p.name}</option>
              ))}
            </optgroup>
          ))}
        </select>
      )}
      {!compact && !patternsUnavailable && (
        <button type="button" className="mt-1 text-xs text-att-600 hover:underline" onClick={() => setManualPattern((v) => !v)}>
          {manualPattern ? "Choose from list" : "Enter ID manually"}
        </button>
      )}
      {errors.enrollmentPatternId && (
        <p className="mt-1 text-xs text-red-600">{errors.enrollmentPatternId}</p>
      )}
    </div>
  );

  const setMetadata = (name: string, value: string) =>
    setMetadataValues((prev) => ({ ...prev, [name]: value }));

  const renderMetadataField = (field: MetadataField) => {
    const value = metadataValue(field);
    const choices =
      field.data_type === "boolean" && field.options.length === 0 ? ["True", "False"] : field.options;
    const error = errors[`md:${field.name}`];
    let control: React.ReactNode;
    if (choices.length > 0) {
      control = (
        <select className={fieldInput} value={value} onChange={(e) => setMetadata(field.name, e.target.value)}>
          <option value="">Select…</option>
          {choices.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      );
    } else if (field.data_type === "text") {
      control = (
        <textarea
          className={`${fieldInput} h-20`}
          value={value}
          onChange={(e) => setMetadata(field.name, e.target.value)}
          placeholder={field.hint}
        />
      );
    } else {
      const inputType =
        field.data_type === "integer" ? "number" : field.data_type === "date" ? "date" : field.data_type === "email" ? "email" : "text";
      control = (
        <input
          type={inputType}
          className={fieldInput}
          value={value}
          onChange={(e) => setMetadata(field.name, e.target.value)}
          placeholder={field.hint}
        />
      );
    }
    return (
      <div key={field.name}>
        <label className={fieldLabel}>
          {field.name}
          {field.required ? " *" : ""}
        </label>
        {control}
        {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      </div>
    );
  };

  const currentDefaults = (): EnrollmentProfileDefaults => ({
    template: template.trim(),
    enrollment_pattern_id: patternIdValue,
    certificate_authority: ca.trim(),
    key_type: keyAlgorithm,
    key_length: keySize,
    curve: curve || undefined,
    organization: organization.trim(),
    organizational_unit: orgUnit.trim(),
    city: city.trim(),
    state: state.trim(),
    country: country.trim(),
    email: email.trim(),
    owner_role_name: ownerRoleName.trim(),
    include_chain: includeChain,
    use_legacy_encryption: useLegacyEncryption,
    metadata: metadataPayload(),
  });

  const applyProfile = (profile: EnrollmentProfile | undefined) => {
    setProfileId(profile?.id ?? "");
    setProfileAction(null);
    if (!profile) return;
    const d = profile.defaults ?? {};
    setTemplate(d.template ?? profile.template ?? "");
    setEnrollmentPatternId(d.enrollment_pattern_id ? String(d.enrollment_pattern_id) : "");
    setCa(d.certificate_authority ?? profile.certificate_authority ?? "");
    if (d.key_type) setKeyAlgorithm(d.key_type);
    if (d.key_length) setKeySize(d.key_length);
    setCurve(d.curve ?? "");
    setOrganization(d.organization ?? "");
    setOrgUnit(d.organizational_unit ?? "");
    setCity(d.city ?? "");
    setState(d.state ?? "");
    setCountry(d.country ?? "");
    setEmail(d.email ?? "");
    setOwnerRoleName(d.owner_role_name ?? "");
    setIncludeChain(d.include_chain ?? true);
    setUseLegacyEncryption(d.use_legacy_encryption ?? true);
    const legacy: Record<string, string> = {};
    for (const [key, fieldName] of Object.entries(LEGACY_METADATA_KEYS)) {
      const value = d[key as keyof EnrollmentProfileDefaults];
      if (typeof value === "string" && value) legacy[fieldName] = value;
    }
    setMetadataValues({ ...legacy, ...(d.metadata ?? {}) });
    setErrors({});
  };

  const openProfileAction = (action: ProfileAction) => {
    if (action === profileAction) {
      setProfileAction(null);
      return;
    }
    setErrors((p) => ({ ...p, profileName: "" }));
    if (action === "update" && selectedProfile) {
      setProfileName(selectedProfile.name);
      setProfileShared(selectedProfile.shared);
    } else if (action === "create") {
      setProfileName("");
      setProfileShared(true);
    }
    setProfileAction(action);
  };

  const handleSaveProfile = async () => {
    const name = profileName.trim();
    if (!name) {
      setErrors((p) => ({ ...p, profileName: "Profile name is required" }));
      return;
    }
    const isUpdate = profileAction === "update" && selectedProfile !== undefined;
    try {
      if (isUpdate) {
        const saved = await updateProfile.mutateAsync({
          id: selectedProfile.id,
          data: {
            name,
            description: selectedProfile.description,
            shared: profileShared,
            defaults: currentDefaults(),
          },
        });
        onSuccess(`Enrollment profile "${saved.name}" updated`);
      } else {
        const saved = await createProfile.mutateAsync({
          name,
          description: "",
          shared: profileShared,
          defaults: currentDefaults(),
        });
        setProfileId(saved.id);
        onSuccess(`Enrollment profile "${saved.name}" saved`);
      }
      setProfileName("");
      setProfileAction(null);
    } catch (err) {
      onError(
        certificateErrorMessage(
          err,
          isUpdate ? "Failed to update enrollment profile" : "Failed to save enrollment profile",
        ),
      );
    }
  };

  const handleDeleteProfile = async () => {
    if (profileId === "") return;
    try {
      await removeProfile.mutateAsync(profileId);
      setProfileId("");
      setProfileAction(null);
      onSuccess("Enrollment profile deleted");
    } catch (err) {
      onError(certificateErrorMessage(err, "Failed to delete enrollment profile"));
    }
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    const payload: EnrollRequest = {
      enrollment_type: type,
      certificate_authority: ca.trim(),
      template: template.trim(),
      enrollment_pattern_id: patternIdValue,
      include_chain: includeChain,
      sans: sansPayload,
      key_type: currentAlgorithm.name,
      key_length: keySize,
      curve: usesCurve ? curve || currentAlgorithm.curves[0] : undefined,
      metadata: metadataPayload(),
      collection_id: collectionId,
      use_legacy_encryption: useLegacyEncryption,
      owner_role_name: ownerRoleName.trim() || undefined,
    };
    let pfxPassword = "";
    if (type === "csr") {
      payload.csr = csr.trim();
    } else {
      // Keyfactor rejects a PFX request without a password, so one is minted
      // here rather than failing the request when the user supplies none.
      pfxPassword = useCustomPassword && password.trim() ? password : randomPfxPassword();
      payload.common_name = commonName.trim();
      payload.organization = organization.trim();
      payload.organizational_unit = orgUnit.trim();
      payload.city = city.trim();
      payload.state = state.trim();
      payload.country = country.trim();
      payload.email = email.trim() || undefined;
      payload.custom_friendly_name = friendlyName.trim() || undefined;
      payload.password = pfxPassword;
    }
    try {
      const res = await enroll.mutateAsync(payload);
      setIssuedPassword(pfxPassword);
      setResult(res);
      onSuccess("Certificate enrolled successfully");
    } catch (err) {
      onError(certificateErrorMessage(err, "Enrollment failed"));
    }
  };

  const downloadPfx = () => {
    if (!result?.pfx_base64) return;
    const blob = new Blob([Uint8Array.from(atob(result.pfx_base64), (c) => c.charCodeAt(0))], { type: "application/x-pkcs12" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${commonName || "certificate"}.pfx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const addSan = () => { if (!newSanValue.trim()) return; setSans((p) => [...p, { type: newSanType, value: newSanValue.trim() }]); setNewSanValue(""); };
  const removeSan = (idx: number) => setSans((p) => p.filter((_, i) => i !== idx));

  const handleLoadToAkv = async () => {
    if (!result?.pfx_base64 || !isAkvTargetComplete(akvTarget)) return;
    try {
      await loadToAkv.mutateAsync({
        id: result.certificate_id ?? 0,
        data: {
          subscription_id: akvTarget.subscriptionId.trim(),
          resource_group: akvTarget.resourceGroup.trim(),
          vault_name: akvTarget.vaultName.trim(),
          certificate_names: akvTarget.certificateNames.map((n) => n.trim()),
          certificate_data: result.pfx_base64,
          ...(issuedPassword ? { certificate_password: issuedPassword } : {}),
        },
      });
      setAkvLoaded(true);
      onSuccess(`Certificate loaded to AKV: ${akvTarget.vaultName}`);
    } catch (err) {
      onError(certificateErrorMessage(err, "Failed to load certificate into Azure Key Vault"));
    }
  };

  if (result) {
    return (
      <CertificateModal title="Enrollment Complete" onClose={onClose} footer={<button type="button" className={modalButton.secondary} onClick={onClose}>Close</button>}>
        <div className="space-y-3 text-sm text-gray-700">
          <p className="font-medium text-green-700">The certificate was issued successfully.</p>
          {result.thumbprint && <p><span className="font-semibold">Thumbprint:</span> <span className="font-mono text-xs break-all">{result.thumbprint}</span></p>}
          {result.serial_number && <p><span className="font-semibold">Serial:</span> <span className="font-mono text-xs break-all">{result.serial_number}</span></p>}
          {result.pfx_base64 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs text-amber-800">The PFX contains the private key — download and store securely. It is never retained by the portal.</p>
              {!useCustomPassword && issuedPassword && (
                <p className="mt-2 text-xs text-amber-900">
                  <span className="font-semibold">Generated PFX password:</span>{" "}
                  <span className="font-mono break-all">{issuedPassword}</span>
                  <br />
                  Copy it now — it is shown only here and is not stored by the portal.
                </p>
              )}
              <button type="button" className={`${modalButton.primary} mt-2`} onClick={downloadPfx}>Download PFX</button>
            </div>
          )}
          {result.pfx_base64 && (
            <div className="space-y-3 rounded-xl border border-att-100 bg-att-50/30 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-att-600">
                Load to Azure Key Vault (optional)
              </p>
              {akvLoaded ? (
                <p className="text-sm text-green-700">Certificate loaded into Azure Key Vault.</p>
              ) : (
                <>
                  <p className="text-xs text-gray-500">
                    This is the only moment the private key is available, so load it now if it is
                    destined for a vault.
                  </p>
                  <AkvTargetPicker commonName={commonName} onChange={setAkvTarget} />
                  <button
                    type="button"
                    className={modalButton.primary + " w-full"}
                    disabled={loadToAkv.isPending || !isAkvTargetComplete(akvTarget)}
                    onClick={handleLoadToAkv}
                  >
                    {loadToAkv.isPending ? "Loading to AKV…" : "Load to Azure Key Vault"}
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </CertificateModal>
    );
  }

  const Toggle: React.FC<{ checked: boolean; onChange: () => void; label: string }> = ({ checked, onChange, label }) => (
    <label className="flex items-center gap-3 cursor-pointer">
      <div role="switch" aria-checked={checked} tabIndex={0} className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${checked ? "bg-att-500" : "bg-gray-300"}`} onClick={onChange} onKeyDown={(e) => e.key === "Enter" && onChange()}>
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? "translate-x-6" : "translate-x-1"}`} />
      </div>
      <span className="text-sm text-gray-700">{label}</span>
    </label>
  );

  return (
    <CertificateModal title={type === "pfx" ? "PFX Enrollment" : "CSR Enrollment"} onClose={onClose} widthClassName="max-w-3xl"
      footer={<><button type="button" className={modalButton.secondary} onClick={onClose}>Cancel</button><button type="button" className={modalButton.primary} disabled={enroll.isPending} onClick={handleSubmit}>{enroll.isPending ? "Enrolling…" : "ENROLL"}</button></>}>
      <div className="space-y-6">
        {/* Type selector */}
        <div className="flex gap-4 border-b border-att-100 pb-4">
          <button type="button" className={`px-4 py-2 rounded-lg text-sm font-medium transition ${type === "pfx" ? "bg-att-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-att-50"}`} onClick={() => setType("pfx")}>PFX Enrollment</button>
          <button type="button" className={`px-4 py-2 rounded-lg text-sm font-medium transition ${type === "csr" ? "bg-att-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-att-50"}`} onClick={() => setType("csr")}>CSR Enrollment</button>
        </div>

        {/* Saved enrollment profile */}
        <fieldset className="space-y-3 rounded-xl border border-att-100 bg-att-50/30 p-4">
          <legend className="px-1 text-sm font-semibold text-att-700">Enrollment Profile</legend>
          <p className="text-xs text-gray-500">
            Load a saved profile to fill the template, authority and metadata — then only the Common
            Name and SANs are left to enter.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[16rem] flex-1">
              <label className={fieldLabel}>Profile</label>
              <select
                className={fieldInput}
                value={profileId}
                onChange={(e) =>
                  applyProfile(profiles?.find((p) => p.id === Number(e.target.value)))
                }
              >
                <option value="">No profile — enter values manually</option>
                {profiles?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.shared ? "" : " (private)"}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              className={modalButton.secondary}
              onClick={() => openProfileAction("create")}
            >
              NEW PROFILE
            </button>
            {selectedProfile && (
              <>
                <button
                  type="button"
                  className={modalButton.secondary}
                  onClick={() => openProfileAction("update")}
                >
                  UPDATE PROFILE
                </button>
                <button
                  type="button"
                  className={modalButton.secondary}
                  onClick={() => openProfileAction("delete")}
                >
                  DELETE PROFILE
                </button>
              </>
            )}
          </div>
          {(profileAction === "create" || profileAction === "update") && (
            <div className="space-y-2 border-t border-att-100 pt-3">
              {profileAction === "update" && selectedProfile && (
                <p className="text-xs text-gray-600">
                  Saves the current form values (pattern, key, authority, owner, subject and metadata)
                  into <span className="font-semibold">{selectedProfile.name}</span>.
                </p>
              )}
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-[16rem] flex-1">
                  <label className={fieldLabel}>
                    {profileAction === "update" ? "Profile name" : "New profile name"}
                  </label>
                  <input
                    className={fieldInput}
                    value={profileName}
                    onChange={(e) => setProfileName(e.target.value)}
                    placeholder="e.g. ATT Internal Web Server"
                  />
                  {errors.profileName && <p className="mt-1 text-xs text-red-600">{errors.profileName}</p>}
                </div>
                {renderPatternField(true)}
                <label className="flex items-center gap-2 pb-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={profileShared}
                    onChange={() => setProfileShared((v) => !v)}
                  />
                  Share with everyone
                </label>
                <button
                  type="button"
                  className={modalButton.secondary}
                  onClick={() => setProfileAction(null)}
                >
                  CANCEL
                </button>
                <button
                  type="button"
                  className={modalButton.primary}
                  disabled={createProfile.isPending || updateProfile.isPending}
                  onClick={handleSaveProfile}
                >
                  {createProfile.isPending || updateProfile.isPending
                    ? "Saving…"
                    : profileAction === "update"
                      ? "UPDATE"
                      : "SAVE"}
                </button>
              </div>
            </div>
          )}
          {profileAction === "delete" && selectedProfile && (
            <div className="flex flex-wrap items-center gap-2 border-t border-att-100 pt-3">
              <p className="flex-1 text-sm text-red-700">
                Delete profile <span className="font-semibold">{selectedProfile.name}</span>? This cannot be
                undone.
              </p>
              <button
                type="button"
                className={modalButton.secondary}
                onClick={() => setProfileAction(null)}
              >
                CANCEL
              </button>
              <button
                type="button"
                className={modalButton.primary}
                disabled={removeProfile.isPending}
                onClick={handleDeleteProfile}
              >
                {removeProfile.isPending ? "Deleting…" : "CONFIRM DELETE"}
              </button>
            </div>
          )}
          <p className="text-xs text-gray-400">
            Profiles never store the PFX password or a CSR.
          </p>
        </fieldset>

        {/* CA Information */}
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Authority Information</legend>
          <div className="grid grid-cols-4 gap-3">
            {renderPatternField(false)}
            <div>
              <label className={fieldLabel}>Key Algorithm</label>
              <select
                className={fieldInput}
                value={currentAlgorithm.name}
                onChange={(e) => {
                  const algo = keyAlgorithms.find((a) => a.name === e.target.value);
                  if (algo) applyAlgorithm(algo);
                }}
              >
                {keyAlgorithms.map((a) => (
                  <option key={a.name} value={a.name}>{a.name}</option>
                ))}
              </select>
            </div>
            {usesCurve ? (
              <div>
                <label className={fieldLabel}>Curve</label>
                <select
                  className={`${fieldInput} disabled:bg-gray-100 disabled:text-gray-500`}
                  value={curve || currentAlgorithm.curves[0]}
                  disabled={currentAlgorithm.curves.length === 1}
                  onChange={(e) => selectCurve(e.target.value)}
                >
                  {currentAlgorithm.curves.map((c) => (
                    <option key={c} value={c}>{CURVES[c]?.label ?? c}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div>
                <label className={fieldLabel}>Key Size</label>
                <select
                  className={`${fieldInput} disabled:bg-gray-100 disabled:text-gray-500`}
                  value={keySize}
                  disabled={currentAlgorithm.key_sizes.length === 1}
                  onChange={(e) => setKeySize(Number(e.target.value))}
                >
                  {currentAlgorithm.key_sizes.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <div className="max-w-md">
            <label className={fieldLabel}>Certificate Authority</label>
            <select className={fieldInput} value={ca} onChange={(e) => setCa(e.target.value)}>
              <option value="">Auto-Select</option>
              {caOptions.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </div>
        </fieldset>

        {/* Owner — Keyfactor policy rejects enrollment without one */}
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Owner</legend>
          <div className="max-w-md">
            <label className={fieldLabel}>Owner Role Name *</label>
            <input
              className={fieldInput}
              value={ownerRoleName}
              onChange={(e) => setOwnerRoleName(e.target.value)}
              placeholder="e.g. AP-KF-ATTCC-31599"
            />
            <p className="mt-1 text-xs text-gray-500">
              Keyfactor security role that owns the certificate — usually your collection&apos;s role.
            </p>
            {errors.ownerRoleName && <p className="mt-1 text-xs text-red-600">{errors.ownerRoleName}</p>}
          </div>
        </fieldset>

        {type === "csr" ? (
          <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Signing Request</legend><textarea className={`${fieldInput} h-32 font-mono text-xs`} value={csr} onChange={(e) => setCsr(e.target.value)} placeholder="-----BEGIN CERTIFICATE REQUEST-----" />{errors.csr && <p className="mt-1 text-xs text-red-600">{errors.csr}</p>}</fieldset>
        ) : (
          <>
            {/* Subject */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Subject Information</legend>
              <div className="grid grid-cols-3 gap-3">
                <div><label className={fieldLabel}>Common Name *</label><input className={fieldInput} value={commonName} onChange={(e) => setCommonName(e.target.value)} placeholder="app.example.att.com" />{errors.commonName && <p className="mt-1 text-xs text-red-600">{errors.commonName}</p>}</div>
                <div><label className={fieldLabel}>Organization</label><input className={fieldInput} value={organization} onChange={(e) => setOrganization(e.target.value)} /></div>
                <div><label className={fieldLabel}>Organizational Unit</label><input className={fieldInput} value={orgUnit} onChange={(e) => setOrgUnit(e.target.value)} /></div>
                <div><label className={fieldLabel}>City/Locality</label><input className={fieldInput} value={city} onChange={(e) => setCity(e.target.value)} /></div>
                <div><label className={fieldLabel}>State/Province</label><input className={fieldInput} value={state} onChange={(e) => setState(e.target.value)} /></div>
                <div><label className={fieldLabel}>Country/Region</label><input className={fieldInput} value={country} onChange={(e) => setCountry(e.target.value)} maxLength={2} /></div>
              </div>
              <div><label className={fieldLabel}>Email</label><input type="email" className={fieldInput} value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            </fieldset>

            {/* Friendly Name */}
            <fieldset className="space-y-2"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Custom Friendly Name</legend><input className={fieldInput} value={friendlyName} onChange={(e) => setFriendlyName(e.target.value)} placeholder="Custom Friendly Name" /></fieldset>

            {/* SANs */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Subject Alternative Names</legend>
              <div className="flex gap-2"><select className={`${fieldInput} w-28`} value={newSanType} onChange={(e) => setNewSanType(e.target.value)}><option value="DNS">DNS</option><option value="IP">IP</option><option value="URI">URI</option><option value="Email">Email</option></select><input className={fieldInput} value={newSanValue} onChange={(e) => setNewSanValue(e.target.value)} placeholder="Value" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSan(); } }} /><button type="button" className={modalButton.secondary} onClick={addSan}>ADD</button></div>
              {sans.length > 0 && (<table className="w-full text-sm border border-att-100 rounded-lg overflow-hidden"><thead className="bg-att-50/80"><tr><th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">Type</th><th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">Value</th><th className="px-3 py-2 w-16" /></tr></thead><tbody>{sans.map((s, i) => (<tr key={i} className="border-t border-att-100"><td className="px-3 py-2 text-gray-700">{s.type}</td><td className="px-3 py-2 text-gray-700 font-mono text-xs">{s.value}</td><td className="px-3 py-2 text-center"><button type="button" className="text-red-500 hover:text-red-700 text-xs" onClick={() => removeSan(i)}>DELETE</button></td></tr>))}</tbody></table>)}
              <span className="text-xs text-gray-500">Total: {sans.length}</span>
            </fieldset>

            {/* Password */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Password (min 12 characters)</legend>
              <Toggle checked={useCustomPassword} onChange={() => setUseCustomPassword(!useCustomPassword)} label="Use Custom Password" />
              {useCustomPassword && <div><input type="password" className={fieldInput} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Minimum 12 characters" />{errors.password && <p className="mt-1 text-xs text-red-600">{errors.password}</p>}</div>}
            </fieldset>

            {/* Chain & Legacy */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Chain Options</legend><Toggle checked={includeChain} onChange={() => setIncludeChain(!includeChain)} label="Include Chain" /></fieldset>
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Additional Options</legend><Toggle checked={useLegacyEncryption} onChange={() => setUseLegacyEncryption(!useLegacyEncryption)} label="Use Legacy Encryption" /></fieldset>
          </>
        )}

        {/* Metadata — fields, options and validation come from Keyfactor */}
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Metadata</legend>
          {metadataLoading ? (
            <p className="text-sm text-gray-500">Loading metadata fields…</p>
          ) : (metadataFields?.length ?? 0) === 0 ? (
            <p className="text-sm text-amber-700">
              Metadata fields could not be loaded from Keyfactor. Enrollment may fail metadata validation.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {metadataFields?.map((field) => renderMetadataField(field))}
            </div>
          )}
        </fieldset>
      </div>
    </CertificateModal>
  );
};
