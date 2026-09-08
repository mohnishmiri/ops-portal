/**
 * Certificate Management API client and React Query hooks (Keyfactor Command).
 *
 * Provides the full certificate lifecycle used by CertificatesPage:
 * list/search, view details, enroll (CSR & PFX), renew, revoke, update
 * metadata, and delete.
 *
 * All calls go through the shared apiClient (MSAL token injection + subscription
 * scope handling). Never store PFX/private-key material returned by enrollment.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

const API_BASE = "/certificates";
const LIST_STALE_TIME = 60_000;

// ── Types ─────────────────────────────────────────────────────────────

export type CertificateStatus =
  | "valid"
  | "expiring_soon"
  | "expired"
  | "revoked"
  | "unknown";

export type EnrollmentType = "csr" | "pfx";

/** RFC 5280 revocation reason codes supported by Keyfactor. */
export const REVOCATION_REASONS = [
  "unspecified",
  "keyCompromise",
  "caCompromise",
  "affiliationChanged",
  "superseded",
  "cessationOfOperation",
  "certificateHold",
  "removeFromCRL",
  "privilegeWithdrawn",
  "aaCompromise",
] as const;

export type RevocationReason = (typeof REVOCATION_REASONS)[number];

export interface Certificate {
  id: number;
  common_name: string;
  subject_dn: string;
  issuer_dn: string;
  serial_number: string;
  thumbprint: string;
  template: string;
  certificate_authority: string;
  not_before: string | null;
  not_after: string | null;
  import_date: string | null;
  effective_date: string | null;
  sans: string[];
  san_count: number;
  revoked: boolean;
  revocation_reason: number | null;
  status: CertificateStatus;
  metadata: Record<string, unknown>;
  // Enriched fields
  key_algorithm: string;
  key_size: number;
  key_usage: string;
  extended_key_usage: string;
  signing_algorithm: string;
  requester: string;
  principal_name: string;
  locations: { store_path: string; agent_pool: string; alias: string }[];
  location_count: number;
  collection: string;
  has_private_key?: boolean | null;
  /**
   * Whether the private key is held in the escrow Key Vault, so the certificate
   * can be loaded into further vaults later. Undefined when escrow is not
   * configured on the backend — distinct from `false`, which means "escrow is
   * on and this certificate has no escrowed key".
   */
  key_escrowed?: boolean | null;
}

export interface CertificateListResponse {
  items: Certificate[];
  total: number;
  page: number;
  page_size: number;
}

