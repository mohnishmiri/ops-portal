/**
 * Drill-down for one Key Vault secret, key, or certificate — the same
 * full-size layout as the AKS Deployment / Pod views: overview with KPI tiles,
 * the value (secrets, write roles only — every read is audited), version
 * history, which AKS AzureKeyVaultSecret objects sync it, and its audit trail.
 */

import React, { useCallback, useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { usePortalTimezone } from "../../contexts/TimezoneContext";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type CertificateDetailResponse,
  type KeyDetailResponse,
  type KeyVaultAksReference,
  type KeyVaultAuditEntry,
  type KeyVaultItemType,
  type KeyVaultItemVersion,
  type SecretInfo,
  useCertificateDetail,
  useDeleteCertificate,
  useDeleteKey,
  useDeleteSecret,
  useKeyDetail,
  useKeyVaultAksReferences,
  useKeyVaultAuditHistory,
  useKeyVaultItemVersions,
  useKeyVaults,
  useSecretValue,
  useVaultCertificates,
  useVaultKeys,
  useVaultSecrets,
} from "../../services/costApi";
import { DetailGrid, GridFilterSelect, type GridColumn } from "../aks/DetailGrid";
import { CopyButton, KeyValueGrid, Truncate } from "../aks/detailShared";
import {
  DetailCard,
  type DetailTab,
  KpiRow,
  PropertyList,
  ResourceDetailShell,
  ResourceKindIcons,
} from "../aks/ResourceDetailShell";
import {
  azurePortalUrl,
  Badge,
  DaysLeftBadge,
  daysUntil,
  decodeBase64Utf8,
  encodeBase64Utf8,
  expiryLabel,
  fmtDate,
  fmtDateTime,
  Icons,
  nameLinkClass,
} from "./kvShared";

export type ItemDetailTab = "overview" | "value" | "versions" | "aks" | "activity";

const KIND_LABEL: Record<KeyVaultItemType, string> = {
  secret: "Key Vault Secret",
  key: "Key Vault Key",
  certificate: "Key Vault Certificate",
};

const KIND_ICON: Record<KeyVaultItemType, React.ReactNode> = {
  secret: Icons.secret("h-[22px] w-[22px]"),
  key: ResourceKindIcons.keyvault,
  certificate: Icons.certificate("h-[22px] w-[22px]"),
};

/** The fields every list row (secret, key, certificate) has in common. */
interface ItemSummary {
  name: string;
  id: string;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  expires: string | null;
  not_before: string | null;
  tags: Record<string, string>;
  managed?: boolean;
  content_type?: string;
  cn_name?: string;
  san?: string[];
  serial_number?: string | null;
  thumbprint?: string;
}

const AKVS_STATUS_STYLES: Record<string, string> = {
  Synced: "bg-green-100 text-green-700",
  Failed: "bg-red-100 text-red-700",
  Degraded: "bg-amber-100 text-amber-700",
  Pending: "bg-blue-100 text-blue-700",
  EnvInjector: "bg-indigo-100 text-indigo-700",
};

