/**
 * Drill-down for one Azure Key Vault, in the same full-size layout as the AKS
 * Deployment view: overview tiles and properties, its secrets / keys /
 * certificates (the page's own grids, passed in), expiring items, network
 * rules and private endpoints, access policies, the AKS objects that sync
 * from it, its audit trail, and the raw ARM resource.
 */

import React, { useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { usePortalTimezone } from "../../contexts/TimezoneContext";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type ExpiringItem,
  type KeyVaultAksReference,
  type KeyVaultItemType,
  type VaultAccessPolicy,
  type VaultPrivateEndpoint,
  type VaultSummary,
  useKeyVaultAksReferences,
  useVaultDetail,
} from "../../services/costApi";
import { DetailGrid, type GridColumn } from "../aks/DetailGrid";
import { CopyButton, KeyValueGrid, Truncate } from "../aks/detailShared";
import { DetailCard, type DetailTab, KpiRow, PropertyList, ResourceDetailShell } from "../aks/ResourceDetailShell";
import { AksReferencesGrid } from "./KeyVaultItemDetail";
import { azurePortalUrl, Badge, fmtDateTime, Icons } from "./kvShared";

export type VaultDetailTab =
  | "overview"
  | "secrets"
  | "keys"
  | "certificates"
  | "expiring"
  | "network"
  | "access"
  | "aks"
  | "activity"
  | "json";

const yesNo = (value: boolean | null | undefined) =>
  value === null || value === undefined ? null : <Badge label={value ? "Enabled" : "Disabled"} color={value ? "green" : "gray"} />;

/** "/subscriptions/…/virtualNetworks/vnet-a/subnets/snet-b" → "vnet-a / snet-b". */
function subnetLabel(id: string): string {
  const parts = id.split("/");
  const at = (key: string) => {
    const i = parts.findIndex((p) => p.toLowerCase() === key);
    return i >= 0 ? parts[i + 1] : undefined;
  };
  const vnet = at("virtualnetworks");
  const subnet = at("subnets");
  return vnet && subnet ? `${vnet} / ${subnet}` : id;
}