export interface CertificateListParams {
  cn?: string;
  thumbprint?: string;
  issuer?: string;
  cert_status?: string;
  collection_id?: number;
  expires_in_days?: number;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface EnrollRequest {
  enrollment_type: EnrollmentType;
  certificate_authority: string;
  template: string;
  include_chain?: boolean;
  sans?: Record<string, string[]>;
  metadata?: Record<string, unknown>;
  // CSR enrollment
  csr?: string;
  // PFX enrollment
  subject?: string;
  password?: string;
  key_type?: string;
  key_length?: number;
  // Subject information
  common_name?: string;
  organization?: string;
  organizational_unit?: string;
  city?: string;
  state?: string;
  country?: string;
  email?: string;
  custom_friendly_name?: string;
  // AT&T metadata
  mots_profile_id?: string;
  requester_att_user_id?: string;
  requester_att_manager_user_id?: string;
  server_type?: string;
  environment?: string;
  tls_port_services_internet_traffic?: string;
  port?: string;
  pci_data?: string;
  // Delivery
  owner_role_name?: string;
  delivery_format?: string;
  use_legacy_encryption?: boolean;
}

export interface EnrollResult {
  serial_number?: string;
  thumbprint?: string;
  certificate_id?: number;
  certificate?: string;
  certificates?: string[];
  pfx_base64?: string;
  /** True when the issuance-time PFX was captured into the escrow Key Vault. */
  key_escrowed?: boolean;
  [key: string]: unknown;
}

export interface RenewRequest {
  mode?: "one_click" | "pfx" | "csr";
  certificate_authority?: string;
  template?: string;
  collection_id?: number;
  password?: string;
  key_type?: string;
  key_length?: number;
  owner_role_name?: string;
  csr?: string;
}

export interface RevokeRequest {
  reason: RevocationReason;
  comment?: string;
  effective_date?: string;
  collection_id?: number;
}

export interface UpdateMetadataRequest {
  metadata: Record<string, unknown>;
}

// ── Query keys ────────────────────────────────────────────────────────

export const certificateKeys = {
  all: ["certificates"] as const,
  list: (params: CertificateListParams) => ["certificates", "list", params] as const,
  detail: (id: number) => ["certificates", "detail", id] as const,
};

// ── Fetchers ──────────────────────────────────────────────────────────

export const fetchCertificates = async (
  params: CertificateListParams
): Promise<CertificateListResponse> => {
  const response = await apiClient.get<CertificateListResponse>(API_BASE, { params });
  return response.data;
};

/**
 * Fetch every certificate matching the given filters by walking all pages.
 * Used for CSV export ("download all the data"), capped by ``maxRows`` so a
 * huge collection can't lock up the browser.
 */
export const fetchAllCertificatesForExport = async (
  params: CertificateListParams,
  maxRows = 10000
): Promise<Certificate[]> => {
  const pageSize = 200;
  const all: Certificate[] = [];
  let page = 1;
  let total = Infinity;
  while (all.length < Math.min(total, maxRows)) {
    const res = await fetchCertificates({ ...params, page, page_size: pageSize });
    total = res.total;
    if (res.items.length === 0) break;
    all.push(...res.items);
    if (res.items.length < pageSize) break;
    page += 1;
  }
  return all.slice(0, maxRows);
};

export const fetchCertificate = async (id: number): Promise<Certificate> => {
  const response = await apiClient.get<Certificate>(`${API_BASE}/${id}`);
  return response.data;
};

export const enrollCertificate = async (data: EnrollRequest): Promise<EnrollResult> => {
  const response = await apiClient.post<EnrollResult>(`${API_BASE}/enroll`, data);
  return response.data;
};

export const renewCertificate = async (
  id: number,
  data: RenewRequest
): Promise<EnrollResult> => {
  const response = await apiClient.post<EnrollResult>(`${API_BASE}/${id}/renew`, data);
  return response.data;
};

export const revokeCertificate = async (
  id: number,
  data: RevokeRequest
): Promise<{ certificate_id: number; reason: string; revoked: boolean }> => {
  const response = await apiClient.post(`${API_BASE}/${id}/revoke`, data);
  return response.data;
};

export const updateCertificateMetadata = async (
  id: number,
  data: UpdateMetadataRequest
): Promise<{ certificate_id: number; updated_fields: string[] }> => {
  const response = await apiClient.put(`${API_BASE}/${id}/metadata`, data);
  return response.data;
};

export const deleteCertificate = async (
  id: number,
  collectionId?: number
): Promise<{ certificate_id: number; deleted: boolean }> => {
  const params = collectionId != null ? { collection_id: collectionId } : undefined;
  const response = await apiClient.delete(`${API_BASE}/${id}`, { params });
  return response.data;
};

// ── Hooks ─────────────────────────────────────────────────────────────

export const useCertificates = (params: CertificateListParams, enabled = true) =>
  useQuery({
    queryKey: certificateKeys.list(params),
    queryFn: () => fetchCertificates(params),
    staleTime: LIST_STALE_TIME,
    enabled,
  });

/**
 * Accurate, collection-scoped certificate counts for the dashboard tiles.
 * Each field is the true collection total for a filter (from the API's
 * x-total-count header), not just the current page. ``revoked`` is ``-1`` when
 * the upstream could not resolve a collection-wide value.
 */
export interface CollectionCertStats {
  total: number;
  expired: number;
  revoked: number;
  expiring30: number;
  expiring60: number;
  expiring90: number;
}

export const fetchCollectionCertStats = async (
  collectionId: number
): Promise<CollectionCertStats> => {
  const base: CertificateListParams = { collection_id: collectionId, page: 1, page_size: 1 };
  // expires_in_days=N counts certs with ExpirationDate <= now+N (includes
  // already-expired), so subtract the expired total to get "expiring within N".
  const [all, expired, d30, d60, d90, revoked] = await Promise.all([
    fetchCertificates(base),
    fetchCertificates({ ...base, expires_in_days: 0 }),
    fetchCertificates({ ...base, expires_in_days: 30 }),
    fetchCertificates({ ...base, expires_in_days: 60 }),
    fetchCertificates({ ...base, expires_in_days: 90 }),
    fetchCertificates({ ...base, cert_status: "Revoked" }).catch(() => null),
  ]);
  const expiredCount = expired.total;
  return {
    total: all.total,
    expired: expiredCount,
    revoked: revoked ? revoked.total : -1,
    expiring30: Math.max(0, d30.total - expiredCount),
    expiring60: Math.max(0, d60.total - expiredCount),
    expiring90: Math.max(0, d90.total - expiredCount),
  };
};

export const useCollectionCertStats = (collectionId?: number) =>
  useQuery({
    queryKey: ["certificates", "collection-stats", collectionId] as const,
    queryFn: () => fetchCollectionCertStats(collectionId as number),
    enabled: collectionId != null,
    staleTime: LIST_STALE_TIME,
  });

// ── Sync (DB cache) ────────────────────────────────────────────────────

export interface CertificateSyncRun {
  id: number;
  sync_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  collections_synced: number;
  certificates_synced: number;
  error_message: string | null;
  triggered_by: string | null;
}

export interface CertificateSyncStatus {
  certificates_in_db: number;
  collections_in_db: number;
  last_completed_at?: string | null;
  is_stale?: boolean;
  recent_syncs: CertificateSyncRun[];
}

export const triggerCertificateSync = async (collectionId?: number): Promise<CertificateSyncRun> => {
  const resp = await apiClient.post<CertificateSyncRun>(`${API_BASE}/sync`, {
    collection_id: collectionId ?? null,
  });
  return resp.data;
};

export const fetchCertificateSyncStatus = async (): Promise<CertificateSyncStatus> => {
  const resp = await apiClient.get<CertificateSyncStatus>(`${API_BASE}/sync/status`);
  return resp.data;
};

export const useCertificateSyncStatus = () =>
  useQuery({
    queryKey: ["certificates", "sync-status"],
    queryFn: fetchCertificateSyncStatus,
    staleTime: 30_000,
    // Poll live while a sync is running so the badge and progress update in real time.
    refetchInterval: (query) => {
      const running = query.state.data?.recent_syncs?.[0]?.status === "running";
      return running ? 3_000 : false;
    },
  });

export const useCertificateSync = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (collectionId?: number) => triggerCertificateSync(collectionId),
    onSuccess: () => {
      // Refresh every certificate-related query (list, collections, stats, status).
      qc.invalidateQueries({ queryKey: certificateKeys.all });
    },
  });
};

