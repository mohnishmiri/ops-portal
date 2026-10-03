/**
 * Expanded view of one pod volume: where each container mounts it, the volume
 * source as declared in the pod spec, and — for ConfigMap, Secret, and PVC
 * sources — the object behind it, including the file each key becomes.
 */

import React, { useState } from "react";
import { Spinner } from "../../components/gridStyles";
import { PodVolume, PodVolumeClaim, useConfigMapDetail, useSecretDetail } from "../../services/aksApi";
import { apiErrorDetail, KeyValue, SectionTitle } from "./detailShared";

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
  if (files.length > 0) return <span className="font-mono text-[11px] text-gray-600 break-all">{files.join(", ")}</span>;
  return <span className="text-[11px] text-gray-400">{items ? "not projected (not listed in items)" : "not mounted as a file"}</span>;
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

  if (isLoading) return <Loading text={`Loading ConfigMap ${name}…`} />;
  if (isError) return <p className="text-sm text-red-600">{apiErrorDetail(error, `ConfigMap ${name} could not be loaded.`)}</p>;
  if (data?.detail_source === "unavailable") {
    return <p className="text-sm text-amber-700">ConfigMap content is unavailable from the live cluster.{data.data_unavailable_reason ? ` ${data.data_unavailable_reason}` : ""}</p>;
  }
  const entries = Object.entries(data?.data ?? {});
  return (
    <div>
      <SectionTitle>ConfigMap {name} — {entries.length} key{entries.length === 1 ? "" : "s"}</SectionTitle>
      {entries.length === 0 ? (
        <p className="text-sm text-gray-400">No data keys</p>
      ) : (
        <div className="divide-y divide-att-100 rounded-lg border border-att-100 bg-white">
          {entries.map(([key, value]) => (
            <div key={key}>
              <button
                type="button"
                onClick={() => setOpen(open === key ? null : key)}
                aria-expanded={open === key}
                className="flex w-full items-start justify-between gap-3 px-3 py-1.5 text-left hover:bg-att-50"
              >
                <span className="font-mono text-xs text-blue-700 break-all">{key}</span>
                <span className="flex shrink-0 flex-col items-end gap-0.5 text-right">
                  <KeyFiles keyName={key} items={items} mounts={mounts} />
                  <span className="text-[11px] text-gray-400">{sizeLabel(value)}</span>
                </span>
              </button>
              {open === key && (
                <pre className="mx-3 mb-2 max-h-[300px] overflow-auto whitespace-pre-wrap rounded bg-gray-900 p-3 font-mono text-xs text-green-300">{value}</pre>
              )}
            </div>
          ))}
        </div>
      )}
      {(data?.binary_data_keys?.length ?? 0) > 0 && (
        <p className="mt-1 text-xs text-gray-500">Binary keys: {data!.binary_data_keys.join(", ")}</p>
      )}
    </div>
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

  if (isLoading) return <Loading text={`Loading Secret ${name}…`} />;
  if (isError) return <p className="text-sm text-red-600">{apiErrorDetail(error, `Secret ${name} could not be loaded.`)}</p>;
  const keys = data?.keys ?? [];
  return (
    <div>
      <SectionTitle>Secret {name}{data?.type ? ` (${data.type})` : ""} — {keys.length} key{keys.length === 1 ? "" : "s"}</SectionTitle>
      <p className="mb-1 text-xs text-gray-500">Values are hidden here. Users with permission can reveal them from the Secrets tab, which is audited.</p>
      {keys.length === 0 ? (
        <p className="text-sm text-gray-400">No data keys</p>
      ) : (
        <ul className="divide-y divide-att-100 rounded-lg border border-att-100 bg-white">
          {keys.map((key) => (
            <li key={key} className="flex items-start justify-between gap-3 px-3 py-1.5">
              <span className="font-mono text-xs text-gray-800 break-all">{key}</span>
              <KeyFiles keyName={key} items={items} mounts={mounts} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ClaimInfo({ name, claim, formatDate }: { name: string | null; claim?: PodVolumeClaim | null; formatDate: (v: string) => string }) {
  if (!claim) {
    return <p className="text-sm text-amber-700">PersistentVolumeClaim {name ?? ""} could not be read — it may have been deleted.</p>;
  }
  return (
    <div>
      <SectionTitle>PersistentVolumeClaim {claim.name}</SectionTitle>
      <KeyValue label="Phase" value={claim.phase} />
      <KeyValue label="Capacity / requested" value={`${claim.capacity ?? "—"} / ${claim.requested ?? "—"}`} />
      <KeyValue label="Access modes" value={claim.access_modes.join(", ") || "—"} />
      <KeyValue label="Storage class" value={claim.storage_class} />
      <KeyValue label="Bound volume" value={claim.volume_name} />
      <KeyValue label="Volume mode" value={claim.volume_mode ?? "Filesystem"} />
      <KeyValue label="Created" value={claim.created_at ? formatDate(claim.created_at) : "—"} />
    </div>
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
    <div className="space-y-1 text-sm">
      <SectionTitle>Mounted at</SectionTitle>
      {mounts.length === 0 ? (
        <p className="text-sm text-gray-400">Not mounted by any container</p>
      ) : (
        <ul className="space-y-0.5">
          {mounts.map((m) => (
            <li key={`${m.container}:${m.mount_path}`} className="text-xs text-gray-700">
              <span className="font-medium">{m.container}</span> → <span className="font-mono">{m.mount_path}</span>
              <span className={m.read_only ? "ml-2 text-orange-600" : "ml-2 text-gray-500"}>{m.read_only ? "read-only" : "read-write"}</span>
              {m.sub_path && <span className="ml-2 text-gray-500">subPath <span className="font-mono">{m.sub_path}</span></span>}
            </li>
          ))}
        </ul>
      )}

      <SectionTitle>{volume.type} source</SectionTitle>
      {specRows.length === 0 ? (
        <p className="text-sm text-gray-400">No additional settings</p>
      ) : (
        specRows.map(([key, value]) => (
          <KeyValue key={key} label={key} value={<span className="font-mono text-xs">{value}</span>} />
        ))
      )}

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
