/**
 * Expanded view of one pod volume: where each container mounts it, the volume
 * source as declared in the pod spec, and — for ConfigMap, Secret, and PVC
 * sources — the object behind it, including the file each key becomes.
 */

import React, { useMemo, useState } from "react";
import { Spinner } from "../../components/gridStyles";
import { PodVolume, PodVolumeClaim, useConfigMapDetail, useSecretDetail } from "../../services/aksApi";
import { DetailGrid } from "./DetailGrid";
import { apiErrorDetail, DetailIcons } from "./detailShared";
import { DetailCard, PropertyList } from "./ResourceDetailShell";

export interface VolumeMountRef {
  container: string;
  mount_path: string;
  read_only: boolean;
  sub_path: string | null;
}

type KeyToPath = { key: string; path: string };

/** Nested spec → ["volumeAttributes.shareName", "logs"] rows. */
export function flattenSpec(value: unknown, prefix = ""): [string, string][] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) return value.flatMap((v, i) => flattenSpec(v, `${prefix}[${i}]`));
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => flattenSpec(v, prefix ? `${prefix}.${k}` : k));
  }
  // Kubernetes stores file modes in decimal (420); show the familiar octal alongside.
  if (/(^|\.)(defaultMode|mode)$/.test(prefix) && typeof value === "number") {
    return [[prefix, `0${value.toString(8)} (${value})`]];
  }
  return [[prefix, String(value)]];
}

/** Where a ConfigMap/Secret key appears inside each container that mounts the volume. */
export function projectedFilePaths(key: string, items: KeyToPath[] | undefined, mounts: VolumeMountRef[]): string[] {
  const relative = items ? items.find((i) => i.key === key)?.path : key;
  if (!relative) return [];
  return mounts.flatMap((m) => {
    if (m.sub_path) return m.sub_path === relative ? [`${m.container}:${m.mount_path}`] : [];
    return [`${m.container}:${m.mount_path.replace(/\/+$/, "")}/${relative}`];
  });
}

function sizeLabel(value: string): string {
  return value.length > 1024 ? `${(value.length / 1024).toFixed(1)} KB` : `${value.length} chars`;
}

function Loading({ text }: { text: string }) {
  return <div className="flex items-center gap-2 py-2 text-xs text-gray-500"><Spinner className="h-3 w-3" />{text}</div>;
}

function KeyFiles({ keyName, items, mounts }: { keyName: string; items?: KeyToPath[]; mounts: VolumeMountRef[] }) {
  const files = projectedFilePaths(keyName, items, mounts);
  if (files.length > 0) return <span className="block max-w-[28rem] break-all font-mono text-xs text-slate-600">{files.join(", ")}</span>;
  return <span className="text-xs text-slate-400">{items ? "not projected (not listed in items)" : "not mounted as a file"}</span>;
}

function ConfigMapKeys({
  clusterId,
  namespace,
  name,
  items,
  mounts,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  items?: KeyToPath[];
  mounts: VolumeMountRef[];
}) {
  const { data, isLoading, isError, error } = useConfigMapDetail(clusterId, namespace, name);
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => Object.entries(data?.data ?? {}).map(([key, value]) => ({ key, value })), [data]);

  if (isLoading) return <Loading text={`Loading ConfigMap ${name}…`} />;
  if (isError) return <p className="text-sm text-red-600">{apiErrorDetail(error, `ConfigMap ${name} could not be loaded.`)}</p>;
  if (data?.detail_source === "unavailable") {
    return <p className="text-sm text-amber-700">ConfigMap content is unavailable from the live cluster.{data.data_unavailable_reason ? ` ${data.data_unavailable_reason}` : ""}</p>;
  }
  return (
    <>
      <DetailGrid
        title={`ConfigMap ${name}`}
        rows={rows}
        columns={[
          {
            key: "key",
            header: "Key",
            sortValue: (r) => r.key,
            render: (r) => (
              <button type="button" aria-expanded={open === r.key} className="inline-flex items-center gap-1.5 whitespace-nowrap text-left font-mono text-xs text-blue-700 hover:underline">
                <span className={`transition-transform ${open === r.key ? "rotate-90" : ""}`}>{DetailIcons.chevron}</span>
                {r.key}
              </button>
            ),
          },
          { key: "file", header: "File in Container", render: (r) => <KeyFiles keyName={r.key} items={items} mounts={mounts} /> },
          { key: "size", header: "Size", align: "right", sortValue: (r) => r.value.length, render: (r) => <span className="whitespace-nowrap text-xs text-slate-500">{sizeLabel(r.value)}</span> },
        ]}
        rowKey={(r) => r.key}
        searchText={(r) => `${r.key} ${r.value}`}
        searchPlaceholder="Search keys or values…"
        emptyText="No data keys"
        initialSort={{ key: "key", direction: "asc" }}
        expandedKey={open}
        onRowClick={(r) => setOpen(open === r.key ? null : r.key)}
        renderExpanded={(r) => (
          <pre className="max-h-[300px] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono text-xs text-green-300">{r.value}</pre>
        )}
      />
      {(data?.binary_data_keys?.length ?? 0) > 0 && (
        <p className="text-xs text-slate-500">Binary keys: {data!.binary_data_keys.join(", ")}</p>
      )}
    </>
  );
}