export const useCertificate = (id: number | null) =>
  useQuery({
    queryKey: certificateKeys.detail(id ?? -1),
    queryFn: () => fetchCertificate(id as number),
    enabled: id != null,
  });

export const useEnrollCertificate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: enrollCertificate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: certificateKeys.all });
    },
  });
};

export const useRenewCertificate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: RenewRequest }) => renewCertificate(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: certificateKeys.all });
    },
  });
};

export const useRevokeCertificate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: RevokeRequest }) => revokeCertificate(id, data),
    onSuccess: async () => {
      // Small delay — Keyfactor eventual consistency
      await new Promise((r) => setTimeout(r, 500));
      await queryClient.invalidateQueries({ queryKey: certificateKeys.all, refetchType: "all" });
    },
  });
};

export const useUpdateCertificateMetadata = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: UpdateMetadataRequest }) =>
      updateCertificateMetadata(id, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: certificateKeys.all, refetchType: "all" });
    },
  });
};

export const useDeleteCertificate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      collectionId,
    }: {
      id: number;
      collectionId?: number;
      notAfter: string | null;
      revoked: boolean;
    }) =>
      deleteCertificate(id, collectionId),
    onMutate: ({ collectionId }) => ({
      collectionId,
      collections: queryClient.getQueryData<CertificateCollection[]>([
        "certificates",
        "collections",
      ]),
      stats:
        collectionId == null
          ? undefined
          : queryClient.getQueryData<CollectionCertStats>([
              "certificates",
              "collection-stats",
              collectionId,
            ]),
    }),
    onSuccess: async (_result, variables, context) => {
      await new Promise((r) => setTimeout(r, 500));
      await queryClient.invalidateQueries({ queryKey: certificateKeys.all, refetchType: "all" });
      if (context.collectionId != null && context.collections) {
        queryClient.setQueryData<CertificateCollection[]>(
          ["certificates", "collections"],
          context.collections.map((collection) =>
            collection.id === context.collectionId
              ? { ...collection, certificate_count: Math.max(0, collection.certificate_count - 1) }
              : collection
          )
        );
      }
      if (context.collectionId != null && context.stats) {
        const expiration = variables.notAfter ? Date.parse(variables.notAfter) : Number.NaN;
        const now = Date.now();
        const expiresWithin = (days: number) =>
          Number.isFinite(expiration) && expiration > now && expiration <= now + days * 86_400_000;
        const isExpired = Number.isFinite(expiration) && expiration <= now;
        const decrement = (value: number, applies: boolean) =>
          applies ? Math.max(0, value - 1) : value;

        queryClient.setQueryData<CollectionCertStats>(
          ["certificates", "collection-stats", context.collectionId],
          {
            ...context.stats,
            total: Math.max(0, context.stats.total - 1),
            expired: decrement(context.stats.expired, isExpired),
            revoked: decrement(context.stats.revoked, variables.revoked && context.stats.revoked >= 0),
            expiring30: decrement(context.stats.expiring30, expiresWithin(30)),
            expiring60: decrement(context.stats.expiring60, expiresWithin(60)),
            expiring90: decrement(context.stats.expiring90, expiresWithin(90)),
          }
        );
      }
    },
  });
};
// ── Audit History ─────────────────────────────────────────────────────────

