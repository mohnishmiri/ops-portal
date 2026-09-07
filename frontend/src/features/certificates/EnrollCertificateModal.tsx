/**
 * Enroll Certificate modal — full Keyfactor PFX/CSR enrollment form.
 *
 * Matches the Keyfactor Command PFX Enrollment UI with sections:
 * - Certificate Authority Information (template, key algo, key size, CA)
 * - Certificate Subject Information (CN, O, OU, L, ST, C, Email)
 * - Custom Friendly Name
 * - Subject Alternative Names (add/remove table)
 * - Certificate Metadata (AT&T required fields)
 * - Password & Delivery options
 */

import React, { useMemo, useState } from "react";
import {
  EnrollRequest,
  EnrollResult,
  EnrollmentType,
  certificateErrorMessage,
  useEnrollCertificate,
  useLoadCertificateToAkv,
  useTemplates,
  useAuthorities,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";
import { AkvTarget, AkvTargetPicker, isAkvTargetComplete } from "./AkvTargetPicker";

interface EnrollCertificateModalProps {
  defaultCa?: string;
  defaultTemplate?: string;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

interface SanEntry { type: string; value: string; }

const KEY_ALGORITHMS = ["RSA"];
const KEY_SIZES = [2048, 3072, 4096];
const SERVER_TYPES = ["Linux", "Windows", "AIX", "Other"];
const ENVIRONMENTS = ["Production", "Pre-Production", "Performance", "UAT", "Development", "DR"];
const TLS_OPTIONS = ["Yes", "No"];
const PCI_OPTIONS = ["Yes", "No"];

export const EnrollCertificateModal: React.FC<EnrollCertificateModalProps> = ({
  defaultCa = "",
  defaultTemplate = "",
  onClose,
  onSuccess,
  onError,
}) => {
  const enroll = useEnrollCertificate();
  const { data: templates } = useTemplates();
  const { data: authorities } = useAuthorities();

  const [type, setType] = useState<EnrollmentType>("pfx");
  const [template, setTemplate] = useState(defaultTemplate);
  const [keyAlgorithm, setKeyAlgorithm] = useState("RSA");
  const [keySize, setKeySize] = useState(4096);
  const [ca, setCa] = useState(defaultCa);

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

  const [motsProfileId, setMotsProfileId] = useState("");
  const [requesterUserId, setRequesterUserId] = useState("");
  const [managerUserId, setManagerUserId] = useState("");
  const [serverType, setServerType] = useState("");
  const [environment, setEnvironment] = useState("");
  const [tlsTraffic, setTlsTraffic] = useState("");
  const [port, setPort] = useState("");
  const [pciData, setPciData] = useState("");

  const [password, setPassword] = useState("");
  const [useCustomPassword, setUseCustomPassword] = useState(false);
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

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!template.trim()) next.template = "Template is required";
    if (!ca.trim()) next.ca = "Certificate Authority is required";
    if (type === "pfx") {
      if (!commonName.trim()) next.commonName = "Common Name is required";
      if (useCustomPassword && !password.trim()) next.password = "Password is required (min 12 characters)";
      if (password.trim() && password.length < 12) next.password = "Password must be at least 12 characters";
      if (!motsProfileId.trim()) next.motsProfileId = "MOTS-Profile-ID is required";
      if (!requesterUserId.trim()) next.requesterUserId = "Requester ATT User ID is required";
      if (!managerUserId.trim()) next.managerUserId = "Manager ATT User ID is required";
      if (!serverType) next.serverType = "Server Type is required";
      if (!environment) next.environment = "Environment is required";
      if (!tlsTraffic) next.tlsTraffic = "TLS/Port Services is required";
      if (!port.trim()) next.port = "Port is required";
      if (!pciData) next.pciData = "PCI Data is required";
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

  const handleSubmit = async () => {
    if (!validate()) return;
    const payload: EnrollRequest = {
      enrollment_type: type,
      certificate_authority: ca.trim(),
      template: template.trim(),
      include_chain: includeChain,
      sans: sansPayload,
      key_type: keyAlgorithm,
      key_length: keySize,
      use_legacy_encryption: useLegacyEncryption,
    };
    if (type === "csr") {
      payload.csr = csr.trim();
    } else {
      payload.common_name = commonName.trim();
      payload.organization = organization.trim();
      payload.organizational_unit = orgUnit.trim();
      payload.city = city.trim();
      payload.state = state.trim();
      payload.country = country.trim();
      payload.email = email.trim() || undefined;
      payload.custom_friendly_name = friendlyName.trim() || undefined;
      payload.password = password || undefined;
      payload.owner_role_name = ownerRoleName.trim() || undefined;
      payload.mots_profile_id = motsProfileId.trim();
      payload.requester_att_user_id = requesterUserId.trim();
      payload.requester_att_manager_user_id = managerUserId.trim();
      payload.server_type = serverType;
      payload.environment = environment;
      payload.tls_port_services_internet_traffic = tlsTraffic;
      payload.port = port.trim();
      payload.pci_data = pciData;
    }
    try {
      const res = await enroll.mutateAsync(payload);
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
          ...(password ? { certificate_password: password } : {}),
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

        {/* CA Information */}
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Authority Information</legend>
          <div className="grid grid-cols-3 gap-3">
            <div><label className={fieldLabel}>Template *</label><select className={fieldInput} value={template} onChange={(e) => setTemplate(e.target.value)}><option value="">Select…</option>{templates?.map((t) => <option key={t.id} value={t.template_name}>{t.template_name}</option>)}{!templates?.length && <option value="Digicert-Standard-SHA2-4096Key">Digicert-Standard-SHA2-4096Key</option>}</select>{errors.template && <p className="mt-1 text-xs text-red-600">{errors.template}</p>}</div>
            <div><label className={fieldLabel}>Key Algorithm</label><select className={fieldInput} value={keyAlgorithm} onChange={(e) => setKeyAlgorithm(e.target.value)}>{KEY_ALGORITHMS.map((a) => <option key={a} value={a}>{a}</option>)}</select></div>
            <div><label className={fieldLabel}>Key Size</label><select className={fieldInput} value={keySize} onChange={(e) => setKeySize(Number(e.target.value))}>{KEY_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}</select></div>
          </div>
          <div><label className={fieldLabel}>Certificate Authority *</label><select className={fieldInput} value={ca} onChange={(e) => setCa(e.target.value)}><option value="">Auto-Select</option>{authorities?.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}</select>{errors.ca && <p className="mt-1 text-xs text-red-600">{errors.ca}</p>}</div>
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

            {/* AT&T Metadata */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Metadata</legend>
              <div className="grid grid-cols-2 gap-3">
                <div><label className={fieldLabel}>MOTS-Profile-ID *</label><input className={fieldInput} value={motsProfileId} onChange={(e) => setMotsProfileId(e.target.value)} placeholder="Enter MOTS-ID or iTap number" />{errors.motsProfileId && <p className="mt-1 text-xs text-red-600">{errors.motsProfileId}</p>}</div>
                <div><label className={fieldLabel}>Requester-ATT-User-ID *</label><input className={fieldInput} value={requesterUserId} onChange={(e) => setRequesterUserId(e.target.value)} placeholder="AT&T User ID" />{errors.requesterUserId && <p className="mt-1 text-xs text-red-600">{errors.requesterUserId}</p>}</div>
                <div><label className={fieldLabel}>Requester-ATT-Manager-User-ID *</label><input className={fieldInput} value={managerUserId} onChange={(e) => setManagerUserId(e.target.value)} placeholder="Manager AT&T User ID" />{errors.managerUserId && <p className="mt-1 text-xs text-red-600">{errors.managerUserId}</p>}</div>
                <div><label className={fieldLabel}>Server-Type *</label><select className={fieldInput} value={serverType} onChange={(e) => setServerType(e.target.value)}><option value="">Select…</option>{SERVER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select>{errors.serverType && <p className="mt-1 text-xs text-red-600">{errors.serverType}</p>}</div>
                <div><label className={fieldLabel}>Environment *</label><select className={fieldInput} value={environment} onChange={(e) => setEnvironment(e.target.value)}><option value="">Select…</option>{ENVIRONMENTS.map((e) => <option key={e} value={e}>{e}</option>)}</select>{errors.environment && <p className="mt-1 text-xs text-red-600">{errors.environment}</p>}</div>
                <div><label className={fieldLabel}>TLS-Port-Services-Internet-Traffic *</label><select className={fieldInput} value={tlsTraffic} onChange={(e) => setTlsTraffic(e.target.value)}><option value="">Select…</option>{TLS_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}</select>{errors.tlsTraffic && <p className="mt-1 text-xs text-red-600">{errors.tlsTraffic}</p>}</div>
                <div><label className={fieldLabel}>Port *</label><input className={fieldInput} value={port} onChange={(e) => setPort(e.target.value)} placeholder="Port(s) comma-separated" />{errors.port && <p className="mt-1 text-xs text-red-600">{errors.port}</p>}</div>
                <div><label className={fieldLabel}>PCI-Data *</label><select className={fieldInput} value={pciData} onChange={(e) => setPciData(e.target.value)}><option value="">Select…</option>{PCI_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}</select>{errors.pciData && <p className="mt-1 text-xs text-red-600">{errors.pciData}</p>}</div>
              </div>
            </fieldset>

            {/* Password */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Password (min 12 characters)</legend>
              <Toggle checked={useCustomPassword} onChange={() => setUseCustomPassword(!useCustomPassword)} label="Use Custom Password" />
              {useCustomPassword && <div><input type="password" className={fieldInput} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Minimum 12 characters" />{errors.password && <p className="mt-1 text-xs text-red-600">{errors.password}</p>}</div>}
            </fieldset>

            {/* Owner */}
            <fieldset className="space-y-2"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Certificate Owner</legend><div><label className={fieldLabel}>Owner Role Name</label><input className={fieldInput} value={ownerRoleName} onChange={(e) => setOwnerRoleName(e.target.value)} /></div></fieldset>

            {/* Chain & Legacy */}
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Chain Options</legend><Toggle checked={includeChain} onChange={() => setIncludeChain(!includeChain)} label="Include Chain" /></fieldset>
            <fieldset className="space-y-3"><legend className="text-sm font-semibold text-gray-800 border-b border-att-100 pb-2 w-full">Additional Options</legend><Toggle checked={useLegacyEncryption} onChange={() => setUseLegacyEncryption(!useLegacyEncryption)} label="Use Legacy Encryption" /></fieldset>
          </>
        )}
      </div>
    </CertificateModal>
  );
};