function SecretKeys({
  clusterId,
  namespace,
  name,
  items,
  mounts,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  items?: KeyToPath[];
  mounts: VolumeMountRef[];
}) {
  // Never reveals values: the API returns key names and masked data unless reveal is requested.
  const { data, isLoading, isError, error } = useSecretDetail(clusterId, namespace, name, false, true);
  const rows = useMemo(() => (data?.keys ?? []).map((key) => ({ key })), [data]);

  if (isLoading) return <Loading text={`Loading Secret ${name}…`} />;
  if (isError) return <p className="text-sm text-red-600">{apiErrorDetail(error, `Secret ${name} could not be loaded.`)}</p>;
  return (
    <>
      <p className="text-xs text-slate-500">
        {data?.type ? `Type ${data.type}. ` : ""}Values are hidden here. Users with permission can reveal them from the Secrets tab, which is audited.
      </p>
      <DetailGrid
        title={`Secret ${name}`}
        rows={rows}
        columns={[
          { key: "key", header: "Key", sortValue: (r) => r.key, render: (r) => <span className="whitespace-nowrap font-mono text-xs text-slate-800">{r.key}</span> },
          { key: "file", header: "File in Container", render: (r) => <KeyFiles keyName={r.key} items={items} mounts={mounts} /> },
        ]}
        rowKey={(r) => r.key}
        searchText={(r) => r.key}
        searchPlaceholder="Search keys…"
        emptyText="No data keys"
        initialSort={{ key: "key", direction: "asc" }}
      />
    </>
  );
}

function ClaimInfo({ name, claim, formatDate }: { name: string | null; claim?: PodVolumeClaim | null; formatDate: (v: string) => string }) {
  if (!claim) {
    return <p className="text-sm text-amber-700">PersistentVolumeClaim {name ?? ""} could not be read — it may have been deleted.</p>;
  }
  return (
    <DetailCard title={`PersistentVolumeClaim ${claim.name}`}>
      <PropertyList
        items={[
          { label: "Phase", value: claim.phase },
          { label: "Capacity / Requested", value: `${claim.capacity ?? "—"} / ${claim.requested ?? "—"}` },
          { label: "Access Modes", value: claim.access_modes.join(", ") },
          { label: "Storage Class", value: claim.storage_class },
          { label: "Bound Volume", value: claim.volume_name, mono: true },
          { label: "Volume Mode", value: claim.volume_mode ?? "Filesystem" },
          { label: "Created", value: claim.created_at ? formatDate(claim.created_at) : null },
        ]}
      />
    </DetailCard>
  );
}

export function PodVolumeDetail({
  clusterId,
  namespace,
  volume,
  mounts,
  formatDate,
}: {
  clusterId: string;
  namespace: string;
  volume: PodVolume;
  mounts: VolumeMountRef[];
  formatDate: (v: string) => string;
}) {
  const spec = volume.spec ?? {};
  const items = Array.isArray(spec.items) ? (spec.items as KeyToPath[]) : undefined;
  const specRows = flattenSpec(spec);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DetailCard title="Mounted At">
          {mounts.length === 0 ? (
            <p className="text-sm text-slate-400">Not mounted by any container</p>
          ) : (
            <ul className="space-y-2">
              {mounts.map((m) => (
                <li key={`${m.container}:${m.mount_path}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-700">
                  <span className="font-medium">{m.container}</span>
                  <span className="text-slate-400">→</span>
                  <span className="font-mono">{m.mount_path}</span>
                  <span className={`rounded px-1.5 py-0.5 ${m.read_only ? "bg-orange-50 text-orange-700" : "bg-slate-100 text-slate-600"}`}>
                    {m.read_only ? "read-only" : "read-write"}
                  </span>
                  {m.sub_path && <span className="text-slate-500">subPath <span className="font-mono">{m.sub_path}</span></span>}
                </li>
              ))}
            </ul>
          )}
        </DetailCard>
        <DetailCard title={`${volume.type} Source`}>
          {specRows.length === 0 ? (
            <p className="text-sm text-slate-400">No additional settings</p>
          ) : (
            <PropertyList items={specRows.map(([key, value]) => ({ label: key, value, mono: true }))} />
          )}
        </DetailCard>
      </div>

      {volume.type === "ConfigMap" && volume.source && (
        <ConfigMapKeys clusterId={clusterId} namespace={namespace} name={volume.source} items={items} mounts={mounts} />
      )}
      {volume.type === "Secret" && volume.source && (
        <SecretKeys clusterId={clusterId} namespace={namespace} name={volume.source} items={items} mounts={mounts} />
      )}
      {volume.type === "PersistentVolumeClaim" && (
        <ClaimInfo name={volume.source} claim={volume.claim} formatDate={formatDate} />
      )}
    </div>
  );
}

export default PodVolumeDetail;