export interface CertificateAuditEntry {
  id: number;
  timestamp: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
  user_id: string;
  user_email: string;
  status: string;
  summary: string;
  details: Record<string, unknown>;
}

export interface CertificateAuditResponse {
  history: CertificateAuditEntry[];
  count: number;
}

export const fetchCertificateAuditHistory = async (
  days = 90,
  limit = 200
): Promise<CertificateAuditResponse> => {
  const response = await apiClient.get<CertificateAuditResponse>(`${API_BASE}/audit-history`, {
    params: { days, limit },
  });
  return response.data;
};

export const useCertificateAuditHistory = (days = 90, limit = 200) =>
  useQuery({
    queryKey: ["certificates", "audit-history", days, limit],
    queryFn: () => fetchCertificateAuditHistory(days, limit),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
// ── Auto-Renewal Configuration ─────────────────────────────────────────

export interface AutoRenewalCertificateRef {
  id: number;
  common_name: string;
  thumbprint: string;
}

/** A Key Vault entry a renewed certificate is imported into. */
export interface AutoRenewalAkvTarget {
  subscription_id: string;
  resource_group: string;
  vault_name: string;
  certificate_names: string[];
}

export interface AutoRenewalConfig {
  id: number;
  collection_id: number;
  collection_name: string;
  enabled: boolean;
  /** False = dry run: the schedule reports what it would renew but issues nothing. */
  armed?: boolean;
  days_before_expiry: number;
  notify_on_renewal: boolean;
  notification_emails: string[];
  certificates: AutoRenewalCertificateRef[];
  certificate_count?: number;
  akv_targets?: AutoRenewalAkvTarget[];
  created_at: string | null;
  created_by: string;
  last_run_at?: string | null;
  last_run_summary?: string;
}

export interface AutoRenewalConfigRequest {
  collection_id: number;
  collection_name?: string;
  enabled?: boolean;
  /** Leave false to run as a dry run until the targets have been validated. */
  armed?: boolean;
  days_before_expiry?: number;
  notify_on_renewal?: boolean;
  notification_emails?: string[];
  certificates?: AutoRenewalCertificateRef[];
  akv_targets?: AutoRenewalAkvTarget[];
}

export const fetchAutoRenewalConfigs = async (): Promise<AutoRenewalConfig[]> => {
  const resp = await apiClient.get<AutoRenewalConfig[]>(`${API_BASE}/auto-renewal/configs`);
  return resp.data;
};

export const createAutoRenewalConfig = async (data: AutoRenewalConfigRequest): Promise<{ id: number }> => {
  const resp = await apiClient.post(`${API_BASE}/auto-renewal/configs`, data);
  return resp.data;
};

export const deleteAutoRenewalConfig = async (id: number): Promise<void> => {
  await apiClient.delete(`${API_BASE}/auto-renewal/configs/${id}`);
};

export const useAutoRenewalConfigs = () =>
  useQuery({
    queryKey: ["certificates", "auto-renewal-configs"],
    queryFn: fetchAutoRenewalConfigs,
    staleTime: 60_000,
  });

export const useCreateAutoRenewalConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createAutoRenewalConfig,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["certificates", "auto-renewal-configs"] }); },
  });
};

export const useDeleteAutoRenewalConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteAutoRenewalConfig,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["certificates", "auto-renewal-configs"] }); },
  });
};

export interface AutoRenewalRunResult {
  status: string;
  config_id: number;
  /** False = dry run: nothing was issued. */
  armed: boolean;
  certificates_due: number;
  renewed: number;
  failed: number;
  emails_sent: number;
}