function PermissionChips({ values }: { values: string[] }) {
  if (!values.length) return <span className="text-xs text-slate-400">—</span>;
  const all = values.some((v) => v.toLowerCase() === "all");
  return (
    <span className="flex max-w-[16rem] flex-wrap gap-1" title={values.join(", ")}>
      {all ? (
        <Badge label="All" color="purple" />
      ) : (
        values.slice(0, 6).map((v) => <span key={v} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700">{v}</span>)
      )}
      {!all && values.length > 6 && <span className="text-[11px] text-slate-500">+{values.length - 6}</span>}
    </span>
  );
}

function JsonViewer({ value, fileName }: { value: unknown; fileName: string }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const lines = text.split("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };
  return (
    <DetailCard
      title="Azure Resource (ARM)"
      subtitle={`${lines.length} lines · live from Azure Resource Manager`}
      actions={
        <div className="flex items-center gap-2">
          <CopyButton value={text} label="Copy JSON" />
          <button type="button" onClick={download} className="rounded border border-att-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-att-700 hover:bg-att-50">
            Download
          </button>
        </div>
      }
    >
      <div className="max-h-[60vh] overflow-auto rounded-lg bg-slate-950 py-2 font-mono text-xs leading-5">
        <table className="border-collapse">
          <tbody>
            {lines.map((line, i) => (
              <tr key={i}>
                <td className="select-none px-3 text-right align-top text-slate-500">{i + 1}</td>
                <td className="whitespace-pre pr-6 text-slate-100">{line || " "}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DetailCard>
  );
}

export function VaultDetailModal({
  vaultName,
  vaultUri,
  summary,
  expiring,
  sections,
  initialTab = "overview",
  actions,
  onOpenItem,
  onClose,
}: {
  vaultName: string;
  vaultUri: string;
  /** The dashboard row (synced item counts). */
  summary?: VaultSummary;
  /** This vault's expired and expiring items. */
  expiring: ExpiringItem[];
  /** The page's grids for this vault, shown on the matching tabs. */
  sections: Record<"secrets" | "keys" | "certificates" | "expiring" | "activity", React.ReactNode>;
  initialTab?: VaultDetailTab;
  /** Extra header buttons, e.g. "Sync vault". */
  actions?: React.ReactNode;
  onOpenItem: (type: KeyVaultItemType, name: string) => void;
  onClose: () => void;
}) {
  const { timezone } = usePortalTimezone();
  const [tab, setTab] = useState<VaultDetailTab>(initialTab);
  const { data, isLoading, isError, error } = useVaultDetail(vaultUri);
  const references = useKeyVaultAksReferences(vaultUri);

  const vault = data?.vault;
  const props = data?.properties ?? null;
  const counts = {
    secrets: summary?.secrets_count ?? vault?.secrets_count,
    keys: summary?.keys_count ?? vault?.keys_count,
    certificates: summary?.certificates_count ?? vault?.certificates_count,
  };
  const expired = expiring.filter((i) => i.days_remaining < 0).length;
  const within30 = expiring.filter((i) => i.days_remaining >= 0 && i.days_remaining <= 30).length;
  const within90 = expiring.filter((i) => i.days_remaining >= 0 && i.days_remaining <= 90).length;
  const refs = references.data ?? [];
  const failingRefs = refs.filter((r) => r.status === "Failed" || r.status === "Degraded").length;
  const rbac = props?.rbac_enabled ?? vault?.rbac_enabled ?? summary?.rbac_enabled ?? false;
  const resourceId = vault?.id || "";

  const tabs: DetailTab<VaultDetailTab>[] = [
    { key: "overview", label: "Overview" },
    { key: "secrets", label: "Secrets", count: counts.secrets },
    { key: "keys", label: "Keys", count: counts.keys },
    { key: "certificates", label: "Certificates", count: counts.certificates },
    { key: "expiring", label: "Expiring", count: expired + within90, attention: expired + within30 > 0 },
    { key: "network", label: "Network", count: props ? props.private_endpoints.length + props.ip_rules.length + props.virtual_network_rules.length : undefined },
    { key: "access", label: "Access", count: props && !rbac ? props.access_policies.length : undefined },
    { key: "aks", label: "Used by AKS", count: references.data?.length, attention: failingRefs > 0 },
    { key: "activity", label: "Activity" },
    ...(data?.arm ? [{ key: "json" as const, label: "JSON" }] : []),
  ];

  const armNotice = data?.arm_error && (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      Live Azure properties are unavailable ({data.arm_error}). Showing the synced inventory record.
    </div>
  );

  const endpointColumns: GridColumn<VaultPrivateEndpoint>[] = [
    { key: "name", header: "Private Endpoint", sortValue: (p) => p.name, render: (p) => <span className="font-mono text-xs" title={p.private_endpoint_id}>{p.name}</span> },
    {
      key: "status",
      header: "Connection",
      sortValue: (p) => p.status ?? "",
      render: (p) => <Badge label={p.status || "Unknown"} color={p.status === "Approved" ? "green" : p.status === "Pending" ? "yellow" : "red"} />,
    },
    { key: "provisioning", header: "Provisioning", sortValue: (p) => p.provisioning_state ?? "", render: (p) => <span className="text-xs">{p.provisioning_state || "—"}</span> },
    { key: "description", header: "Description", render: (p) => <span className="text-xs text-slate-600">{p.description || "—"}</span> },
  ];

  const policyColumns: GridColumn<VaultAccessPolicy>[] = [
    {
      key: "object",
      header: "Object ID",
      sortValue: (p) => p.object_id ?? "",
      render: (p) => (
        <span className="flex items-center gap-2">
          <span className="whitespace-nowrap font-mono text-xs">{p.object_id || "—"}</span>
          {p.object_id && <CopyButton value={p.object_id} />}
        </span>
      ),
    },
    { key: "app", header: "Application ID", render: (p) => <Truncate value={p.application_id} className="font-mono text-xs" maxWidth="max-w-[12rem]" /> },
    { key: "secrets", header: "Secrets", sortValue: (p) => p.secrets.length, render: (p) => <PermissionChips values={p.secrets} /> },
    { key: "keys", header: "Keys", sortValue: (p) => p.keys.length, render: (p) => <PermissionChips values={p.keys} /> },
    { key: "certificates", header: "Certificates", sortValue: (p) => p.certificates.length, render: (p) => <PermissionChips values={p.certificates} /> },
    { key: "storage", header: "Storage", render: (p) => <PermissionChips values={p.storage} /> },
  ];

  return (
    <ResourceDetailShell
      kind="Azure Key Vault"
      name={vaultName}
      icon={Icons.vault("h-[22px] w-[22px]")}
      status={
        <span className="inline-flex flex-wrap items-center gap-1">
          {(props?.soft_delete_enabled ?? vault?.soft_delete_enabled ?? summary?.soft_delete) && <Badge label="Soft Delete" color="green" />}
          {(props?.purge_protection_enabled ?? vault?.purge_protection_enabled ?? summary?.purge_protection) && <Badge label="Purge Protect" color="blue" />}
          {rbac && <Badge label="RBAC" color="purple" />}
        </span>
      }
      meta={
        <>
          <span className="font-mono text-xs">{vaultUri}</span>
          {(vault?.location || summary?.location) && <span>{vault?.location || summary?.location}</span>}
          {vault?.resource_group && <span>Resource group {vault.resource_group}</span>}
        </>
      }
      actions={
        <>
          {actions}
          {resourceId && (
            <a
              href={azurePortalUrl(resourceId)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-att-200 bg-white px-3 py-1.5 text-sm font-medium text-att-700 hover:bg-att-50"
            >
              Azure portal {Icons.external()}
            </a>
          )}
        </>
      }
      tabs={tabs}
      activeTab={tab}
      onTabChange={setTab}
      isLoading={isLoading && tab === "overview"}
      error={isError && tab === "overview" ? formatAxiosError(error, "Failed to load the vault.") : null}
      onClose={onClose}
    >
      {tab === "overview" && (
        <>
          {armNotice}
          <KpiRow>
            <MetricCard
              title="Secrets"
              value={counts.secrets ?? "—"}
              icon={Icons.secret("h-5 w-5")}
              tone="green"
              onClick={() => setTab("secrets")}
              actionLabel="Show this vault's secrets"
            />
            <MetricCard title="Keys" value={counts.keys ?? "—"} icon={Icons.key("h-5 w-5")} tone="purple" onClick={() => setTab("keys")} actionLabel="Show this vault's keys" />
            <MetricCard
              title="Certificates"
              value={counts.certificates ?? "—"}
              icon={Icons.certificate("h-5 w-5")}
              tone="indigo"
              onClick={() => setTab("certificates")}
              actionLabel="Show this vault's certificates"
            />
            <MetricCard
              title="Expired / ≤30d"
              value={`${expired} / ${within30}`}
              subtitle={`${within90} expiring within 90 days`}
              icon={MetricCardIcons.alert()}
              tone={expired ? "red" : within30 ? "amber" : "slate"}
              onClick={() => setTab("expiring")}
              actionLabel="Show this vault's expired and expiring items"
            />
          </KpiRow>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <DetailCard title="Vault">
              <PropertyList
                items={[
                  {
                    label: "Vault URI",
                    wide: true,
                    value: (
                      <span className="flex items-center gap-2">
                        <span className="break-all font-mono text-xs">{vaultUri}</span>
                        <CopyButton value={vaultUri} />
                      </span>
                    ),
                  },
                  { label: "Location", value: vault?.location || summary?.location },
                  { label: "SKU", value: props?.sku || vault?.sku },
                  { label: "Subscription", value: vault?.subscription_id || summary?.subscription_id, mono: true, wide: true },
                  { label: "Resource Group", value: vault?.resource_group },
                  { label: "Provisioning State", value: props?.provisioning_state || vault?.provisioning_state },
                  { label: "Tenant", value: props?.tenant_id || vault?.tenant_id, mono: true, wide: true },
                  props?.created_at && { label: "Created", value: `${fmtDateTime(props.created_at, timezone)}${props.created_by ? ` by ${props.created_by}` : ""}`, wide: true },
                  props?.last_modified_at && {
                    label: "Last Modified",
                    value: `${fmtDateTime(props.last_modified_at, timezone)}${props.last_modified_by ? ` by ${props.last_modified_by}` : ""}`,
                    wide: true,
                  },
                  vault?.synced_at && { label: "Inventory Synced", value: fmtDateTime(vault.synced_at, timezone) },
                ]}
              />
            </DetailCard>
            <div className="space-y-5">
              <DetailCard title="Protection & Access Model">
                <PropertyList
                  items={[
                    {
                      label: "Soft Delete",
                      value: (
                        <span className="inline-flex items-center gap-2">
                          {yesNo(props?.soft_delete_enabled ?? vault?.soft_delete_enabled)}
                          {props?.soft_delete_retention_days ? <span className="text-xs text-slate-500">{props.soft_delete_retention_days}-day retention</span> : null}
                        </span>
                      ),
                    },
                    { label: "Purge Protection", value: yesNo(props?.purge_protection_enabled ?? vault?.purge_protection_enabled) },
                    {
                      label: "Permission Model",
                      value: rbac ? "Azure RBAC" : `Access policies${props ? ` (${props.access_policies.length})` : ""}`,
                    },
                    props && { label: "VM Deployment", value: yesNo(props.enabled_for_deployment) },
                    props && { label: "Disk Encryption", value: yesNo(props.enabled_for_disk_encryption) },
                    props && { label: "Template Deployment", value: yesNo(props.enabled_for_template_deployment) },
                  ]}
                />
              </DetailCard>
              {props && (
                <DetailCard
                  title="Network"
                  actions={
                    <button type="button" onClick={() => setTab("network")} className="text-xs font-medium text-blue-600 hover:underline">
                      View rules
                    </button>
                  }
                >
                  <PropertyList
                    items={[
                      { label: "Public Network Access", value: props.public_network_access || "Enabled" },
                      { label: "Default Action", value: props.network_default_action || "Allow" },
                      { label: "Trusted Services Bypass", value: props.network_bypass },
                      { label: "Private Endpoints", value: props.private_endpoints.length },
                      { label: "Firewall IP Rules", value: props.ip_rules.length },
                      { label: "VNet Rules", value: props.virtual_network_rules.length },
                    ]}
                  />
                </DetailCard>
              )}
            </div>
          </div>

          <KeyValueGrid title="Tags" entries={vault?.tags ?? {}} emptyText="No tags" />
        </>
      )}

      {tab === "secrets" && sections.secrets}
      {tab === "keys" && sections.keys}
      {tab === "certificates" && sections.certificates}
      {tab === "expiring" && sections.expiring}
      {tab === "activity" && sections.activity}

      {tab === "network" &&
        (props ? (
          <>
            <DetailCard title="Network Access">
              <PropertyList
                items={[
                  { label: "Public Network Access", value: props.public_network_access || "Enabled" },
                  {
                    label: "Default Action",
                    value: props.network_default_action === "Deny" ? "Deny — only the rules below and private endpoints can connect" : props.network_default_action || "Allow",
                  },
                  { label: "Trusted Azure Services Bypass", value: props.network_bypass },
                ]}
              />
            </DetailCard>
            <DetailGrid
              title="Private Endpoints"
              rows={props.private_endpoints}
              columns={endpointColumns}
              rowKey={(p) => p.private_endpoint_id || p.name}
              searchText={(p) => `${p.name} ${p.status} ${p.description}`}
              searchPlaceholder="Search endpoints…"
              emptyText="No private endpoints"
            />
            <DetailGrid
              title="Firewall IP Rules"
              rows={props.ip_rules.map((value) => ({ value }))}
              columns={[{ key: "value", header: "Address Range", sortValue: (r) => r.value, render: (r) => <span className="font-mono text-xs">{r.value}</span> }]}
              rowKey={(r) => r.value}
              searchText={(r) => r.value}
              searchPlaceholder="Search address…"
              emptyText="No IP rules"
            />
            <DetailGrid
              title="Virtual Network Rules"
              rows={props.virtual_network_rules.map((id) => ({ id }))}
              columns={[
                { key: "subnet", header: "VNet / Subnet", sortValue: (r) => subnetLabel(r.id), render: (r) => <span className="text-sm" title={r.id}>{subnetLabel(r.id)}</span> },
                { key: "id", header: "Subnet ID", render: (r) => <Truncate value={r.id} className="font-mono text-xs" maxWidth="max-w-[40rem]" /> },
              ]}
              rowKey={(r) => r.id}
              searchText={(r) => r.id}
              searchPlaceholder="Search subnet…"
              emptyText="No virtual network rules"
            />
          </>
        ) : (
          armNotice || <p className="text-sm text-slate-500">Loading network rules…</p>
        ))}

      {tab === "access" &&
        (props ? (
          <>
            {rbac && (
              <div className="rounded-xl border border-att-100 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm">
                This vault uses <span className="font-semibold">Azure RBAC</span>: data-plane access is granted with role assignments (for example Key Vault Secrets
                User) under Access control (IAM).
                {resourceId && (
                  <a href={azurePortalUrl(resourceId, "users")} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center gap-1 font-medium text-blue-600 hover:underline">
                    Open IAM {Icons.external()}
                  </a>
                )}
                {props.access_policies.length > 0 && (
                  <p className="mt-1 text-xs text-amber-700">The {props.access_policies.length} access policies below are ignored while RBAC is enabled.</p>
                )}
              </div>
            )}
            {(!rbac || props.access_policies.length > 0) && (
              <DetailGrid
                title="Access Policies"
                rows={props.access_policies}
                columns={policyColumns}
                rowKey={(p) => `${p.object_id}/${p.application_id ?? ""}`}
                searchText={(p) => `${p.object_id} ${p.application_id ?? ""} ${[...p.secrets, ...p.keys, ...p.certificates].join(" ")}`}
                searchPlaceholder="Search object ID or permission…"
                emptyText="No access policies"
              />
            )}
          </>
        ) : (
          armNotice || <p className="text-sm text-slate-500">Loading access configuration…</p>
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
            showObject
            onOpenObject={(r: KeyVaultAksReference) => r.object_name && onOpenItem((r.object_kind as KeyVaultItemType) || "secret", r.object_name)}
            emptyText="No AzureKeyVaultSecret in the AKS inventory reads from this vault. References come from AKS Operations → AKV Sync; sync a cluster there to refresh them."
          />
        ))}

      {tab === "json" && data?.arm && <JsonViewer value={data.arm} fileName={`${vaultName}.json`} />}
    </ResourceDetailShell>
  );
}

export default VaultDetailModal;