export function AksStatusPill({ status }: { status: string | null }) {
  const value = status || "Unknown";
  return (
    <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${AKVS_STATUS_STYLES[value] ?? "bg-gray-100 text-gray-700"}`}>
      {value === "EnvInjector" ? "Env Injector" : value}
    </span>
  );
}

const ghostButton =
  "inline-flex items-center gap-1.5 rounded-lg border border-att-200 bg-white px-3 py-1.5 text-sm font-medium text-att-700 hover:bg-att-50";

// ── Secret value ──────────────────────────────────────────────────────

/**
 * A secret's value — current, or one version. Mounting this reads the value,
 * which the API records in the audit log, so it is only rendered on request.
 */
export function SecretValuePanel({ vaultUri, name, version }: { vaultUri: string; name: string; version?: string }) {
  const { timezone } = usePortalTimezone();
  const { data, isLoading, isError, error } = useSecretValue(vaultUri, name, version);
  const [view, setView] = useState<"raw" | "decoded">("raw");

  const decoded = useMemo(() => (data ? data.decoded_value ?? decodeBase64Utf8(data.value) : null), [data]);
  const encoded = useMemo(() => {
    if (!data?.value || decoded !== null) return null;
    try {
      return encodeBase64Utf8(data.value);
    } catch {
      return null;
    }
  }, [data, decoded]);

  if (isLoading) return <p className="text-sm text-slate-500">Reading secret value…</p>;
  if (isError) return <p className="text-sm text-red-600">Failed to read the secret value: {formatAxiosError(error, "Unknown error")}</p>;
  if (!data) return null;

  const shown = view === "decoded" && decoded !== null ? decoded : data.value;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {data.version && (
          <span>
            Version <span className="font-mono text-slate-700">{data.version}</span>
          </span>
        )}
        <span>· Content type {data.content_type || "—"}</span>
        <span>· Updated {fmtDateTime(data.updated, timezone)}</span>
        {decoded !== null && <Badge label="Base64 value" color="blue" />}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-lg border border-att-200 text-xs" role="group" aria-label="Value view">
          <button
            type="button"
            onClick={() => setView("raw")}
            className={`px-3 py-1.5 ${view === "raw" ? "bg-att-600 text-white" : "bg-white text-att-700 hover:bg-att-50"}`}
          >
            Raw
          </button>
          <button
            type="button"
            onClick={() => setView("decoded")}
            disabled={decoded === null}
            title={decoded === null ? "This value is not Base64-encoded text" : "Show the Base64-decoded text"}
            className={`border-l border-att-200 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40 ${
              view === "decoded" ? "bg-att-600 text-white" : "bg-white text-att-700 hover:bg-att-50"
            }`}
          >
            Decoded (Base64 → UTF-8)
          </button>
        </div>
        <CopyButton value={shown} label={view === "decoded" && decoded !== null ? "Copy decoded" : "Copy value"} />
        {encoded && <CopyButton value={encoded} label="Copy as Base64" />}
      </div>
      <textarea
        readOnly
        value={shown}
        rows={Math.min(12, Math.max(3, shown.split("\n").length))}
        aria-label={`Value of ${name}`}
        className="w-full resize-y rounded-lg border border-att-100 bg-slate-50 p-3 font-mono text-xs text-slate-800 focus:outline-none"
      />
    </div>
  );
}

// ── Key & certificate specifics ───────────────────────────────────────

function downloadText(text: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function KeyMaterial({ data, name }: { data: KeyDetailResponse; name: string }) {
  const jwk = [
    data.e && { label: "Exponent (e)", value: data.e },
    data.n && { label: "Modulus (n)", value: data.n },
    data.x && { label: "X coordinate", value: data.x },
    data.y && { label: "Y coordinate", value: data.y },
  ].filter((f): f is { label: string; value: string } => !!f);
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <DetailCard title="Key">
        <PropertyList
          items={[
            { label: "Key Type", value: data.kty, mono: true },
            data.key_size && { label: "Key Size", value: `${data.key_size} bits` },
            data.crv && { label: "Curve", value: data.crv },
            { label: "Recovery Level", value: data.recovery_level },
            {
              label: "Permitted Operations",
              wide: true,
              value: data.key_ops?.length ? (
                <span className="flex flex-wrap gap-1">{data.key_ops.map((op) => <Badge key={op} label={op} color="blue" />)}</span>
              ) : null,
            },
          ]}
        />
      </DetailCard>
      <DetailCard
        title="Public Key"
        subtitle="Private key material never leaves Key Vault — signing and decryption run in the vault."
        actions={
          data.public_key_pem ? (
            <div className="flex items-center gap-2">
              <CopyButton value={data.public_key_pem} label="Copy PEM" />
              <button
                type="button"
                onClick={() => downloadText(data.public_key_pem!, `${name}.pub.pem`, "application/x-pem-file")}
                className="rounded border border-att-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-att-700 hover:bg-att-50"
              >
                Download .pem
              </button>
            </div>
          ) : undefined
        }
      >
        {jwk.length === 0 && !data.public_key_pem ? (
          <p className="text-sm text-slate-400">No public component (symmetric key).</p>
        ) : (
          <div className="space-y-2">
            {jwk.map((f) => (
              <div key={f.label} className="flex items-center gap-2">
                <span className="w-28 shrink-0 text-xs text-slate-500">{f.label}</span>
                <code className="min-w-0 flex-1 truncate rounded border border-att-100 bg-slate-50 px-2 py-1 font-mono text-xs" title={f.value}>
                  {f.value}
                </code>
                <CopyButton value={f.value} />
              </div>
            ))}
            {data.public_key_pem && (
              <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-all rounded-lg border border-att-100 bg-slate-50 p-3 font-mono text-xs">
                {data.public_key_pem}
              </pre>
            )}
          </div>
        )}
      </DetailCard>
    </div>
  );
}

function CertificateIdentity({ data, timezone }: { data: CertificateDetailResponse; timezone: string }) {
  const hex = (label: string, value: string | null | undefined) =>
    value ? (
      <span className="flex items-center gap-2">
        <span className="break-all font-mono text-xs">{value}</span>
        <CopyButton value={value} />
      </span>
    ) : null;
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <DetailCard title="Subject">
        <PropertyList
          items={[
            { label: "Common Name (CN)", value: data.cn_name, mono: true, wide: true },
            { label: "Subject", value: data.subject, mono: true, wide: true },
            {
              label: `Subject Alternative Names (${data.san?.length ?? 0})`,
              wide: true,
              value: data.san?.length ? (
                <span className="flex flex-wrap gap-1">
                  {data.san.map((s) => (
                    <span key={s} className="rounded bg-blue-50 px-1.5 py-0.5 font-mono text-[11px] text-blue-700">{s}</span>
                  ))}
                </span>
              ) : null,
            },
            { label: "Issued By", value: data.issuer_cn || null },
            { label: "Issuer (policy)", value: data.issuer_name || null },
          ]}
        />
      </DetailCard>
      <DetailCard title="Fingerprints & Policy">
        <PropertyList
          items={[
            { label: "Thumbprint (SHA-1)", value: hex("sha1", data.thumbprint), wide: true },
            data.thumbprint_sha256 && { label: "Thumbprint (SHA-256)", value: hex("sha256", data.thumbprint_sha256), wide: true },
            { label: "Serial Number", value: hex("serial", data.serial_number), wide: true },
            { label: "Key Type", value: data.key_type || null },
            data.key_size && { label: "Key Size", value: `${data.key_size} bits` },
            data.validity_months && { label: "Validity", value: `${data.validity_months} months` },
            { label: "Auto-Renew", value: <Badge label={data.auto_renew ? "Yes" : "No"} color={data.auto_renew ? "green" : "gray"} /> },
            { label: "Valid From", value: fmtDate(data.not_before, timezone) },
            { label: "Valid To", value: fmtDate(data.expires, timezone) },
            {
              label: "Key Usage",
              wide: true,
              value: data.key_usage?.length ? (
                <span className="flex flex-wrap gap-1">{data.key_usage.map((u) => <Badge key={u} label={u} color="blue" />)}</span>
              ) : null,
            },
          ]}
        />
      </DetailCard>
    </div>
  );
}

// ── Grids ─────────────────────────────────────────────────────────────

function VersionsGrid({
  versions,
  itemType,
  vaultUri,
  name,
  canReadValues,
  timezone,
}: {
  versions: KeyVaultItemVersion[];
  itemType: KeyVaultItemType;
  vaultUri: string;
  name: string;
  canReadValues: boolean;
  timezone: string;
}) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const columns: GridColumn<KeyVaultItemVersion>[] = [
    {
      key: "version",
      header: "Version",
      sortValue: (v) => v.version,
      render: (v) => (
        <span className="inline-flex items-center gap-2">
          <Truncate value={v.version} className="font-mono text-xs" maxWidth="max-w-[16rem]" />
          {v.is_current && <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">current</span>}
        </span>
      ),
    },
    {
      key: "enabled",
      header: "Status",
      sortValue: (v) => (v.enabled ? 1 : 0),
      render: (v) => <Badge label={v.enabled ? "Enabled" : "Disabled"} color={v.enabled ? "green" : "red"} />,
    },
    { key: "created", header: "Created", sortValue: (v) => v.created ?? "", render: (v) => <span className="whitespace-nowrap text-xs">{fmtDateTime(v.created, timezone)}</span> },
    { key: "not_before", header: "Activation", sortValue: (v) => v.not_before ?? "", render: (v) => <span className="whitespace-nowrap text-xs">{fmtDate(v.not_before, timezone)}</span> },
    {
      key: "expires",
      header: "Expires",
      sortValue: (v) => v.expires ?? "9999",
      render: (v) => (
        <span className="inline-flex items-center gap-2 whitespace-nowrap text-xs">
          {fmtDate(v.expires, timezone)}
          {v.expires && <DaysLeftBadge days={daysUntil(v.expires)} />}
        </span>
      ),
    },
    ...(itemType === "certificate"
      ? [{ key: "thumbprint", header: "Thumbprint", render: (v: KeyVaultItemVersion) => <Truncate value={v.thumbprint} className="font-mono text-xs" maxWidth="max-w-[14rem]" /> }]
      : itemType === "secret"
        ? [{ key: "content_type", header: "Content Type", render: (v: KeyVaultItemVersion) => <span className="text-xs">{v.content_type || "—"}</span> }]
        : []),
    ...(canReadValues
      ? [
          {
            key: "value",
            header: "Value",
            render: (v: KeyVaultItemVersion) => (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setRevealed((prev) => (prev === v.version ? null : v.version));
                }}
                className="whitespace-nowrap rounded border border-att-200 bg-white px-2 py-0.5 text-xs font-medium text-att-700 hover:bg-att-50"
              >
                {revealed === v.version ? "Hide value" : "Show value"}
              </button>
            ),
          },
        ]
      : []),
  ];
  return (
    <DetailGrid
      title="Versions"
      rows={versions}
      columns={columns}
      rowKey={(v) => v.version}
      searchText={(v) => `${v.version} ${v.content_type ?? ""} ${v.thumbprint}`}
      searchPlaceholder="Search version…"
      emptyText="No versions"
      initialSort={{ key: "created", direction: "desc" }}
      expandedKey={revealed}
      renderExpanded={(v) => <SecretValuePanel vaultUri={vaultUri} name={name} version={v.version} />}
    />
  );
}

export function AksReferencesGrid({
  references,
  timezone,
  showObject = false,
  onOpenObject,
  emptyText,
}: {
  references: KeyVaultAksReference[];
  timezone: string;
  /** Show which vault object each reference reads (vault-level view). */
  showObject?: boolean;
  /** Makes the vault object a link to its own detail view. */
  onOpenObject?: (reference: KeyVaultAksReference) => void;
  emptyText: string;
}) {
  const [status, setStatus] = useState("all");
  const rows = status === "all" ? references : references.filter((r) => (status === "problems" ? r.status === "Failed" || r.status === "Degraded" : r.status === status));
  const columns: GridColumn<KeyVaultAksReference>[] = [
    { key: "cluster", header: "Cluster", sortValue: (r) => r.cluster_name, render: (r) => <span className="whitespace-nowrap font-medium text-slate-800">{r.cluster_name}</span> },
    { key: "namespace", header: "Namespace", sortValue: (r) => r.namespace ?? "", render: (r) => <span className="whitespace-nowrap">{r.namespace || "—"}</span> },
    { key: "name", header: "AzureKeyVaultSecret", sortValue: (r) => r.name ?? "", render: (r) => <Truncate value={r.name} className="font-mono text-xs" maxWidth="max-w-[16rem]" /> },
    ...(showObject
      ? [
          {
            key: "object",
            header: "Vault Object",
            sortValue: (r: KeyVaultAksReference) => r.object_name ?? "",
            render: (r: KeyVaultAksReference) => (
              <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                {onOpenObject && r.object_name ? (
                  <button type="button" onClick={() => onOpenObject(r)} className={`${nameLinkClass} font-mono text-xs`}>
                    {r.object_name}
                  </button>
                ) : (
                  <span className="font-mono text-xs">{r.object_name || "—"}</span>
                )}
                <span className="text-[11px] text-slate-400">{r.object_type}</span>
              </span>
            ),
          },
        ]
      : []),
    {
      key: "output",
      header: "Writes To",
      sortValue: (r) => r.output_name ?? "",
      render: (r) =>
        r.output_kind === "env-injection" ? (
          <span className="text-xs text-slate-500">Env injection (no output object)</span>
        ) : (
          <span className="whitespace-nowrap text-xs">
            {r.output_kind === "configmap" ? "ConfigMap" : "Secret"} <span className="font-mono">{r.output_name || "—"}</span>
            {r.output_data_key && <span className="text-slate-500"> · key {r.output_data_key}</span>}
          </span>
        ),
    },
    {
      key: "version",
      header: "Version",
      render: (r) => (r.object_version ? <Truncate value={r.object_version} className="font-mono text-xs" maxWidth="max-w-[8rem]" /> : <span className="text-xs text-slate-500">latest</span>),
    },
    { key: "status", header: "Status", sortValue: (r) => r.status ?? "", render: (r) => <span title={r.status_reason ?? ""}><AksStatusPill status={r.status} /></span> },
    { key: "synced", header: "Last Synced From Azure", sortValue: (r) => r.last_azure_update ?? "", render: (r) => <span className="whitespace-nowrap text-xs">{fmtDateTime(r.last_azure_update, timezone)}</span> },
  ];
  return (
    <DetailGrid
      title="Used by AKS (akv2k8s)"
      rows={rows}
      columns={columns}
      rowKey={(r) => `${r.cluster_id}/${r.namespace}/${r.name}`}
      searchText={(r) => `${r.cluster_name} ${r.namespace} ${r.name} ${r.object_name} ${r.output_name} ${r.output_data_key}`}
      searchPlaceholder="Search cluster, namespace, output…"
      emptyText={emptyText}
      initialSort={{ key: "cluster", direction: "asc" }}
      toolbar={
        <GridFilterSelect
          label="Filter by sync status"
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: "All statuses" },
            { value: "Synced", label: "Synced" },
            { value: "problems", label: "Failed or Degraded" },
            { value: "Pending", label: "Pending" },
            { value: "EnvInjector", label: "Env Injector" },
          ]}
        />
      }
    />
  );
}

const ACTION_LABELS: Record<string, { label: string; color: "green" | "blue" | "red" | "purple" | "gray" }> = {
  create: { label: "Create", color: "green" },
  update: { label: "Update", color: "blue" },
  delete: { label: "Delete", color: "red" },
  view: { label: "Viewed value", color: "purple" },
  search: { label: "Value search", color: "purple" },
  bulk: { label: "Bulk upload", color: "green" },
};

export function auditActionBadge(action: string) {
  const prefix = action.split("_")[0];
  const meta = ACTION_LABELS[prefix];
  return meta ? <Badge label={meta.label} color={meta.color} /> : <Badge label={action} color="gray" />;
}

export const isReadAction = (action: string) => action === "view_secret_value" || action === "search_secret_values";

function ActivityGrid({ entries, timezone }: { entries: KeyVaultAuditEntry[]; timezone: string }) {
  const columns: GridColumn<KeyVaultAuditEntry>[] = [
    { key: "time", header: "Time", sortValue: (e) => e.timestamp ?? "", render: (e) => <span className="whitespace-nowrap text-xs">{fmtDateTime(e.timestamp, timezone)}</span> },
    { key: "action", header: "Action", sortValue: (e) => e.action, render: (e) => auditActionBadge(e.action) },
    {
      key: "status",
      header: "Result",
      sortValue: (e) => e.status,
      render: (e) => <Badge label={e.status === "success" ? "Success" : "Failed"} color={e.status === "success" ? "green" : "red"} />,
    },
    { key: "user", header: "User", sortValue: (e) => e.user_email || e.user_id, render: (e) => <span className="text-xs">{e.user_email || e.user_id}</span> },
    { key: "summary", header: "Summary", render: (e) => <span className="text-xs text-slate-600">{e.summary}</span> },
  ];
  return (
    <DetailGrid
      title="Activity"
      rows={entries}
      columns={columns}
      rowKey={(e) => String(e.id)}
      searchText={(e) => `${e.action} ${e.user_email ?? ""} ${e.user_id} ${e.summary}`}
      searchPlaceholder="Search user, action…"
      emptyText="No portal activity recorded in the last 365 days."
      initialSort={{ key: "time", direction: "desc" }}
    />
  );
}

// ── Delete confirmation ───────────────────────────────────────────────

function ConfirmDelete({
  itemType,
  name,
  vaultName,
  pending,
  error,
  onConfirm,
  onCancel,
}: {
  itemType: KeyVaultItemType;
  name: string;
  vaultName: string;
  pending: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div role="alertdialog" aria-modal="true" aria-label={`Delete ${itemType}`} className="w-[480px] max-w-full rounded-2xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-800">Delete {itemType}</h3>
        <p className="mt-2 text-sm text-slate-600">
          Delete <span className="font-mono font-semibold">{name}</span> from <span className="font-semibold">{vaultName}</span>? It is soft-deleted and can be
          recovered in Azure until the vault's retention period ends.
        </p>
        {error && <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-600 hover:bg-slate-200">Cancel</button>
          <button type="button" onClick={onConfirm} disabled={pending} className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-50">
            {pending ? "Deleting…" : `Delete ${itemType}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── The view ──────────────────────────────────────────────────────────

export function KeyVaultItemDetail({
  vaultUri,
  vaultName,
  itemType,
  name,
  initialTab = "overview",
  canWrite,
  onClose,
  onOpenVault,
  renderSecretEditor,
  onDeleted,
}: {
  vaultUri: string;
  vaultName: string;
  itemType: KeyVaultItemType;
  name: string;
  initialTab?: ItemDetailTab;
  canWrite: boolean;
  onClose: () => void;
  /** Opens the vault's own detail view (the vault link in the header). */
  onOpenVault?: () => void;
  /** The update dialog for a secret, rendered inside this view so it stacks above it. */
  renderSecretEditor?: (secret: SecretInfo, close: () => void) => React.ReactNode;
  onDeleted?: (message: string) => void;
}) {
  const { timezone } = usePortalTimezone();
  // Reading a secret's value requires write, like the API (GET /keyvault/secrets/{name}).
  const canReadValues = itemType === "secret" && canWrite;
  const [tab, setTab] = useState<ItemDetailTab>(initialTab === "value" && !canReadValues ? "overview" : initialTab);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // List rows are DB-backed and shared with the vault tabs' cache.
  const secrets = useVaultSecrets(itemType === "secret" ? vaultUri : null);
  const keys = useVaultKeys(itemType === "key" ? vaultUri : null);
  const certs = useVaultCertificates(itemType === "certificate" ? vaultUri : null);
  const list = itemType === "secret" ? secrets : itemType === "key" ? keys : certs;
  const listed = useMemo(
    () => ((list.data ?? []) as ItemSummary[]).find((i) => i.name.toLowerCase() === name.toLowerCase()) ?? null,
    [list.data, name],
  );

  const versions = useKeyVaultItemVersions(vaultUri, itemType, name);
  const references = useKeyVaultAksReferences(vaultUri, name, itemType);
  const history = useKeyVaultAuditHistory(vaultUri, 500, 365, { type: itemType, name });
  const keyDetail = useKeyDetail(itemType === "key" ? vaultUri : null, itemType === "key" ? name : null);
  const certDetail = useCertificateDetail(itemType === "certificate" ? vaultUri : null, itemType === "certificate" ? name : null);
  const { data: vaults } = useKeyVaults();
  const vaultResourceId = vaults?.find((v) => v.name === vaultName)?.id;

  const deleteSecret = useDeleteSecret();
  const deleteKey = useDeleteKey();
  const deleteCert = useDeleteCertificate();
  const deleteMutation = itemType === "secret" ? deleteSecret : itemType === "key" ? deleteKey : deleteCert;

  const current = versions.data?.find((v) => v.is_current) ?? null;
  // The synced row, else the live current version when the item is not in the snapshot yet.
  const item: ItemSummary | null =
    listed ??
    (current
      ? {
          name,
          id: current.id,
          enabled: current.enabled,
          created: current.created,
          updated: current.updated,
          expires: current.expires,
          not_before: current.not_before,
          tags: current.tags,
          managed: current.managed,
          content_type: itemType === "secret" ? current.content_type ?? undefined : undefined,
        }
      : null);

  const activity = history.data?.history ?? [];
  const refs = references.data ?? [];
  const failingRefs = refs.filter((r) => r.status === "Failed" || r.status === "Degraded").length;
  const days = daysUntil(item?.expires);
  const managed = !!item?.managed;

  const handleDelete = useCallback(() => {
    deleteMutation.mutate(
      { vaultUri, name },
      {
        onSuccess: () => {
          setConfirmingDelete(false);
          onDeleted?.(`${itemType[0].toUpperCase()}${itemType.slice(1)} ${name} deleted`);
          onClose();
        },
      },
    );
  }, [deleteMutation, vaultUri, name, itemType, onDeleted, onClose]);

  const tabs: DetailTab<ItemDetailTab>[] = [
    { key: "overview", label: "Overview" },
    ...(canReadValues ? [{ key: "value" as const, label: "Value" }] : []),
    { key: "versions", label: "Versions", count: versions.data?.length },
    { key: "aks", label: "Used by AKS", count: references.data?.length, attention: failingRefs > 0 },
    { key: "activity", label: "Activity", count: history.data?.history.length },
  ];

  const loadError = list.isError && versions.isError && !item ? formatAxiosError(versions.error, `Failed to load this ${itemType}.`) : null;

  return (
    <>
      <ResourceDetailShell
        kind={KIND_LABEL[itemType]}
        name={name}
        icon={KIND_ICON[itemType]}
        status={
          item && (
            <span className="inline-flex items-center gap-1.5">
              <Badge label={item.enabled ? "Enabled" : "Disabled"} color={item.enabled ? "green" : "red"} />
              {item.expires && <DaysLeftBadge days={days} />}
            </span>
          )
        }
        meta={
          <>
            <span>
              Vault{" "}
              {onOpenVault ? (
                <button type="button" onClick={onOpenVault} className="font-medium text-blue-600 hover:text-blue-800 hover:underline">
                  {vaultName}
                </button>
              ) : (
                <span className="font-medium text-slate-700">{vaultName}</span>
              )}
            </span>
            {item?.content_type && <span>Content type {item.content_type}</span>}
            {managed && <span className="rounded bg-purple-100 px-1.5 py-0.5 text-xs font-medium text-purple-800">Managed by a certificate</span>}
          </>
        }
        actions={
          <>
            {vaultResourceId && (
              <a
                href={azurePortalUrl(vaultResourceId, itemType === "secret" ? "secrets" : itemType === "key" ? "keys" : "certificates")}
                target="_blank"
                rel="noreferrer"
                className={ghostButton}
              >
                Azure portal {Icons.external()}
              </a>
            )}
            {canWrite && itemType === "secret" && !managed && listed && renderSecretEditor && (
              <button type="button" onClick={() => setEditing(true)} className={ghostButton}>
                {Icons.edit("h-4 w-4")} New version
              </button>
            )}
            {canWrite && !managed && item && (
              <button
                type="button"
                onClick={() => {
                  deleteMutation.reset();
                  setConfirmingDelete(true);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50"
              >
                {Icons.trash("h-4 w-4")} Delete
              </button>
            )}
          </>
        }
        tabs={tabs}
        activeTab={tab}
        onTabChange={setTab}
        isLoading={list.isLoading && versions.isLoading}
        error={loadError}
        onClose={onClose}
      >
        {tab === "overview" && (
          <>
            {!item && !list.isLoading && !versions.isLoading && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {versions.isError
                  ? `Azure could not be read for this ${itemType}: ${formatAxiosError(versions.error, "request failed")}`
                  : `This ${itemType} is not in the synced inventory — it may have been deleted.`}
              </div>
            )}
            <KpiRow>
              <MetricCard
                title="Status"
                value={item ? (item.enabled ? "Enabled" : "Disabled") : "—"}
                subtitle={item ? `Updated ${fmtDate(item.updated, timezone)}` : undefined}
                icon={MetricCardIcons.checkCircle()}
                tone={item ? (item.enabled ? "green" : "red") : "slate"}
              />
              <MetricCard
                title="Expires"
                value={item?.expires ? (days !== null && days < 0 ? "Expired" : expiryLabel(days)) : "Never"}
                subtitle={item?.expires ? fmtDate(item.expires, timezone) : "No expiry date set"}
                icon={MetricCardIcons.calendar()}
                tone={!item?.expires ? "slate" : days !== null && days < 0 ? "red" : days !== null && days <= 30 ? "amber" : "green"}
                onClick={() => setTab("versions")}
                actionLabel="Show the expiry of every version"
              />
              <MetricCard
                title="Versions"
                value={versions.data ? versions.data.length : versions.isError ? "—" : "…"}
                subtitle={current ? `Current since ${fmtDate(current.created, timezone)}` : versions.isError ? "Could not read versions" : undefined}
                icon={MetricCardIcons.layers()}
                tone="att"
                onClick={() => setTab("versions")}
                actionLabel="Show version history"
              />
              <MetricCard
                title="Used by AKS"
                value={references.data ? refs.length : "…"}
                subtitle={refs.length ? (failingRefs ? `${failingRefs} failing to sync` : "All syncing") : "No AzureKeyVaultSecret reads it"}
                icon={MetricCardIcons.server()}
                tone={failingRefs ? "red" : refs.length ? "indigo" : "slate"}
                onClick={() => setTab("aks")}
                actionLabel="Show the AKS objects that sync it"
              />
            </KpiRow>

            <DetailCard title="Properties">
              <PropertyList
                items={[
                  { label: "Name", value: name, mono: true },
                  { label: "Vault", value: vaultName },
                  {
                    label: "Identifier",
                    wide: true,
                    value: item?.id ? (
                      <span className="flex items-center gap-2">
                        <span className="break-all font-mono text-xs">{item.id}</span>
                        <CopyButton value={item.id} />
                      </span>
                    ) : null,
                  },
                  current && {
                    label: "Current Version",
                    wide: true,
                    value: (
                      <span className="flex items-center gap-2">
                        <span className="break-all font-mono text-xs">{current.version}</span>
                        <CopyButton value={current.id} label="Copy versioned ID" />
                      </span>
                    ),
                  },
                  itemType === "secret" && { label: "Content Type", value: item?.content_type || null },
                  { label: "Created", value: fmtDateTime(item?.created, timezone) },
                  { label: "Updated", value: fmtDateTime(item?.updated, timezone) },
                  { label: "Activation (Not Before)", value: fmtDate(item?.not_before, timezone) },
                  {
                    label: "Expires",
                    value: item?.expires ? (
                      <span className="inline-flex items-center gap-2">
                        {fmtDate(item.expires, timezone)} <DaysLeftBadge days={days} />
                      </span>
                    ) : (
                      "Never"
                    ),
                  },
                  current?.recovery_level && { label: "Recovery Level", value: current.recovery_level },
                  itemType !== "certificate" && {
                    label: "Managed",
                    value: managed ? "Yes — backs a certificate; renew the certificate instead of editing it" : "No",
                  },
                  itemType === "certificate" && item?.cn_name && { label: "Common Name (CN)", value: item.cn_name, mono: true },
                ]}
              />
            </DetailCard>

            {itemType === "key" &&
              (keyDetail.data ? (
                <KeyMaterial data={keyDetail.data} name={name} />
              ) : keyDetail.isError ? (
                <p className="text-sm text-red-600">Key material could not be read: {formatAxiosError(keyDetail.error, "Unknown error")}</p>
              ) : (
                <p className="text-sm text-slate-500">Loading key material…</p>
              ))}
            {itemType === "certificate" &&
              (certDetail.data ? (
                <CertificateIdentity data={certDetail.data} timezone={timezone} />
              ) : certDetail.isError ? (
                <p className="text-sm text-red-600">Certificate details could not be read: {formatAxiosError(certDetail.error, "Unknown error")}</p>
              ) : (
                <p className="text-sm text-slate-500">Loading certificate details…</p>
              ))}

            <KeyValueGrid title="Tags" entries={item?.tags ?? {}} emptyText="No tags" />
          </>
        )}

        {tab === "value" && canReadValues && (
          <DetailCard title="Current Value" subtitle="Every read of a secret value is recorded in the Key Vault audit history.">
            <SecretValuePanel vaultUri={vaultUri} name={name} />
          </DetailCard>
        )}

        {tab === "versions" &&
          (versions.isError ? (
            <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Could not list versions: {formatAxiosError(versions.error, "Unknown error")}
            </p>
          ) : versions.isLoading ? (
            <p className="text-sm text-slate-500">Loading versions…</p>
          ) : (
            <VersionsGrid
              versions={versions.data ?? []}
              itemType={itemType}
              vaultUri={vaultUri}
              name={name}
              canReadValues={canReadValues}
              timezone={timezone}
            />
          ))}

        {tab === "aks" &&
          (references.isError ? (
            <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Could not load AKS references: {formatAxiosError(references.error, "Unknown error")}
            </p>
          ) : (
            <AksReferencesGrid
              references={refs}
              timezone={timezone}
              emptyText={`No AzureKeyVaultSecret in the AKS inventory reads this ${itemType}. References come from AKS Operations → AKV Sync; sync a cluster there to refresh them.`}
            />
          ))}

        {tab === "activity" &&
          (history.isError ? (
            <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Could not load activity: {formatAxiosError(history.error, "Unknown error")}
            </p>
          ) : (
            <ActivityGrid entries={activity} timezone={timezone} />
          ))}
      </ResourceDetailShell>

      {editing && listed && renderSecretEditor?.(listed as SecretInfo, () => setEditing(false))}
      {confirmingDelete && (
        <ConfirmDelete
          itemType={itemType}
          name={name}
          vaultName={vaultName}
          pending={deleteMutation.isPending}
          error={deleteMutation.isError ? formatAxiosError(deleteMutation.error, `Failed to delete ${itemType}`) : null}
          onConfirm={handleDelete}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </>
  );
}

export default KeyVaultItemDetail;