export const runAutoRenewalConfig = async (id: number): Promise<AutoRenewalRunResult> => {
  const resp = await apiClient.post<AutoRenewalRunResult>(`${API_BASE}/auto-renewal/configs/${id}/run`);
  return resp.data;
};

export const useRunAutoRenewalConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runAutoRenewalConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["certificates", "auto-renewal-configs"] });
      qc.invalidateQueries({ queryKey: ["certificates", "audit-history"] });
    },
  });
};

// ── Alert Configuration ───────────────────────────────────────────────

export interface AlertConfig {
  id: number;
  collection_id: number | null;
  collection_name: string;
  enabled: boolean;
  warning_days: number;
  critical_days: number;
  notification_emails: string[];
  notify_channel: string;
  created_at: string | null;
  created_by: string;
}

export interface AlertConfigRequest {
  collection_id?: number | null;
  collection_name?: string;
  enabled?: boolean;
  warning_days?: number;
  critical_days?: number;
  notification_emails?: string[];
  notify_channel?: string;
}

export interface AlertRunResult {
  status: string;
  config_id: number;
  critical: number;
  warning: number;
  emails_sent: number;
}

export const runAlertConfig = async (id: number): Promise<AlertRunResult> => {
  const resp = await apiClient.post<AlertRunResult>(`${API_BASE}/alerts/configs/${id}/run`);
  return resp.data;
};

export const useRunAlertConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runAlertConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["certificates", "alert-configs"] });
      qc.invalidateQueries({ queryKey: ["certificates", "audit-history"] });
    },
  });
};

export const fetchAlertConfigs = async (): Promise<AlertConfig[]> => {
  const resp = await apiClient.get<AlertConfig[]>(`${API_BASE}/alerts/configs`);
  return resp.data;
};

export const createAlertConfig = async (data: AlertConfigRequest): Promise<{ id: number }> => {
  const resp = await apiClient.post(`${API_BASE}/alerts/configs`, data);
  return resp.data;
};

export const deleteAlertConfig = async (id: number): Promise<void> => {
  await apiClient.delete(`${API_BASE}/alerts/configs/${id}`);
};

export const useAlertConfigs = () =>
  useQuery({
    queryKey: ["certificates", "alert-configs"],
    queryFn: fetchAlertConfigs,
    staleTime: 60_000,
  });

export const useCreateAlertConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createAlertConfig,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["certificates", "alert-configs"] }); },
  });
};

export const useDeleteAlertConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteAlertConfig,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["certificates", "alert-configs"] }); },
  });
};
// ── Admin: Enabled Collections ────────────────────────────────────────

export interface EnabledCollectionsResponse {
  collection_ids: number[];
  mode: "all" | "selected";
}

export const fetchEnabledCollections = async (): Promise<EnabledCollectionsResponse> => {
  const resp = await apiClient.get<EnabledCollectionsResponse>(`${API_BASE}/collections/enabled`);
  return resp.data;
};

export const setEnabledCollections = async (collectionIds: number[]): Promise<void> => {
  await apiClient.put(`${API_BASE}/collections/enabled`, { collection_ids: collectionIds });
};

export const useEnabledCollections = () =>
  useQuery({
    queryKey: ["certificates", "enabled-collections"],
    queryFn: fetchEnabledCollections,
    staleTime: 60_000,
  });

export const useSetEnabledCollections = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: setEnabledCollections,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["certificates", "enabled-collections"] });
      qc.invalidateQueries({ queryKey: ["certificates", "collections"] });
    },
  });
};

/** Fetch ALL collections (unfiltered) for the admin panel. */
export const fetchAllCollections = async (): Promise<CertificateCollection[]> => {
  const response = await apiClient.get<CertificateCollection[]>(`${API_BASE}/collections`, {
    params: { include_all: "true" },
  });
  return response.data;
};

export const useAllCollections = () =>
  useQuery({
    queryKey: ["certificates", "all-collections"],
    queryFn: fetchAllCollections,
    staleTime: 5 * 60_000,
  });
// ── Helpers ───────────────────────────────────────────────────────────

export const STATUS_LABEL: Record<CertificateStatus, string> = {
  valid: "Valid",
  expiring_soon: "Expiring Soon",
  expired: "Expired",
  revoked: "Revoked",
  unknown: "Unknown",
};

/** Extract a friendly error message from an axios error shape. */
export const certificateErrorMessage = (error: unknown, fallback = "Operation failed"): string => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (error instanceof Error) return error.message;
  return fallback;
};

// ── Download ───────────────────────────────────────────────────────────────

export type DownloadFormat = "PEM" | "CER" | "CRT" | "DER" | "P7B" | "PFX" | "JKS";

/** Formats that carry the private key: keystore password + WRITE role required. */
export const KEYSTORE_FORMATS: DownloadFormat[] = ["PFX", "JKS"];
export type ChainOrder = "EndEntityFirst" | "RootFirst";

export const DOWNLOAD_FORMATS: DownloadFormat[] = ["PEM", "CER", "CRT", "DER", "P7B", "PFX", "JKS"];

export interface DownloadRequest {
  file_format: DownloadFormat;
  include_chain: boolean;
  chain_order: ChainOrder;
  include_subject_header: boolean;
  collection_id?: number;
  /** Keystore password for the PFX and JKS formats (min 12 chars). */
  pfx_password?: string;
  /** JKS entry alias; defaults to the certificate's common name. */
  jks_alias?: string;
}

export const downloadCertificate = async (id: number, data: DownloadRequest): Promise<Blob> => {
  const response = await apiClient.post(`${API_BASE}/${id}/download`, data, {
    responseType: "blob",
  });
  return response.data as Blob;
};

export const useDownloadCertificate = () => {
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: DownloadRequest }) =>
      downloadCertificate(id, data),
  });
};

// ── Collections / Templates / CAs ───────────────────────────────────────

export interface CertificateCollection {
  id: number;
  name: string;
  description: string;
  certificate_count: number;
}

export interface CertificateTemplate {
  id: number;
  common_name: string;
  template_name: string;
  oid: string;
  key_size: string;
  key_type: string;
}

export interface CertificateAuthority {
  id: number;
  name: string;
  host_name: string;
}

export const fetchCollections = async (): Promise<CertificateCollection[]> => {
  const response = await apiClient.get<CertificateCollection[]>(`${API_BASE}/collections`);
  return response.data;
};

export const fetchTemplates = async (): Promise<CertificateTemplate[]> => {
  const response = await apiClient.get<CertificateTemplate[]>(`${API_BASE}/templates`);
  return response.data;
};

export const fetchAuthorities = async (): Promise<CertificateAuthority[]> => {
  const response = await apiClient.get<CertificateAuthority[]>(`${API_BASE}/authorities`);
  return response.data;
};

export const useCollections = () =>
  useQuery({
    queryKey: ["certificates", "collections"],
    queryFn: fetchCollections,
    staleTime: 5 * 60_000,
  });

export const useTemplates = () =>
  useQuery({
    queryKey: ["certificates", "templates"],
    queryFn: fetchTemplates,
    staleTime: 5 * 60_000,
  });

export const useAuthorities = () =>
  useQuery({
    queryKey: ["certificates", "authorities"],
    queryFn: fetchAuthorities,
    staleTime: 5 * 60_000,
  });

// ── Load Certificate to Azure Key Vault ───────────────────────────────

export interface AkvUploadRequest {
  subscription_id: string;
  resource_group: string;
  vault_name: string;
  /** One entry per AKV name holding this certificate (multi-SAN certs use several). */
  certificate_names: string[];
  /** Omit to have the backend source the private key (escrow, then Keyfactor). */
  certificate_data?: string;
  certificate_password?: string;
  collection_id?: number;
  /** "auto" prefers the escrowed key; "escrow" fails instead of falling back. */
  key_source?: AkvKeySource;
}

export type AkvKeySource = "auto" | "escrow" | "keyfactor";

export interface AkvUploadedCertificate {
  certificate_name: string;
  akv_id: string;
  enabled: boolean;
}

export interface AkvUploadResult {
  status: string;
  vault_name: string;
  certificates: AkvUploadedCertificate[];
  failed: { certificate_name: string; error: string }[];
  /** Which key source the backend actually used. */
  key_source?: "provided" | "escrow" | "keyfactor";
}

export const loadCertificateToAkv = async (
  certificateId: number,
  data: AkvUploadRequest
): Promise<AkvUploadResult> => {
  const response = await apiClient.post<AkvUploadResult>(
    `${API_BASE}/${certificateId}/load-to-akv`,
    data
  );
  return response.data;
};

export const useLoadCertificateToAkv = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AkvUploadRequest }) =>
      loadCertificateToAkv(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["certificates", "audit-history"] });
    },
  });
};
