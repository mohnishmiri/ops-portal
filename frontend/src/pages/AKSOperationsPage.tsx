/**
 * AKS Operations Page — Cluster inventory, deployment management, pod observability, CronJob management.
 * 
 * Module 2: AKS Operations & Control Center
 * - Multi-cluster inventory with health status
 * - Deployment scaling and restart controls
 * - Real-time pod CPU/memory metrics
 * - CronJob suspend/resume management
 */

import React, { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../contexts/AuthContext";
import Toast, { type ToastState } from "../components/Toast";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import { AutoRefreshIndicator, gridStyles, SortState, nextSortState, SortableHeader } from "../components/gridStyles";
import {
  useClusters,
  useCachedClusters,
  useCachedDeployments,
  useCachedPodMetrics,

  useNodePools,
  useCachedNodePools,
  useScaleDeployment,
  useRestartDeployment,
  useCreateDeployment,
  useUpdateDeployment,
  useDeleteDeployment,
  useSuspendCronJob,
  useCreateCronJob,
  useUpdateCronJob,
  useDeleteCronJob,
  useTriggerCronJob,
  useCronJobDetail,
  useConfigMapDetail,
  useCachedCronJobs,
  useScaleNodePool,
  useUpdateAutoscaling,
  useStartCluster,
  useStopCluster,
  useScaleHistory,
  useAksNamespaces,
  useAksBackgroundSync,
  refreshClusters,
  usePodLogs,
  usePodLogSearch,
  useExecPodCommand,
  usePodContainers,
  AKSCluster,
  Deployment,
  PodMetrics,
  CronJob,
  CronJobDetail,
  ConfigMapDetail,
  NodePoolDetails,
  NodeDetail,
  PodLogSearchResult,
} from "../services/aksApi";
import {
  SecretsTab,
  ServicesTab,
  ConfigMapsTab,
  IngressTab,
  HelmTab,
  AuditHistoryTab,
} from "../features/aks/AKSExtendedTabs";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  RadialBarChart,
  RadialBar,
} from "recharts";

// ── SVG Icons ─────────────────────────────────────────────────────────

const Icons = {
  cluster: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <circle cx="12" cy="12" r="3" /><circle cx="12" cy="4" r="2" /><circle cx="20" cy="12" r="2" /><circle cx="12" cy="20" r="2" /><circle cx="4" cy="12" r="2" />
      <line x1="12" y1="6" x2="12" y2="9" /><line x1="18" y1="12" x2="15" y2="12" /><line x1="12" y1="18" x2="12" y2="15" /><line x1="6" y1="12" x2="9" y2="12" />
    </svg>
  ),
  deployment: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  ),
  pod: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="4" y="4" width="16" height="16" rx="2" ry="2" /><line x1="9" y1="4" x2="9" y2="20" /><line x1="15" y1="4" x2="15" y2="20" />
    </svg>
  ),
  cronjob: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
    </svg>
  ),
  scale: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  ),
  restart: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  ),
  play: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  pause: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
    </svg>
  ),
  cpu: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="4" y="4" width="16" height="16" rx="2" ry="2" /><rect x="9" y="9" width="6" height="6" />
      <line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" /><line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" />
      <line x1="20" y1="9" x2="23" y2="9" /><line x1="20" y1="14" x2="23" y2="14" /><line x1="1" y1="9" x2="4" y2="9" /><line x1="1" y1="14" x2="4" y2="14" />
    </svg>
  ),
  memory: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M6 19v-3" /><path d="M10 19v-3" /><path d="M14 19v-3" /><path d="M18 19v-3" /><path d="M8 11V9" /><path d="M16 11V9" /><path d="M12 11V9" />
      <path d="M2 15h20" /><path d="M2 7h20" /><rect x="2" y="3" width="20" height="18" rx="2" ry="2" />
    </svg>
  ),
  refresh: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  ),
  check: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  warning: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  history: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
    </svg>
  ),
};

// ── Tab Types ─────────────────────────────────────────────────────────

type TabKey =
  | "clusters" | "nodepools" | "deployments" | "pods"
  | "services" | "secrets" | "configmaps" | "ingress" | "helm"
  | "cronjobs" | "history" | "audit";

// ── Color Constants ───────────────────────────────────────────────────

const COLORS = {
  primary: "#3f9bca",
  primaryDark: "#2d7aa8",
  primaryLight: "#6bb8d8",
  success: "#10b981",
  warning: "#f59e0b",
  danger: "#ef4444",
  neutral: "#6b7280",
};

const PIE_COLORS = ["#3f9bca", "#2d7aa8", "#10b981", "#f59e0b", "#ef4444", "#6b7280"];

// ── Reusable Helpers ──────────────────────────────────────────────────

const PAGE_SIZE = 15;

type AksBackgroundSyncState = ReturnType<typeof useAksBackgroundSync>;

function BackgroundRefreshStatus({ sync }: { sync: AksBackgroundSyncState }) {
  if (sync.isRetrying) {
    return <span className="text-sm text-amber-600">Refresh delayed, retrying...</span>;
  }
  if (sync.isRunning) {
    return <span className="text-sm text-blue-600">Refreshing in background...</span>;
  }
  if (sync.error) {
    return <span className="text-sm text-red-600">Last refresh failed. Cached data is still shown.</span>;
  }
  if (sync.status === "completed") {
    return <span className="text-sm text-green-600">Background refresh complete.</span>;
  }
  return null;
}

function useSearchPagination<T>(items: T[], searchFn: (item: T, q: string) => boolean) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter((item) => searchFn(item, q));
  }, [items, search, searchFn]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safeP = Math.min(page, totalPages);
  const paged = filtered.slice((safeP - 1) * PAGE_SIZE, safeP * PAGE_SIZE);

  return { search, setSearch, page: safeP, setPage, paged, filtered, totalPages };
}



/** Search toolbar — sits at the top of the grid shell */
function GridSearchBar({
  search, onSearch, onPage, totalItems, shownItems, placeholder,
}: {
  search: string; onSearch: (v: string) => void;
  onPage: (p: number) => void; totalItems: number; shownItems: number; placeholder?: string;
}) {
  return (
    <div className={gridStyles.panelHeader}>
      <div className="flex items-center gap-3">
        <span className={gridStyles.countBadge}>{shownItems} of {totalItems}</span>
        <AutoRefreshIndicator />
      </div>
      <input
        type="text"
        value={search}
        onChange={(e) => { onSearch(e.target.value); onPage(1); }}
        placeholder={placeholder || "Search..."}
        className={gridStyles.toolbarInput}
      />
    </div>
  );
}

/** Pagination footer — sits at the bottom of the grid shell */
function GridPager({
  page, totalPages, onPage,
}: {
  page: number; totalPages: number; onPage: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className={gridStyles.pager}>
      <span className="text-gray-600">Showing page {page} of {totalPages}</span>
      <div className="flex items-center gap-2">
        <button disabled={page <= 1} onClick={() => onPage(page - 1)} className={gridStyles.pagerButton}>Previous</button>
        <span className="text-gray-600">Page {page} of {totalPages}</span>
        <button disabled={page >= totalPages} onClick={() => onPage(page + 1)} className={gridStyles.pagerButton}>Next</button>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────

const AKSOperationsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const { formatDate } = usePortalTimezone();
  const { canWrite } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("clusters");
  const [selectedCluster, setSelectedCluster] = useState<AKSCluster | null>(null);
  const [selectedNamespace, setSelectedNamespace] = useState<string>("");
  const [scaleDialog, setScaleDialog] = useState<{ deployment: Deployment; replicas: number } | null>(null);
  const [nodePoolScaleDialog, setNodePoolScaleDialog] = useState<{
    pool: NodePoolDetails;
    nodeCount: number;
  } | null>(null);
  const [autoscaleDialog, setAutoscaleDialog] = useState<{
    pool: NodePoolDetails;
    enable: boolean;
    minCount: number;
    maxCount: number;
  } | null>(null);

  // CronJob CRUD dialogs
  const [createCronJobDialog, setCreateCronJobDialog] = useState(false);
  const [editCronJobDialog, setEditCronJobDialog] = useState<CronJob | null>(null);
  const [viewCronJobDialog, setViewCronJobDialog] = useState<{ cluster_id: string; namespace: string; name: string } | null>(null);
  const [deleteCronJobConfirm, setDeleteCronJobConfirm] = useState<CronJob | null>(null);

  // Deployment CRUD dialogs
  const [createDeploymentDialog, setCreateDeploymentDialog] = useState(false);
  const [editDeploymentDialog, setEditDeploymentDialog] = useState<Deployment | null>(null);
  const [deleteDeploymentConfirm, setDeleteDeploymentConfirm] = useState<Deployment | null>(null);

  // Create Deployment form state
  const [depForm, setDepForm] = useState({
    name: "", namespace: "default", image: "", replicas: 1, port: "",
    cpu_request: "100m", cpu_limit: "500m", memory_request: "128Mi", memory_limit: "512Mi",
  });
  // Edit Deployment form state
  const [editDepForm, setEditDepForm] = useState({
    image: "", replicas: 1, cpu_request: "", cpu_limit: "", memory_request: "", memory_limit: "",
  });

  // Create CronJob form state (expanded)
  const [cjForm, setCjForm] = useState({
    name: "", namespace: "default", schedule: "*/5 * * * *", image: "", command: "", args: "",
    cpu_request: "100m", cpu_limit: "500m", memory_request: "128Mi", memory_limit: "256Mi",
    concurrency_policy: "Forbid", restart_policy: "OnFailure",
    successful_jobs_history_limit: 3, failed_jobs_history_limit: 1,
    backoff_limit: 6, active_deadline_seconds: "", ttl_seconds_after_finished: "",
    service_account_name: "",
  });
  // Edit CronJob form state
  const [editCjForm, setEditCjForm] = useState({ schedule: "", image: "", suspended: false });

  // Pod detail dialogs (Logs, Exec, Metrics)
  const [podLogDialog, setPodLogDialog] = useState<PodMetrics | null>(null);
  const [podExecDialog, setPodExecDialog] = useState<PodMetrics | null>(null);
  const [podMetricsDialog, setPodMetricsDialog] = useState<PodMetrics | null>(null);
  const [podLogTailLines, setPodLogTailLines] = useState(500);
  const [podLogSinceSeconds, setPodLogSinceSeconds] = useState<number | undefined>(undefined);
  const [podLogContainer, setPodLogContainer] = useState("");
  const [podLogAutoRefresh, setPodLogAutoRefresh] = useState(false);
  const [podLogSearchPattern, setPodLogSearchPattern] = useState("error|exception|fail|panic|crash|oom|kill");
  const [podLogSearchActive, setPodLogSearchActive] = useState(false);
  const [execCommand, setExecCommand] = useState("");
  const [execContainer, setExecContainer] = useState("");
  const [execHistory, setExecHistory] = useState<Array<{ command: string; output: string; success: boolean }>>([]);

  // Refs for auto-scroll
  const logEndRef = useRef<HTMLDivElement>(null);
  const execEndRef = useRef<HTMLDivElement>(null);

  // Toast notification
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: "success" | "error" = "success") => setToast({ message, type }), []);

  // Generic confirmation dialog (replaces window.confirm)
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string;
    message: string;
    confirmLabel?: string;
    variant?: "danger" | "warning" | "info";
    onConfirm: () => void;
  } | null>(null);

  // Node pool expanded rows (by pool name)
  const [expandedPools, setExpandedPools] = useState<Set<string>>(new Set());
  const togglePoolExpand = useCallback((poolName: string) => {
    setExpandedPools(prev => {
      const next = new Set(prev);
      if (next.has(poolName)) next.delete(poolName); else next.add(poolName);
      return next;
    });
  }, []);

  // Load only the data needed for the active tab — avoids parallel K8s/Azure storms.
  const clusterScopedTabs = new Set<TabKey>([
    "nodepools", "deployments", "pods", "cronjobs",
    "services", "secrets", "configmaps", "ingress", "helm",
  ]);
  const needsNamespaces = !!selectedCluster && clusterScopedTabs.has(activeTab);
  const loadDeployments = !!selectedCluster && activeTab === "deployments";
  const loadPodMetrics = !!selectedCluster && activeTab === "pods";
  const loadCronJobs = !!selectedCluster && activeTab === "cronjobs";
  const loadNodePools = !!selectedCluster && activeTab === "nodepools";
  const loadScaleHistory = activeTab === "history";

  // Queries — use DB-cached clusters for fast load
  const {
    data: clustersData,
    isLoading: loadingClusters,
    isFetching: fetchingClusters,
    refetch: refetchClusters,
  } = useCachedClusters();
  const { data: deploymentsData, isLoading: loadingDeployments, isError: deploymentsError, error: deploymentsErr } = useCachedDeployments(
    selectedCluster?.id || "",
    selectedNamespace || undefined,
    loadDeployments
  );
  const { data: podMetricsData, isLoading: loadingPodMetrics, isError: podMetricsError, error: podMetricsErr } = useCachedPodMetrics(
    selectedCluster?.id || "",
    selectedNamespace || undefined,
    loadPodMetrics
  );

  const { data: cronJobsData, isLoading: loadingCronJobs, isError: cronJobsError, error: cronJobsErr } = useCachedCronJobs(
    selectedCluster?.id || "",
    selectedNamespace || undefined,
    loadCronJobs
  );
  const { data: scaleHistoryData } = useScaleHistory(
    loadScaleHistory ? selectedCluster?.id : undefined,
    undefined,
    undefined,
    30,
    loadScaleHistory
  );
  const { data: nodePoolsData, isLoading: loadingNodePools, isError: nodePoolsError, error: nodePoolsErr } = useCachedNodePools(
    selectedCluster?.id || "",
    loadNodePools
  );
  const { data: namespacesData } = useAksNamespaces(selectedCluster?.id, needsNamespaces);

  const namespaceOptions = useMemo(() => {
    return [...(namespacesData?.namespaces || [])].sort();
  }, [namespacesData]);

  const clustersRefresh = useAksBackgroundSync({
    resourceType: "clusters",
    enabled: activeTab === "clusters",
  });
  const deploymentsRefresh = useAksBackgroundSync({
    resourceType: "deployments",
    clusterId: selectedCluster?.id,
    namespace: selectedNamespace || undefined,
    enabled: loadDeployments,
  });
  const podMetricsRefresh = useAksBackgroundSync({
    resourceType: "pods",
    clusterId: selectedCluster?.id,
    namespace: selectedNamespace || undefined,
    enabled: loadPodMetrics,
  });
  const cronJobsRefresh = useAksBackgroundSync({
    resourceType: "cronjobs",
    clusterId: selectedCluster?.id,
    namespace: selectedNamespace || undefined,
    enabled: loadCronJobs,
  });
  const nodePoolsRefresh = useAksBackgroundSync({
    resourceType: "nodepools",
    clusterId: selectedCluster?.id,
    enabled: loadNodePools,
  });

  // Mutations
  const scaleDeploymentMutation = useScaleDeployment();
  const restartDeploymentMutation = useRestartDeployment();
  const createDeploymentMutation = useCreateDeployment();
  const updateDeploymentMutation = useUpdateDeployment();
  const deleteDeploymentMutation = useDeleteDeployment();
  const suspendCronJobMutation = useSuspendCronJob();
  const createCronJobMutation = useCreateCronJob();
  const updateCronJobMutation = useUpdateCronJob();
  const deleteCronJobMutation = useDeleteCronJob();
  const triggerCronJobMutation = useTriggerCronJob();
  const scaleNodePoolMutation = useScaleNodePool();
  const updateAutoscalingMutation = useUpdateAutoscaling();
  const startClusterMutation = useStartCluster();
  const stopClusterMutation = useStopCluster();

  // Pod detail hooks — only enabled when dialog open
  const { data: podLogsData, isLoading: loadingPodLogs, refetch: refetchPodLogs } = usePodLogs(
    selectedCluster?.id || "", podLogDialog?.namespace || "", podLogDialog?.pod_name || "",
    podLogContainer || undefined, podLogTailLines, podLogSinceSeconds,
    !!podLogDialog && !podLogSearchActive
  );
  const { data: podLogSearchData, isLoading: loadingPodLogSearch } = usePodLogSearch(
    selectedCluster?.id || "", podLogDialog?.namespace || "", podLogDialog?.pod_name || "",
    podLogSearchPattern, podLogContainer || undefined, !!podLogDialog && podLogSearchActive
  );
  const execPodMutation = useExecPodCommand();
  const { data: podContainersData } = usePodContainers(
    selectedCluster?.id || "",
    (podLogDialog || podExecDialog)?.namespace || "",
    (podLogDialog || podExecDialog)?.pod_name || "",
    !!(podLogDialog || podExecDialog)
  );

  // Auto-refresh logs every 5s
  useEffect(() => {
    if (!podLogAutoRefresh || !podLogDialog || podLogSearchActive) return;
    const interval = setInterval(() => refetchPodLogs(), 5000);
    return () => clearInterval(interval);
  }, [podLogAutoRefresh, podLogDialog, podLogSearchActive, refetchPodLogs]);

  // Auto-scroll log viewer
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [podLogsData, podLogSearchData]);

  // Auto-scroll exec output
  useEffect(() => {
    execEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [execHistory]);

  // Reset container selection when dialog opens
  useEffect(() => {
    if (podLogDialog) { setPodLogContainer(""); setPodLogSearchActive(false); }
  }, [podLogDialog]);
  useEffect(() => {
    if (podExecDialog) { setExecContainer(""); setExecHistory([]); setExecCommand(""); }
  }, [podExecDialog]);

  // Get unique namespaces from deployments
  const namespaces = useMemo(() => {
    if (!deploymentsData?.deployments) return [];
    return [...new Set(deploymentsData.deployments.map((d) => d.namespace))].sort();
  }, [deploymentsData]);

  // Get unique namespaces from pods — cache when unfiltered so dropdown stays populated
  const [cachedPodNamespaces, setCachedPodNamespaces] = useState<string[]>([]);
  useEffect(() => {
    if (!selectedNamespace && podMetricsData?.pods && podMetricsData.pods.length > 0) {
      setCachedPodNamespaces(
        [...new Set(podMetricsData.pods.map((p) => p.namespace))].sort()
      );
    }
  }, [podMetricsData, selectedNamespace]);
  const podNamespaces = useMemo(() => {
    if (!podMetricsData?.pods) return cachedPodNamespaces;
    const currentNs = [...new Set(podMetricsData.pods.map((p) => p.namespace))];
    return [...new Set([...cachedPodNamespaces, ...currentNs])].sort();
  }, [podMetricsData, cachedPodNamespaces]);

  // Handle cluster selection
  const handleClusterSelect = (cluster: AKSCluster) => {
    setSelectedCluster(cluster);
    setSelectedNamespace("");
  };

  // Navigate from Deployment → Pod Metrics tab (pre-filtered)
  const handleViewDeploymentPods = (deployment: Deployment) => {
    setSelectedNamespace(deployment.namespace);
    podsPag.setSearch(deployment.name);
    setActiveTab("pods");
  };

  // Handle exec command in pod
  const handleExecCommand = async () => {
    if (!execCommand.trim() || !podExecDialog || !selectedCluster) return;
    const cmd = execCommand.trim();
    setExecCommand("");
    try {
      const res = await execPodMutation.mutateAsync({
        clusterId: selectedCluster.id,
        namespace: podExecDialog.namespace,
        podName: podExecDialog.pod_name,
        command: cmd,
        container: execContainer || undefined,
      });
      setExecHistory((h) => [...h, { command: cmd, output: res.output, success: res.success }]);
    } catch (e: any) {
      setExecHistory((h) => [...h, { command: cmd, output: e?.message || "Command failed", success: false }]);
    }
  };

  // Handle scale deployment
  const handleScale = async () => {
    if (!scaleDialog || !selectedCluster) return;
    const { deployment, replicas } = scaleDialog;
    const prevReplicas = deployment.replicas;
    const action = replicas >= prevReplicas ? "scale_up" : "scale_down";
    const activityId = addMutationActivity({
      deploymentName: deployment.name,
      namespace: deployment.namespace,
      action,
      targetReplicas: replicas,
      previousReplicas: prevReplicas,
      startedAt: Date.now(),
      status: "pending",
    });
    setScaleDialog(null);
    try {
      await scaleDeploymentMutation.mutateAsync({
        clusterId: selectedCluster.id,
        namespace: deployment.namespace,
        deploymentName: deployment.name,
        replicas,
      });
      updateMutationActivity(activityId, { status: "scaling", message: `0/${replicas} pods ready` });
    } catch (e: any) {
      updateMutationActivity(activityId, { status: "failed", message: e?.response?.data?.detail || "Scale failed" });
      showToast(e?.response?.data?.detail || "Scale failed", "error");
    }
  };

  // Handle restart deployment
  const handleRestart = (deployment: Deployment) => {
    if (!selectedCluster) return;
    setConfirmDialog({
      title: "Restart Deployment",
      message: `Are you sure you want to restart deployment "${deployment.name}" in namespace "${deployment.namespace}"?`,
      confirmLabel: "Restart",
      variant: "warning",
      onConfirm: async () => {
        try {
          await restartDeploymentMutation.mutateAsync({
            clusterId: selectedCluster.id,
            namespace: deployment.namespace,
            deploymentName: deployment.name,
          });
          showToast(`Restarting ${deployment.name}`);
        } catch (e: any) {
          showToast(e?.response?.data?.detail || "Restart failed", "error");
        }
      },
    });
  };

  // Handle CronJob suspend/resume
  const handleCronJobToggle = (cronjob: CronJob) => {
    if (!selectedCluster) return;
    const action = cronjob.suspended ? "Resume" : "Suspend";
    setConfirmDialog({
      title: `${action} CronJob`,
      message: `Are you sure you want to ${action.toLowerCase()} cronjob "${cronjob.name}" in namespace "${cronjob.namespace}"?`,
      confirmLabel: action,
      variant: cronjob.suspended ? "info" : "warning",
      onConfirm: async () => {
        try {
          await suspendCronJobMutation.mutateAsync({
            clusterId: selectedCluster.id,
            namespace: cronjob.namespace,
            cronjobName: cronjob.name,
            suspend: !cronjob.suspended,
          });
          showToast(`${action}d ${cronjob.name}`);
        } catch (e: any) {
          showToast(e?.response?.data?.detail || `${action} failed`, "error");
        }
      },
    });
  };

  // Handle trigger CronJob (run now)
  const handleTriggerCronJob = (cronjob: CronJob) => {
    if (!selectedCluster) return;
    setConfirmDialog({
      title: "Run CronJob Now",
      message: `This will create a Job from cronjob "${cronjob.name}" in namespace "${cronjob.namespace}" and execute it immediately. Continue?`,
      confirmLabel: "Run Now",
      variant: "info",
      onConfirm: async () => {
        try {
          const result = await triggerCronJobMutation.mutateAsync({
            clusterId: selectedCluster.id,
            namespace: cronjob.namespace,
            cronjobName: cronjob.name,
          });
          showToast(`Triggered ${cronjob.name} → Job: ${result.job_name}`);
        } catch (e: any) {
          showToast(e?.response?.data?.detail || "Trigger failed", "error");
        }
      },
    });
  };

  // Handle Create CronJob
  const handleCreateCronJob = async () => {
    if (!selectedCluster) return;
    try {
      await createCronJobMutation.mutateAsync({
        cluster_id: selectedCluster.id,
        namespace: cjForm.namespace,
        name: cjForm.name,
        schedule: cjForm.schedule,
        image: cjForm.image,
        command: cjForm.command ? cjForm.command.split(" ") : undefined,
        args: cjForm.args ? cjForm.args.split(" ") : undefined,
        restart_policy: cjForm.restart_policy,
        cpu_request: cjForm.cpu_request,
        cpu_limit: cjForm.cpu_limit,
        memory_request: cjForm.memory_request,
        memory_limit: cjForm.memory_limit,
        concurrency_policy: cjForm.concurrency_policy,
        successful_jobs_history_limit: cjForm.successful_jobs_history_limit,
        failed_jobs_history_limit: cjForm.failed_jobs_history_limit,
        backoff_limit: cjForm.backoff_limit,
        active_deadline_seconds: cjForm.active_deadline_seconds ? parseInt(cjForm.active_deadline_seconds) : undefined,
        ttl_seconds_after_finished: cjForm.ttl_seconds_after_finished ? parseInt(cjForm.ttl_seconds_after_finished) : undefined,
        service_account_name: cjForm.service_account_name || undefined,
      });
      showToast(`Created cronjob ${cjForm.name}`);
      setCreateCronJobDialog(false);
      setCjForm({
        name: "", namespace: "default", schedule: "*/5 * * * *", image: "", command: "", args: "",
        cpu_request: "100m", cpu_limit: "500m", memory_request: "128Mi", memory_limit: "256Mi",
        concurrency_policy: "Forbid", restart_policy: "OnFailure",
        successful_jobs_history_limit: 3, failed_jobs_history_limit: 1,
        backoff_limit: 6, active_deadline_seconds: "", ttl_seconds_after_finished: "",
        service_account_name: "",
      });
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Create failed", "error");
    }
  };

  // Handle Update CronJob
  const handleUpdateCronJob = async () => {
    if (!selectedCluster || !editCronJobDialog) return;
    try {
      await updateCronJobMutation.mutateAsync({
        cluster_id: selectedCluster.id,
        namespace: editCronJobDialog.namespace,
        name: editCronJobDialog.name,
        schedule: editCjForm.schedule || undefined,
        image: editCjForm.image || undefined,
        suspended: editCjForm.suspended,
      });
      showToast(`Updated cronjob ${editCronJobDialog.name}`);
      setEditCronJobDialog(null);
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Update failed", "error");
    }
  };

  // Handle Delete CronJob
  const handleDeleteCronJob = async () => {
    if (!selectedCluster || !deleteCronJobConfirm) return;
    try {
      await deleteCronJobMutation.mutateAsync({
        clusterId: selectedCluster.id,
        namespace: deleteCronJobConfirm.namespace,
        name: deleteCronJobConfirm.name,
      });
      showToast(`Deleted cronjob ${deleteCronJobConfirm.name}`);
      setDeleteCronJobConfirm(null);
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Delete failed", "error");
    }
  };

  // Handle Create Deployment
  const handleCreateDeployment = async () => {
    if (!selectedCluster) return;
    try {
      await createDeploymentMutation.mutateAsync({
        cluster_id: selectedCluster.id,
        namespace: depForm.namespace,
        name: depForm.name,
        image: depForm.image,
        replicas: depForm.replicas,
        cpu_request: depForm.cpu_request,
        cpu_limit: depForm.cpu_limit,
        memory_request: depForm.memory_request,
        memory_limit: depForm.memory_limit,
        port: depForm.port ? parseInt(depForm.port) : undefined,
      });
      showToast(`Created deployment ${depForm.name}`);
      setCreateDeploymentDialog(false);
      setDepForm({ name: "", namespace: "default", image: "", replicas: 1, port: "", cpu_request: "100m", cpu_limit: "500m", memory_request: "128Mi", memory_limit: "512Mi" });
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Create failed", "error");
    }
  };

  // Handle Update Deployment
  const handleUpdateDeployment = async () => {
    if (!selectedCluster || !editDeploymentDialog) return;
    try {
      await updateDeploymentMutation.mutateAsync({
        cluster_id: selectedCluster.id,
        namespace: editDeploymentDialog.namespace,
        name: editDeploymentDialog.name,
        image: editDepForm.image || undefined,
        replicas: editDepForm.replicas,
        cpu_request: editDepForm.cpu_request || undefined,
        cpu_limit: editDepForm.cpu_limit || undefined,
        memory_request: editDepForm.memory_request || undefined,
        memory_limit: editDepForm.memory_limit || undefined,
      });
      showToast(`Updated deployment ${editDeploymentDialog.name}`);
      setEditDeploymentDialog(null);
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Update failed", "error");
    }
  };

  // Handle Delete Deployment
  const handleDeleteDeployment = async () => {
    if (!selectedCluster || !deleteDeploymentConfirm) return;
    const deploymentName = deleteDeploymentConfirm.name;
    const namespace = deleteDeploymentConfirm.namespace;
    const activityId = addMutationActivity({
      deploymentName,
      namespace,
      action: "delete",
      startedAt: Date.now(),
      status: "pending",
      message: "Deleting…",
    });
    setDeleteDeploymentConfirm(null);
    try {
      await deleteDeploymentMutation.mutateAsync({
        clusterId: selectedCluster.id,
        namespace,
        name: deploymentName,
      });
      updateMutationActivity(activityId, { status: "deleted", message: "Deployment deleted" });
      showToast(`Deleted deployment ${deploymentName}`);
    } catch (e: any) {
      updateMutationActivity(activityId, { status: "failed", message: e?.response?.data?.detail || "Delete failed" });
      showToast(e?.response?.data?.detail || "Delete failed", "error");
    }
  };

  // Handle Node Pool Scale
  const handleNodePoolScale = async () => {
    if (!nodePoolScaleDialog || !selectedCluster) return;
    try {
      await scaleNodePoolMutation.mutateAsync({
        clusterId: selectedCluster.id,
        nodepoolName: nodePoolScaleDialog.pool.name,
        nodeCount: nodePoolScaleDialog.nodeCount,
      });
      showToast(`Scaled node pool ${nodePoolScaleDialog.pool.name} to ${nodePoolScaleDialog.nodeCount} nodes`);
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Node pool scale failed", "error");
    }
    setNodePoolScaleDialog(null);
  };

  // Handle Autoscaling Update
  const handleAutoscalingUpdate = async () => {
    if (!autoscaleDialog || !selectedCluster) return;
    try {
      await updateAutoscalingMutation.mutateAsync({
        clusterId: selectedCluster.id,
        nodepoolName: autoscaleDialog.pool.name,
        enableAutoScaling: autoscaleDialog.enable,
        minCount: autoscaleDialog.enable ? autoscaleDialog.minCount : undefined,
        maxCount: autoscaleDialog.enable ? autoscaleDialog.maxCount : undefined,
      });
      showToast(`Autoscaling ${autoscaleDialog.enable ? "enabled" : "disabled"} for ${autoscaleDialog.pool.name}`);
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Autoscaling update failed", "error");
    }
    setAutoscaleDialog(null);
  };

  // Handle Cluster Start
  const handleStartCluster = async (cluster: AKSCluster) => {
    try {
      await startClusterMutation.mutateAsync({ clusterId: cluster.id });
      showToast(`Starting cluster "${cluster.name}"`);
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "Start cluster failed", "error");
    }
  };

  // Handle Cluster Stop
  const handleStopCluster = (cluster: AKSCluster) => {
    setConfirmDialog({
      title: "Stop Cluster",
      message: `Are you sure you want to stop cluster "${cluster.name}"? All workloads will be deallocated.`,
      confirmLabel: "Stop Cluster",
      variant: "danger",
      onConfirm: async () => {
        try {
          await stopClusterMutation.mutateAsync({ clusterId: cluster.id });
          showToast(`Stopping cluster "${cluster.name}"`);
        } catch (e: any) {
          showToast(e?.response?.data?.detail || "Stop cluster failed", "error");
        }
      },
    });
  };

  // ── Search / Pagination hooks (must be at top level) ─────────────────
  const allClusters = clustersData?.clusters || [];
  const searchClustersFn = useCallback((c: AKSCluster, q: string) =>
    c.name.toLowerCase().includes(q) || c.location.toLowerCase().includes(q) || (c.environment || "").toLowerCase().includes(q) || c.kubernetes_version.includes(q), []);
  const clustersPag = useSearchPagination(allClusters, searchClustersFn);
  const filteredClusterInventory = clustersPag.filtered;

  const clusterOverview = useMemo(() => {
    const runningClusters = filteredClusterInventory.filter((cluster) => cluster.power_state === "Running");
    const succeededClusters = filteredClusterInventory.filter((cluster) => cluster.provisioning_state === "Succeeded");
    const totalNodes = filteredClusterInventory.reduce((sum, cluster) => sum + (cluster.node_count || 0), 0);

    const locationCounts = filteredClusterInventory.reduce((acc, cluster) => {
      acc[cluster.location] = (acc[cluster.location] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

    const environmentCounts = filteredClusterInventory.reduce((acc, cluster) => {
      const key = cluster.environment || "unassigned";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

    const statusCounts = filteredClusterInventory.reduce((acc, cluster) => {
      const key = cluster.provisioning_state || "Unknown";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

    const locationData = Object.entries(locationCounts)
      .map(([location, count]) => ({ location, count }))
      .sort((left, right) => right.count - left.count);

    const environmentData = Object.entries(environmentCounts)
      .map(([name, value]) => ({ name: name.toUpperCase(), value }))
      .sort((left, right) => right.value - left.value);

    const statusData = Object.entries(statusCounts)
      .map(([name, value]) => ({ name, value }))
      .sort((left, right) => right.value - left.value);

    const nodeFootprintData = [...filteredClusterInventory]
      .sort((left, right) => (right.node_count || 0) - (left.node_count || 0))
      .slice(0, 6)
      .map((cluster) => ({
        name: cluster.name.replace(/^attcc-/, ""),
        nodes: cluster.node_count || 0,
      }));

    return {
      totalClusters: filteredClusterInventory.length,
      runningClusters: runningClusters.length,
      succeededClusters: succeededClusters.length,
      totalNodes,
      locations: Object.keys(locationCounts).length,
      dominantLocation: locationData[0],
      locationData,
      environmentData,
      statusData,
      nodeFootprintData,
    };
  }, [filteredClusterInventory]);

  const allDeps = deploymentsData?.deployments || [];
  const searchDepsFn = useCallback((d: Deployment, q: string) =>
    d.name.toLowerCase().includes(q) || d.namespace.toLowerCase().includes(q) || d.images.some(i => i.toLowerCase().includes(q)), []);
  const depsPag = useSearchPagination(allDeps, searchDepsFn);

  const allPods = podMetricsData?.pods || [];
  const searchPodsFn = useCallback((p: PodMetrics, q: string) =>
    p.pod_name.toLowerCase().includes(q) || p.namespace.toLowerCase().includes(q), []);
  const podsPag = useSearchPagination(allPods, searchPodsFn);

  const allCJs = cronJobsData?.cronjobs || [];
  const searchCJsFn = useCallback((c: CronJob, q: string) =>
    c.name.toLowerCase().includes(q) || c.namespace.toLowerCase().includes(q) || c.schedule.includes(q), []);
  const cjsPag = useSearchPagination(allCJs, searchCJsFn);

  const allPools = nodePoolsData?.node_pools || [];
  const searchPoolsFn = useCallback((p: NodePoolDetails, q: string) =>
    p.name.toLowerCase().includes(q) || p.vm_size.toLowerCase().includes(q) || p.mode.toLowerCase().includes(q) || (p.node_image_version || "").toLowerCase().includes(q), []);
  const poolsPag = useSearchPagination(allPools, searchPoolsFn);

  const allHistory = scaleHistoryData?.history || [];
  const searchHistoryFn = useCallback((h: typeof allHistory[0], q: string) =>
    h.cluster_name.toLowerCase().includes(q) || h.deployment_name.toLowerCase().includes(q) || h.namespace.toLowerCase().includes(q) || h.user_email.toLowerCase().includes(q), []);
  const historyPag = useSearchPagination(allHistory, searchHistoryFn);

  // ── Sorting state (per grid) ────────────────────────────────────────
  type DepSortKey = "name" | "namespace" | "image" | "replicas" | "status";
  type PodSortKey = "pod_name" | "namespace" | "phase" | "node" | "cpu" | "memory" | "restarts";
  type CJSortKey = "name" | "namespace" | "schedule" | "suspended" | "last_schedule_time";
  type NPSortKey = "name" | "mode" | "vm_size" | "count" | "total_pods" | "provisioning_state";
  type HistSortKey = "timestamp" | "cluster_name" | "deployment_name" | "action" | "user_email";

  const [depSort, setDepSort] = useState<SortState<DepSortKey>>({ key: "name", direction: "asc" });
  const [podSort, setPodSort] = useState<SortState<PodSortKey>>({ key: "pod_name", direction: "asc" });
  const [cjSort, setCjSort] = useState<SortState<CJSortKey>>({ key: "name", direction: "asc" });
  const [npSort, setNpSort] = useState<SortState<NPSortKey>>({ key: "name", direction: "asc" });
  const [histSort, setHistSort] = useState<SortState<HistSortKey>>({ key: "timestamp", direction: "desc" });

  // Generic sort helper
  const sortItems = useCallback(<T,>(items: T[], key: string, direction: "asc" | "desc", accessor?: (item: T, key: string) => string | number): T[] => {
    return [...items].sort((a, b) => {
      const av = accessor ? accessor(a, key) : (a as Record<string, unknown>)[key];
      const bv = accessor ? accessor(b, key) : (b as Record<string, unknown>)[key];
      const dir = direction === "asc" ? 1 : -1;
      if (av == null && bv == null) return 0;
      if (av == null) return dir;
      if (bv == null) return -dir;
      return av < bv ? -dir : av > bv ? dir : 0;
    });
  }, []);

  const depAccessor = useCallback((d: Deployment, key: string): string | number => {
    switch (key) {
      case "name": return d.name.toLowerCase();
      case "namespace": return d.namespace.toLowerCase();
      case "image": return (d.images[0] || "").toLowerCase();
      case "replicas": return d.replicas;
      case "status": return d.ready_replicas === d.replicas ? 0 : 1;
      default: return "";
    }
  }, []);
  const sortedDeps = useMemo(() => sortItems(depsPag.filtered, depSort.key, depSort.direction, depAccessor), [depsPag.filtered, depSort, depAccessor, sortItems]);
  const pagedSortedDeps = useMemo(() => sortedDeps.slice((depsPag.page - 1) * PAGE_SIZE, depsPag.page * PAGE_SIZE), [sortedDeps, depsPag.page]);

  const podAccessor = useCallback((p: PodMetrics, key: string): string | number => {
    switch (key) {
      case "pod_name": return p.pod_name.toLowerCase();
      case "namespace": return p.namespace.toLowerCase();
      case "phase": return (p.phase || "").toLowerCase();
      case "node": return (p.node || "").toLowerCase();
      case "cpu": return p.total_cpu_millicores;
      case "memory": return p.total_memory_mb;
      case "restarts": return p.total_restarts || 0;
      default: return "";
    }
  }, []);
  const sortedPods = useMemo(() => sortItems(podsPag.filtered, podSort.key, podSort.direction, podAccessor), [podsPag.filtered, podSort, podAccessor, sortItems]);
  const pagedSortedPods = useMemo(() => sortedPods.slice((podsPag.page - 1) * PAGE_SIZE, podsPag.page * PAGE_SIZE), [sortedPods, podsPag.page]);

  const cjAccessor = useCallback((c: CronJob, key: string): string | number => {
    switch (key) {
      case "name": return c.name.toLowerCase();
      case "namespace": return c.namespace.toLowerCase();
      case "schedule": return c.schedule;
      case "suspended": return c.suspended ? 1 : 0;
      case "last_schedule_time": return c.last_schedule_time || "";
      default: return "";
    }
  }, []);
  const sortedCJs = useMemo(() => sortItems(cjsPag.filtered, cjSort.key, cjSort.direction, cjAccessor), [cjsPag.filtered, cjSort, cjAccessor, sortItems]);
  const pagedSortedCJs = useMemo(() => sortedCJs.slice((cjsPag.page - 1) * PAGE_SIZE, cjsPag.page * PAGE_SIZE), [sortedCJs, cjsPag.page]);

  const npAccessor = useCallback((p: NodePoolDetails, key: string): string | number => {
    switch (key) {
      case "name": return p.name.toLowerCase();
      case "mode": return p.mode.toLowerCase();
      case "vm_size": return p.vm_size.toLowerCase();
      case "count": return p.count;
      case "total_pods": return p.total_pods || 0;
      case "provisioning_state": return p.provisioning_state.toLowerCase();
      default: return "";
    }
  }, []);
  const sortedPools = useMemo(() => sortItems(poolsPag.filtered, npSort.key, npSort.direction, npAccessor), [poolsPag.filtered, npSort, npAccessor, sortItems]);
  const pagedSortedPools = useMemo(() => sortedPools.slice((poolsPag.page - 1) * PAGE_SIZE, poolsPag.page * PAGE_SIZE), [sortedPools, poolsPag.page]);

  const histAccessor = useCallback((h: typeof allHistory[0], key: string): string | number => {
    switch (key) {
      case "timestamp": return h.timestamp;
      case "cluster_name": return h.cluster_name.toLowerCase();
      case "deployment_name": return h.deployment_name.toLowerCase();
      case "action": return (h.action || "scale").toLowerCase();
      case "user_email": return h.user_email.toLowerCase();
      default: return "";
    }
  }, []);
  const sortedHistory = useMemo(() => sortItems(historyPag.filtered, histSort.key, histSort.direction, histAccessor), [historyPag.filtered, histSort, histAccessor, sortItems]);
  const pagedSortedHistory = useMemo(() => sortedHistory.slice((historyPag.page - 1) * PAGE_SIZE, historyPag.page * PAGE_SIZE), [sortedHistory, historyPag.page]);

  // Multi-deployment mutation status tracker
  type MutationActivity = {
    id: string;
    deploymentName: string;
    namespace: string;
    action: "scale_up" | "scale_down" | "delete";
    targetReplicas?: number;
    previousReplicas?: number;
    startedAt: number;
    status: "pending" | "scaling" | "ready" | "deleted" | "failed";
    message?: string;
  };
  const [mutationActivities, setMutationActivities] = useState<MutationActivity[]>([]);

  const addMutationActivity = useCallback((activity: Omit<MutationActivity, "id">) => {
    const id = `${activity.namespace}/${activity.deploymentName}/${Date.now()}`;
    setMutationActivities((prev) => [{ ...activity, id }, ...prev.slice(0, 9)]);
    return id;
  }, []);

  const updateMutationActivity = useCallback((id: string, update: Partial<MutationActivity>) => {
    setMutationActivities((prev) => prev.map((a) => (a.id === id ? { ...a, ...update } : a)));
  }, []);

  const dismissMutationActivity = useCallback((id: string) => {
    setMutationActivities((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // Poll deployment status for each active scaling activity
  useEffect(() => {
    const active = mutationActivities.filter((a) => a.status === "pending" || a.status === "scaling");
    if (!active.length || !selectedCluster) return;

    const pollInterval = setInterval(() => {
      setMutationActivities((prev) =>
        prev.map((activity) => {
          if (activity.status !== "pending" && activity.status !== "scaling") return activity;
          if (activity.action === "delete") return activity;

          const dep = allDeps.find(
            (d) => d.name === activity.deploymentName && d.namespace === activity.namespace
          );
          if (!dep) return { ...activity, status: "scaling" as const };

          if (dep.ready_replicas === activity.targetReplicas) {
            return { ...activity, status: "ready" as const, message: `All ${dep.ready_replicas} pod(s) ready` };
          }
          // Timeout after 5 minutes
          if (Date.now() - activity.startedAt > 5 * 60 * 1000) {
            return { ...activity, status: "failed" as const, message: "Timeout — still waiting for pods" };
          }
          return { ...activity, status: "scaling" as const, message: `${dep.ready_replicas ?? 0}/${activity.targetReplicas} pods ready` };
        })
      );
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [mutationActivities, allDeps, selectedCluster]);

  // ── Render Tabs ─────────────────────────────────────────────────────

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: "clusters", label: "Clusters", icon: Icons.cluster() },
    { key: "nodepools", label: "Node Pools", icon: Icons.scale() },
    { key: "deployments", label: "Deployments", icon: Icons.deployment() },
    { key: "pods", label: "Pod Metrics", icon: Icons.pod() },
    { key: "services", label: "Services", icon: Icons.deployment() },
    { key: "secrets", label: "Secrets", icon: Icons.warning() },
    { key: "configmaps", label: "ConfigMaps", icon: Icons.memory() },
    { key: "ingress", label: "Ingress", icon: Icons.cluster() },
    { key: "helm", label: "Helm", icon: Icons.scale() },
    { key: "cronjobs", label: "CronJobs", icon: Icons.cronjob() },
    { key: "history", label: "Scale History", icon: Icons.history() },
    { key: "audit", label: "Audit History", icon: Icons.history() },
  ];

  // ── Render Clusters Tab ─────────────────────────────────────────────

  const renderClustersTab = () => {
    const { search: cSearch, setSearch: setCSearch, page: cPage, setPage: setCPage, paged: pagedClusters, filtered: filteredClusters, totalPages: cTotalPages } = clustersPag;
    const hasClusters = allClusters.length > 0;
    const isAzureSource = clustersData?.source === "azure";
    const sourceLabel = isAzureSource ? "Azure Live" : "Database Cache";

    return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <h2 className="text-xl font-semibold text-gray-800">AKS Cluster Inventory</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetchClusters()}
            disabled={fetchingClusters}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            {Icons.refresh(fetchingClusters ? "w-4 h-4 animate-spin" : "w-4 h-4")} {fetchingClusters ? "Refreshing..." : "Refresh"}
          </button>
          {canWrite && (
          <button
            onClick={() => clustersRefresh.start(true)}
            disabled={clustersRefresh.isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
          >
            {Icons.refresh(clustersRefresh.isRunning ? "w-4 h-4 animate-spin" : "w-4 h-4")}
            {clustersRefresh.isRunning ? "Syncing..." : "Sync from Azure"}
          </button>
          )}
        </div>
      </div>

      {/* Source & Last Sync Info */}
      <div className="flex items-center gap-3">
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${
          isAzureSource ? "bg-green-100 text-green-700" : "bg-blue-100 text-blue-700"
        }`}>
          Source: {sourceLabel}
        </span>
        {clustersData?.last_sync && (
          <span className="text-sm text-gray-500">
            Last synced: {formatDate(clustersData.last_sync)}
          </span>
        )}
        {!clustersData?.last_sync && (
          <span className="text-sm text-amber-600">
            No saved sync yet. Use Sync from Azure to populate the cache.
          </span>
        )}
        <BackgroundRefreshStatus sync={clustersRefresh} />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Clusters in View"
          value={clusterOverview.totalClusters}
          subtitle={`${clusterOverview.locations} location${clusterOverview.locations === 1 ? "" : "s"} represented`}
          icon={MetricCardIcons.layers()}
          tone="att"
        />
        <MetricCard
          title="Running Clusters"
          value={clusterOverview.runningClusters}
          subtitle={`${clusterOverview.succeededClusters} successfully provisioned`}
          icon={MetricCardIcons.checkCircle()}
          tone="green"
        />
        <MetricCard
          title="Total Nodes"
          value={clusterOverview.totalNodes}
          subtitle="Combined worker footprint across filtered inventory"
          icon={MetricCardIcons.server()}
          tone="blue"
        />
        <MetricCard
          title="Primary Region"
          value={clusterOverview.dominantLocation?.location ?? "N/A"}
          subtitle={clusterOverview.dominantLocation ? `${clusterOverview.dominantLocation.count} cluster${clusterOverview.dominantLocation.count === 1 ? "" : "s"}` : "No clusters available"}
          icon={MetricCardIcons.globe()}
          tone="indigo"
        />
      </div>

      <GridSearchBar search={cSearch} onSearch={setCSearch} onPage={setCPage} totalItems={allClusters.length} shownItems={filteredClusters.length} placeholder="Search clusters..." />

      {loadingClusters && !clustersData ? (
        <div className="text-center py-8 text-gray-500">Loading clusters...</div>
      ) : !hasClusters ? (
        <div className="rounded-2xl border border-amber-100 bg-amber-50/70 p-6 text-sm text-amber-800">
          No AKS clusters are available in the local inventory cache yet. The page is ready; run <span className="font-semibold">Sync from Azure</span> to refresh inventory without blocking navigation.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {pagedClusters.map((cluster) => (
            <div
              key={cluster.id}
              onClick={() => handleClusterSelect(cluster)}
              className={`cursor-pointer transition-all ${selectedCluster?.id === cluster.id ? "scale-[1.01]" : "hover:-translate-y-0.5"}`}
            >
              <MetricCard
                title={cluster.name}
                value={cluster.node_count}
                subtitle={
                  <div className="space-y-1 text-xs text-slate-500">
                    <div>Location: {cluster.location}</div>
                    <div>K8s Version: {cluster.kubernetes_version}</div>
                    {cluster.environment ? <div>Environment: {cluster.environment}</div> : null}
                    <div>
                      Power:{" "}
                      <span className={`font-semibold ${cluster.power_state === "Running" ? "text-emerald-600" : "text-red-600"}`}>
                        {cluster.power_state || "Unknown"}
                      </span>
                    </div>
                  </div>
                }
                meta={
                  <span
                    className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                      cluster.provisioning_state === "Succeeded"
                        ? "bg-emerald-100 text-emerald-700"
                        : cluster.provisioning_state === "Failed"
                          ? "bg-red-100 text-red-700"
                          : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {cluster.provisioning_state}
                  </span>
                }
                icon={MetricCardIcons.cloud()}
                tone={cluster.power_state === "Running" ? "blue" : cluster.provisioning_state === "Succeeded" ? "green" : "amber"}
                className={selectedCluster?.id === cluster.id ? "ring-2 ring-att-300 border-att-300 shadow-lg shadow-att-100/60" : "border-slate-200 hover:border-att-200 hover:shadow-md"}
                valueClassName="text-3xl"
              />
              <div className="mt-3 flex gap-2 border-t border-slate-100 pt-3">
                {canWrite && cluster.power_state === "Stopped" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleStartCluster(cluster); }}
                    disabled={startClusterMutation.isPending}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium bg-green-50 text-green-700 rounded-lg hover:bg-green-100 disabled:opacity-50"
                    title="Start Cluster"
                  >
                    {Icons.play("w-3 h-3")} Start
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <GridPager page={cPage} totalPages={cTotalPages} onPage={setCPage} />

      {clustersData?.clusters && clustersData.clusters.length > 0 && (
        <div className="mt-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Cluster Insights</h3>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="rounded-2xl border border-att-100 bg-white p-5 shadow-sm shadow-att-100/40 xl:col-span-2">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h4 className="font-semibold text-slate-800">Node Footprint by Cluster</h4>
                  <p className="text-sm text-slate-500">Largest worker pools across the filtered AKS inventory</p>
                </div>
                <span className="rounded-full bg-att-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-att-700">
                  Top {clusterOverview.nodeFootprintData.length}
                </span>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={clusterOverview.nodeFootprintData} layout="vertical" margin={{ top: 8, right: 24, left: 8, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#d9ebf5" />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(value: number) => [`${value} nodes`, "Nodes"]} />
                  <Bar dataKey="nodes" fill={COLORS.primary} radius={[0, 8, 8, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded-2xl border border-att-100 bg-white p-5 shadow-sm shadow-att-100/40">
              <h4 className="font-semibold text-slate-800">Provisioning Health</h4>
              <p className="mb-4 text-sm text-slate-500">Current Azure provisioning state across visible clusters</p>
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    data={clusterOverview.statusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={58}
                    outerRadius={88}
                    dataKey="value"
                    label={({ name, value }) => `${name}: ${value}`}
                  >
                    {clusterOverview.statusData.map((_, index) => (
                      <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => [value, "Clusters"]} />
                  <Legend verticalAlign="bottom" height={36} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded-2xl border border-att-100 bg-white p-5 shadow-sm shadow-att-100/40">
              <h4 className="font-semibold text-slate-800">By Location</h4>
              <p className="mb-4 text-sm text-slate-500">Regional distribution of filtered clusters</p>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={clusterOverview.locationData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#d9ebf5" />
                  <XAxis dataKey="location" tick={{ fontSize: 12 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(value: number) => [value, "Clusters"]} />
                  <Bar dataKey="count" fill={COLORS.primaryDark} radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded-2xl border border-att-100 bg-white p-5 shadow-sm shadow-att-100/40 xl:col-span-2">
              <h4 className="font-semibold text-slate-800">By Environment</h4>
              <p className="mb-4 text-sm text-slate-500">Environment mix based on the current cluster result set</p>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={clusterOverview.environmentData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#d9ebf5" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(value: number) => [value, "Clusters"]} />
                  <Bar dataKey="value" fill={COLORS.primaryLight} radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}
    </div>
    );
  };

  // ── Render Deployments Tab ──────────────────────────────────────────

  const renderDeploymentsTab = () => {
    const { search: dSearch, setSearch: setDSearch, page: dPage, setPage: setDPage, filtered: filteredDeps, totalPages: dTotalPages } = depsPag;
    const pagedDeps = pagedSortedDeps;

    return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <h2 className="text-xl font-semibold text-gray-800">
          Deployments {selectedCluster && `- ${selectedCluster.name}`}
        </h2>
        <div className="flex items-center gap-3">
          <select
            value={selectedNamespace}
            onChange={(e) => setSelectedNamespace(e.target.value)}
            className="px-3 py-2 border rounded-lg text-sm"
          >
            <option value="">All Namespaces</option>
            {namespaces.map((ns) => (
              <option key={ns} value={ns}>
                {ns}
              </option>
            ))}
          </select>
          {selectedCluster && (
            <div className="flex items-center gap-2">
              {canWrite && (
              <button
                onClick={() => deploymentsRefresh.start(true)}
                disabled={deploymentsRefresh.isRunning}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
              >
                {Icons.refresh(deploymentsRefresh.isRunning ? "w-4 h-4 animate-spin" : "w-4 h-4")}
                {deploymentsRefresh.isRunning ? "Syncing..." : "Sync from Kubernetes"}
              </button>
              )}
              {canWrite && (
              <button
                onClick={() => setCreateDeploymentDialog(true)}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm"
              >
                + Create Deployment
              </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Source & Last Sync Info */}
      {selectedCluster && (
        <div className="flex items-center gap-3">
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            deploymentsData?.source === "db" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
          }`}>
            Source: {deploymentsData?.source === "db" ? "Database" : "Kubernetes Live"}
          </span>
          {deploymentsData?.last_sync && (
            <span className="text-sm text-gray-500">
              Last synced: {formatDate(deploymentsData.last_sync)}
            </span>
          )}
          {!deploymentsData?.last_sync && (
            <span className="text-sm text-yellow-600">
              Not synced yet — cached table will update after background refresh
            </span>
          )}
          <BackgroundRefreshStatus sync={deploymentsRefresh} />
        </div>
      )}

      {!selectedCluster ? (
        <div className="text-center py-16 text-gray-500">
          Select a cluster from the Clusters tab to view deployments
        </div>
      ) : deploymentsError ? (
        <div className="text-center py-12">
          <div className="text-red-600 font-medium mb-2">{Icons.warning("w-6 h-6 mx-auto mb-2")}Failed to load deployments</div>
          <div className="text-sm text-gray-500 max-w-md mx-auto">{(deploymentsErr as Error)?.message || "Could not connect to the cluster. Check credentials and cluster state."}</div>
        </div>
      ) : loadingDeployments ? (
        <div className="text-center py-8 text-gray-500">Loading deployments...</div>
      ) : (
        <>
        {/* Mutation Activity Panel */}
        {mutationActivities.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-slate-50 border-b border-slate-200">
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Operation Status</span>
              <button
                onClick={() => setMutationActivities([])}
                className="text-xs text-slate-400 hover:text-slate-600"
                title="Clear all"
              >
                Clear all
              </button>
            </div>
            <ul className="divide-y divide-slate-100">
              {mutationActivities.map((activity) => {
                const isScaling = activity.status === "pending" || activity.status === "scaling";
                const isReady = activity.status === "ready" || activity.status === "deleted";
                const isFailed = activity.status === "failed";
                const actionLabel =
                  activity.action === "scale_up" ? `Scale up → ${activity.targetReplicas}` :
                  activity.action === "scale_down" ? `Scale down → ${activity.targetReplicas}` :
                  "Delete";
                const elapsed = Math.round((Date.now() - activity.startedAt) / 1000);
                return (
                  <li key={activity.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    {isScaling && (
                      <svg className="w-4 h-4 text-blue-500 animate-spin shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.49-8.49l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M7.76 7.76L4.93 4.93"/></svg>
                    )}
                    {isReady && (
                      <svg className="w-4 h-4 text-green-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>
                    )}
                    {isFailed && (
                      <svg className="w-4 h-4 text-red-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                    )}
                    <span className="font-semibold text-slate-800 shrink-0">{activity.deploymentName}</span>
                    <span className="text-slate-400 shrink-0 text-xs">{activity.namespace}</span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${
                      activity.action === "delete" ? "bg-red-50 text-red-700" :
                      activity.action === "scale_up" ? "bg-blue-50 text-blue-700" :
                      "bg-yellow-50 text-yellow-700"
                    }`}>{actionLabel}</span>
                    <span className={`flex-1 text-xs ${isFailed ? "text-red-600" : isReady ? "text-green-600" : "text-slate-500"}`}>
                      {activity.message || ""}
                    </span>
                    <span className="text-xs text-slate-300 shrink-0">{elapsed}s</span>
                    {(isReady || isFailed) && (
                      <button
                        onClick={() => dismissMutationActivity(activity.id)}
                        className="ml-1 text-slate-300 hover:text-slate-500 shrink-0"
                        title="Dismiss"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={14} height={14}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        <div className={gridStyles.shell}>
        <GridSearchBar search={dSearch} onSearch={setDSearch} onPage={setDPage} totalItems={allDeps.length} shownItems={filteredDeps.length} placeholder="Search deployments..." />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Name" active={depSort.key === "name"} direction={depSort.direction} onClick={() => setDepSort(nextSortState(depSort, "name"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={depSort.key === "namespace"} direction={depSort.direction} onClick={() => setDepSort(nextSortState(depSort, "namespace"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Image" active={depSort.key === "image"} direction={depSort.direction} onClick={() => setDepSort(nextSortState(depSort, "image"))} /></th>
                <th className={gridStyles.headerCell}>Version</th>
                <th className={gridStyles.headerCellCenter}><SortableHeader label="Replicas" active={depSort.key === "replicas"} direction={depSort.direction} onClick={() => setDepSort(nextSortState(depSort, "replicas"))} align="center" /></th>
                <th className={gridStyles.headerCellCenter}><SortableHeader label="Status" active={depSort.key === "status"} direction={depSort.direction} onClick={() => setDepSort(nextSortState(depSort, "status"))} align="center" /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedDeps.map((deployment) => (
                <tr key={`${deployment.namespace}/${deployment.name}`} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>
                    {deployment.name}
                  </td>
                  <td className={gridStyles.cell}>{deployment.namespace}</td>
                  <td className={gridStyles.monoCell}>
                    <span title={deployment.images[0]}>
                      {deployment.images[0]?.includes(":") ? deployment.images[0].substring(0, deployment.images[0].lastIndexOf(":")) : deployment.images[0] || "-"}
                    </span>
                  </td>
                  <td className={gridStyles.cell}>
                    <span className="text-xs font-mono font-semibold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded">
                      {deployment.images[0]?.includes(":") ? deployment.images[0].substring(deployment.images[0].lastIndexOf(":") + 1) : "latest"}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    {(() => {
                      const activeScale = mutationActivities.find(
                        (a) => a.deploymentName === deployment.name && a.namespace === deployment.namespace && (a.status === "pending" || a.status === "scaling")
                      );
                      return activeScale ? (
                        <span className="inline-flex items-center gap-1 font-mono text-blue-600">
                          <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.49-8.49l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M7.76 7.76L4.93 4.93"/></svg>
                          {deployment.ready_replicas}/{activeScale.targetReplicas}
                        </span>
                      ) : (
                        <span className="font-mono">
                          {deployment.ready_replicas}/{deployment.replicas}
                        </span>
                      );
                    })()}
                  </td>
                  <td className={gridStyles.centerCell}>
                    {deployment.ready_replicas === deployment.replicas ? (
                      <span className="inline-flex items-center gap-1 text-green-600">
                        {Icons.check("w-4 h-4")} Ready
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-yellow-600">
                        {Icons.warning("w-4 h-4")} Degraded
                      </span>
                    )}
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center gap-1">
                      <button
                        onClick={() => handleViewDeploymentPods(deployment)}
                        className="p-2 text-teal-600 hover:bg-teal-50 rounded-lg"
                        title="View Pods"
                      >
                        {Icons.pod()}
                      </button>
                      {canWrite && (
                      <>
                      <button
                        onClick={() => setScaleDialog({ deployment, replicas: deployment.replicas })}
                        className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg"
                        title="Scale Deployment"
                      >
                        {Icons.scale()}
                      </button>
                      <button
                        onClick={() => handleRestart(deployment)}
                        disabled={restartDeploymentMutation.isPending}
                        className="p-2 text-orange-600 hover:bg-orange-50 rounded-lg disabled:opacity-50"
                        title="Restart Deployment"
                      >
                        {Icons.restart()}
                      </button>
                      <button
                        onClick={() => {
                          setEditDeploymentDialog(deployment);
                          setEditDepForm({
                            image: deployment.images[0] || "",
                            replicas: deployment.replicas,
                            cpu_request: deployment.cpu_request || "",
                            cpu_limit: deployment.cpu_limit || "",
                            memory_request: deployment.memory_request || "",
                            memory_limit: deployment.memory_limit || "",
                          });
                        }}
                        className="p-2 text-purple-600 hover:bg-purple-50 rounded-lg"
                        title="Edit Deployment"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                      </button>
                      <button
                        onClick={() => setDeleteDeploymentConfirm(deployment)}
                        className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
                        title="Delete Deployment"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      </button>
                      </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <GridPager page={dPage} totalPages={dTotalPages} onPage={setDPage} />
        </div>
        </>
      )}

      {/* Scale Dialog */}
      {scaleDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="text-lg font-semibold mb-4">Scale Deployment</h3>
            <p className="text-gray-600 mb-4">
              Scale <strong>{scaleDialog.deployment.name}</strong> in namespace{" "}
              <strong>{scaleDialog.deployment.namespace}</strong>
            </p>
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">Replicas</label>
              <input
                type="number"
                min={0}
                max={100}
                value={scaleDialog.replicas}
                onChange={(e) =>
                  setScaleDialog({ ...scaleDialog, replicas: parseInt(e.target.value) || 0 })
                }
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setScaleDialog(null)}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleScale}
                disabled={scaleDeploymentMutation.isPending}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {scaleDeploymentMutation.isPending ? "Scaling..." : "Scale"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Deployment Dialog */}
      {createDeploymentDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[520px] max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">Create Deployment</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                  <input type="text" value={depForm.name} onChange={e => setDepForm({ ...depForm, name: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="my-deployment" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Namespace *</label>
                  <input type="text" value={depForm.namespace} onChange={e => setDepForm({ ...depForm, namespace: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Container Image *</label>
                <input type="text" value={depForm.image} onChange={e => setDepForm({ ...depForm, image: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="nginx:latest" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Replicas</label>
                  <input type="number" min={0} max={100} value={depForm.replicas} onChange={e => setDepForm({ ...depForm, replicas: parseInt(e.target.value) || 1 })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Container Port</label>
                  <input type="text" value={depForm.port} onChange={e => setDepForm({ ...depForm, port: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="80" />
                </div>
              </div>
              <div className="border-t pt-3">
                <h4 className="text-sm font-medium text-gray-700 mb-2">Resources</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CPU Request</label>
                    <input type="text" value={depForm.cpu_request} onChange={e => setDepForm({ ...depForm, cpu_request: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CPU Limit</label>
                    <input type="text" value={depForm.cpu_limit} onChange={e => setDepForm({ ...depForm, cpu_limit: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Memory Request</label>
                    <input type="text" value={depForm.memory_request} onChange={e => setDepForm({ ...depForm, memory_request: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Memory Limit</label>
                    <input type="text" value={depForm.memory_limit} onChange={e => setDepForm({ ...depForm, memory_limit: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setCreateDeploymentDialog(false)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
              <button onClick={handleCreateDeployment} disabled={createDeploymentMutation.isPending || !depForm.name || !depForm.image} className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
                {createDeploymentMutation.isPending ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Deployment Dialog */}
      {editDeploymentDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">Edit Deployment: {editDeploymentDialog.name}</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Image</label>
                <input type="text" value={editDepForm.image} onChange={e => setEditDepForm({ ...editDepForm, image: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Replicas</label>
                <input type="number" min={0} max={100} value={editDepForm.replicas} onChange={e => setEditDepForm({ ...editDepForm, replicas: parseInt(e.target.value) || 0 })} className="w-full px-3 py-2 border rounded-lg text-sm" />
              </div>
              <div className="border-t pt-3">
                <h4 className="text-sm font-medium text-gray-700 mb-2">Resources (leave blank to keep current)</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CPU Request</label>
                    <input type="text" value={editDepForm.cpu_request} onChange={e => setEditDepForm({ ...editDepForm, cpu_request: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="100m" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CPU Limit</label>
                    <input type="text" value={editDepForm.cpu_limit} onChange={e => setEditDepForm({ ...editDepForm, cpu_limit: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="500m" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Memory Request</label>
                    <input type="text" value={editDepForm.memory_request} onChange={e => setEditDepForm({ ...editDepForm, memory_request: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="128Mi" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Memory Limit</label>
                    <input type="text" value={editDepForm.memory_limit} onChange={e => setEditDepForm({ ...editDepForm, memory_limit: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="512Mi" />
                  </div>
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setEditDeploymentDialog(null)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
              <button onClick={handleUpdateDeployment} disabled={updateDeploymentMutation.isPending} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {updateDeploymentMutation.isPending ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Deployment Confirmation */}
      {deleteDeploymentConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="text-lg font-semibold mb-2 text-red-700">Delete Deployment</h3>
            <p className="text-gray-600 mb-4">
              Are you sure you want to delete <strong>{deleteDeploymentConfirm.name}</strong> in namespace <strong>{deleteDeploymentConfirm.namespace}</strong>? This cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteDeploymentConfirm(null)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
              <button onClick={handleDeleteDeployment} disabled={deleteDeploymentMutation.isPending} className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50">
                {deleteDeploymentMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    );
  };

  // ── Render Pod Metrics Tab ──────────────────────────────────────────

  const renderPodMetricsTab = () => {
    const { search: pSearch, setSearch: setPSearch, page: pPage, setPage: setPPage, filtered: filteredPods, totalPages: pTotalPages } = podsPag;
    const pagedPods = pagedSortedPods;

    return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <h2 className="text-xl font-semibold text-gray-800">
          Pod Metrics {selectedCluster && `- ${selectedCluster.name}`}
        </h2>
        {selectedCluster && (
          <select
            value={selectedNamespace}
            onChange={(e) => setSelectedNamespace(e.target.value)}
            className="px-3 py-2 border rounded-lg text-sm"
          >
            <option value="">All Namespaces</option>
            {podNamespaces.map((ns) => (
              <option key={ns} value={ns}>
                {ns}
              </option>
            ))}
          </select>
        )}
      </div>
      {selectedCluster && (
        <div className="flex items-center gap-3">
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            podMetricsData?.source === "db" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
          }`}>
            Source: {podMetricsData?.source === "db" ? "Database" : "Kubernetes Live"}
          </span>
          {podMetricsData?.last_sync && (
            <span className="text-sm text-gray-500">
              Last synced: {formatDate(podMetricsData.last_sync)}
            </span>
          )}
          {!podMetricsData?.last_sync && (
            <span className="text-sm text-yellow-600">
              Not synced yet — cached table will update after background refresh
            </span>
          )}
          <BackgroundRefreshStatus sync={podMetricsRefresh} />
        </div>
      )}

      {!selectedCluster ? (
        <div className="text-center py-16 text-gray-500">
          Select a cluster from the Clusters tab to view pod metrics
        </div>
      ) : podMetricsError && allPods.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-red-600 font-medium mb-2">{Icons.warning("w-6 h-6 mx-auto mb-2")}Failed to load pod metrics</div>
          <div className="text-sm text-gray-500 max-w-md mx-auto">{(podMetricsErr as Error)?.message || "Could not connect to the cluster. Check credentials and cluster state."}</div>
        </div>
      ) : loadingPodMetrics && allPods.length === 0 ? (
        <div className="text-center py-8 text-gray-500">Loading pod metrics...</div>
      ) : (
        <>
          {/* Pod Table with Search */}
          <div className={gridStyles.shell}>
          <GridSearchBar search={pSearch} onSearch={setPSearch} onPage={setPPage} totalItems={allPods.length} shownItems={filteredPods.length} placeholder="Search pods..." />
          <div className="overflow-x-auto">
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}><SortableHeader label="Pod" active={podSort.key === "pod_name"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "pod_name"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={podSort.key === "namespace"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "namespace"))} /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Phase" active={podSort.key === "phase"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "phase"))} align="center" /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Node" active={podSort.key === "node"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "node"))} /></th>
                  <th className={gridStyles.headerCell} style={{ minWidth: 180 }}><SortableHeader label="CPU (Use / Req / Lim)" active={podSort.key === "cpu"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "cpu"))} /></th>
                  <th className={gridStyles.headerCell} style={{ minWidth: 180 }}><SortableHeader label="Memory (Use / Req / Lim)" active={podSort.key === "memory"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "memory"))} /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Restarts" active={podSort.key === "restarts"} direction={podSort.direction} onClick={() => setPodSort(nextSortState(podSort, "restarts"))} align="center" /></th>
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedPods.map((pod) => {
                  const cpuPct = pod.total_cpu_limit && pod.total_cpu_limit > 0
                    ? Math.round((pod.total_cpu_millicores / pod.total_cpu_limit) * 100)
                    : null;
                  const cpuReqPct = pod.total_cpu_request && pod.total_cpu_request > 0
                    ? Math.round((pod.total_cpu_millicores / pod.total_cpu_request) * 100)
                    : null;
                  const memPct = pod.total_memory_limit_mb && pod.total_memory_limit_mb > 0
                    ? Math.round((pod.total_memory_mb / pod.total_memory_limit_mb) * 100)
                    : null;
                  const memReqPct = pod.total_memory_request_mb && pod.total_memory_request_mb > 0
                    ? Math.round((pod.total_memory_mb / pod.total_memory_request_mb) * 100)
                    : null;
                  const barPct = (pct: number | null) => pct !== null ? Math.min(pct, 100) : 0;
                  const barColor = (pct: number | null) =>
                    pct === null ? "bg-gray-200" : pct > 90 ? "bg-red-500" : pct > 70 ? "bg-orange-400" : "bg-blue-500";
                  return (
                  <tr key={`${pod.namespace}/${pod.pod_name}`} className={gridStyles.row}>
                    <td className={gridStyles.cell}>
                      <div className="font-mono text-xs text-gray-800 truncate max-w-[180px]" title={pod.pod_name}>{pod.pod_name}</div>
                      {pod.pod_ip && <div className="text-xs text-gray-400">{pod.pod_ip}</div>}
                    </td>
                    <td className={gridStyles.cell}>{pod.namespace}</td>
                    <td className={gridStyles.centerCell}>
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                        pod.phase === "Running" ? "bg-green-100 text-green-800" :
                        pod.phase === "Succeeded" ? "bg-blue-100 text-blue-800" :
                        pod.phase === "Failed" ? "bg-red-100 text-red-800" :
                        "bg-yellow-100 text-yellow-800"
                      }`}>
                        {pod.phase || "Unknown"}
                      </span>
                    </td>
                    <td className={`${gridStyles.cell} truncate max-w-[120px]`} title={pod.node}>{pod.node || "—"}</td>
                    {/* CPU column with bar */}
                    <td className={gridStyles.cell}>
                      <div className="flex items-center gap-2 font-mono text-[11px]">
                        <span className={cpuPct !== null && cpuPct > 80 ? "text-red-600 font-bold" : "text-gray-800"}>{Math.round(pod.total_cpu_millicores)}m</span>
                        <span className="text-gray-400">/</span>
                        <span className="text-gray-500">{pod.total_cpu_request != null ? `${pod.total_cpu_request}m` : "—"}</span>
                        <span className="text-gray-400">/</span>
                        <span className="text-gray-500">{pod.total_cpu_limit != null ? `${pod.total_cpu_limit}m` : "—"}</span>
                      </div>
                      <div className="mt-1 w-full h-2 bg-gray-100 rounded-full overflow-hidden" title={cpuPct !== null ? `${cpuPct}% of limit` : cpuReqPct !== null ? `${cpuReqPct}% of request` : "No limits set"}>
                        <div className={`h-full rounded-full transition-all ${barColor(cpuPct ?? cpuReqPct)}`} style={{ width: `${barPct(cpuPct ?? cpuReqPct)}%` }} />
                      </div>
                      {(cpuPct !== null || cpuReqPct !== null) && (
                        <div className="text-[10px] text-gray-400 mt-0.5">
                          {cpuPct !== null ? `${cpuPct}% of limit` : `${cpuReqPct}% of request`}
                        </div>
                      )}
                    </td>
                    {/* Memory column with bar */}
                    <td className={gridStyles.cell}>
                      <div className="flex items-center gap-2 font-mono text-[11px]">
                        <span className={memPct !== null && memPct > 80 ? "text-red-600 font-bold" : "text-gray-800"}>{Math.round(pod.total_memory_mb)}MB</span>
                        <span className="text-gray-400">/</span>
                        <span className="text-gray-500">{pod.total_memory_request_mb != null ? `${Math.round(pod.total_memory_request_mb)}MB` : "—"}</span>
                        <span className="text-gray-400">/</span>
                        <span className="text-gray-500">{pod.total_memory_limit_mb != null ? `${Math.round(pod.total_memory_limit_mb)}MB` : "—"}</span>
                      </div>
                      <div className="mt-1 w-full h-2 bg-gray-100 rounded-full overflow-hidden" title={memPct !== null ? `${memPct}% of limit` : memReqPct !== null ? `${memReqPct}% of request` : "No limits set"}>
                        <div className={`h-full rounded-full transition-all ${barColor(memPct ?? memReqPct)}`} style={{ width: `${barPct(memPct ?? memReqPct)}%` }} />
                      </div>
                      {(memPct !== null || memReqPct !== null) && (
                        <div className="text-[10px] text-gray-400 mt-0.5">
                          {memPct !== null ? `${memPct}% of limit` : `${memReqPct}% of request`}
                        </div>
                      )}
                    </td>
                    <td className={gridStyles.centerCell}>
                      <span className={`font-mono ${pod.total_restarts && pod.total_restarts > 0 ? "text-red-600 font-bold" : "text-gray-500"}`}>
                        {pod.total_restarts ?? 0}
                      </span>
                    </td>
                    <td className={gridStyles.centerCell}>
                      <div className="flex items-center justify-center gap-1">
                        <button onClick={() => setPodLogDialog(pod)} title="View Logs" className="p-1 rounded hover:bg-blue-50 text-blue-600">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                        </button>
                        <button onClick={() => setPodExecDialog(pod)} title="Exec into Pod" className="p-1 rounded hover:bg-green-50 text-green-600">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                        </button>
                        <button onClick={() => setPodMetricsDialog(pod)} title="Pod Metrics" className="p-1 rounded hover:bg-purple-50 text-purple-600">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <GridPager page={pPage} totalPages={pTotalPages} onPage={setPPage} />
          </div>
        </>
      )}
    </div>
    );
  };

  // ── Render CronJobs Tab ─────────────────────────────────────────────

  const renderCronJobsTab = () => {
    const { search: cjSearch, setSearch: setCjSearch, page: cjPage, setPage: setCjPage, filtered: filteredCJs, totalPages: cjTotalPages } = cjsPag;
    const pagedCJs = pagedSortedCJs;

    return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <h2 className="text-xl font-semibold text-gray-800">
          CronJobs {selectedCluster && `- ${selectedCluster.name}`}
        </h2>
        {selectedCluster && (
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={selectedNamespace}
              onChange={(e) => setSelectedNamespace(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
            >
              <option value="">All Namespaces</option>
              {namespaceOptions.map((ns) => (
                <option key={ns} value={ns}>{ns}</option>
              ))}
            </select>
            {canWrite && (
            <button
              onClick={() => cronJobsRefresh.start(true)}
              disabled={cronJobsRefresh.isRunning}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {Icons.refresh(cronJobsRefresh.isRunning ? "w-4 h-4 animate-spin" : "w-4 h-4")}
              {cronJobsRefresh.isRunning ? "Syncing..." : "Sync from Kubernetes"}
            </button>
            )}
            {canWrite && (
            <button
              onClick={() => setCreateCronJobDialog(true)}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm"
            >
              + Create CronJob
            </button>
            )}
          </div>
        )}
      </div>

      {/* Source & Last Sync Info */}
      {selectedCluster && (
        <div className="flex items-center gap-3">
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            cronJobsData?.source === "db" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
          }`}>
            Source: {cronJobsData?.source === "db" ? "Database" : "Kubernetes Live"}
          </span>
          {cronJobsData?.last_sync && (
            <span className="text-sm text-gray-500">
              Last synced: {formatDate(cronJobsData.last_sync)}
            </span>
          )}
          {!cronJobsData?.last_sync && (
            <span className="text-sm text-yellow-600">
              Not synced yet — cached table will update after background refresh
            </span>
          )}
          <BackgroundRefreshStatus sync={cronJobsRefresh} />
        </div>
      )}

      {!selectedCluster ? (
        <div className="text-center py-16 text-gray-500">
          Select a cluster from the Clusters tab to view CronJobs
        </div>
      ) : cronJobsError ? (
        <div className="text-center py-12">
          <div className="text-red-600 font-medium mb-2">{Icons.warning("w-6 h-6 mx-auto mb-2")}Failed to load CronJobs</div>
          <div className="text-sm text-gray-500 max-w-md mx-auto">{(cronJobsErr as Error)?.message || "Could not connect to the cluster. Check credentials and cluster state."}</div>
        </div>
      ) : loadingCronJobs ? (
        <div className="text-center py-8 text-gray-500">Loading CronJobs...</div>
      ) : (
        <>
        <div className={gridStyles.shell}>
        <GridSearchBar search={cjSearch} onSearch={setCjSearch} onPage={setCjPage} totalItems={allCJs.length} shownItems={filteredCJs.length} placeholder="Search cronjobs..." />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Name" active={cjSort.key === "name"} direction={cjSort.direction} onClick={() => setCjSort(nextSortState(cjSort, "name"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={cjSort.key === "namespace"} direction={cjSort.direction} onClick={() => setCjSort(nextSortState(cjSort, "namespace"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Schedule" active={cjSort.key === "schedule"} direction={cjSort.direction} onClick={() => setCjSort(nextSortState(cjSort, "schedule"))} /></th>
                <th className={gridStyles.headerCellCenter}><SortableHeader label="Status" active={cjSort.key === "suspended"} direction={cjSort.direction} onClick={() => setCjSort(nextSortState(cjSort, "suspended"))} align="center" /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Last Run" active={cjSort.key === "last_schedule_time"} direction={cjSort.direction} onClick={() => setCjSort(nextSortState(cjSort, "last_schedule_time"))} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedCJs.map((cronjob) => (
                <tr key={`${cronjob.namespace}/${cronjob.name}`} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>
                    <button
                      onClick={() => setViewCronJobDialog({ cluster_id: selectedCluster!.id, namespace: cronjob.namespace, name: cronjob.name })}
                      className="text-blue-600 hover:underline"
                    >
                      {cronjob.name}
                    </button>
                  </td>
                  <td className={gridStyles.cell}>{cronjob.namespace}</td>
                  <td className={`${gridStyles.cell} font-mono`}>{cronjob.schedule}</td>
                  <td className={gridStyles.centerCell}>
                    {cronjob.suspended ? (
                      <span className="inline-flex items-center gap-1 px-2 py-1 bg-red-100 text-red-800 rounded-full text-xs">
                        {Icons.pause("w-3 h-3")} Suspended
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 text-green-800 rounded-full text-xs">
                        {Icons.play("w-3 h-3")} Active
                      </span>
                    )}
                  </td>
                  <td className={gridStyles.cell}>
                    {cronjob.last_schedule_time
                      ? formatDate(cronjob.last_schedule_time)
                      : "Never"}
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center gap-1">
                      {canWrite && (
                      <>
                      <button
                        onClick={() => handleTriggerCronJob(cronjob)}
                        disabled={triggerCronJobMutation.isPending}
                        className="p-2 text-indigo-600 hover:bg-indigo-50 rounded-lg disabled:opacity-50"
                        title="Run Now"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}><polygon points="5 3 19 12 5 21 5 3"/></svg>
                      </button>
                      <button
                        onClick={() => handleCronJobToggle(cronjob)}
                        disabled={suspendCronJobMutation.isPending}
                        className={`p-2 rounded-lg ${
                          cronjob.suspended
                            ? "text-green-600 hover:bg-green-50"
                            : "text-yellow-600 hover:bg-yellow-50"
                        } disabled:opacity-50`}
                        title={cronjob.suspended ? "Resume" : "Suspend"}
                      >
                        {cronjob.suspended ? Icons.play() : Icons.pause()}
                      </button>
                      <button
                        onClick={() => { setEditCronJobDialog(cronjob); setEditCjForm({ schedule: cronjob.schedule, image: cronjob.image || "", suspended: cronjob.suspended }); }}
                        className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg"
                        title="Edit CronJob"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                      </button>
                      <button
                        onClick={() => setDeleteCronJobConfirm(cronjob)}
                        className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
                        title="Delete CronJob"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      </button>
                      </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <GridPager page={cjPage} totalPages={cjTotalPages} onPage={setCjPage} />
        </div>
        </>
      )}

      {/* Create CronJob Dialog */}
      {createCronJobDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[560px] max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">Create CronJob</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                  <input type="text" value={cjForm.name} onChange={e => setCjForm({ ...cjForm, name: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="my-cronjob" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Namespace *</label>
                  <input type="text" value={cjForm.namespace} onChange={e => setCjForm({ ...cjForm, namespace: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Schedule *</label>
                <input type="text" value={cjForm.schedule} onChange={e => setCjForm({ ...cjForm, schedule: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="*/5 * * * *" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Container Image *</label>
                <input type="text" value={cjForm.image} onChange={e => setCjForm({ ...cjForm, image: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="busybox:latest" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Command (space-separated)</label>
                  <input type="text" value={cjForm.command} onChange={e => setCjForm({ ...cjForm, command: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="/bin/sh -c" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Args (space-separated)</label>
                  <input type="text" value={cjForm.args} onChange={e => setCjForm({ ...cjForm, args: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="echo hello" />
                </div>
              </div>

              {/* Job Policies */}
              <div className="border-t pt-3">
                <h4 className="text-sm font-medium text-gray-700 mb-2">Job Policies</h4>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Concurrency Policy</label>
                    <select value={cjForm.concurrency_policy} onChange={e => setCjForm({ ...cjForm, concurrency_policy: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm">
                      <option value="Forbid">Forbid</option>
                      <option value="Allow">Allow</option>
                      <option value="Replace">Replace</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Restart Policy</label>
                    <select value={cjForm.restart_policy} onChange={e => setCjForm({ ...cjForm, restart_policy: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm">
                      <option value="OnFailure">OnFailure</option>
                      <option value="Never">Never</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Backoff Limit</label>
                    <input type="number" min={0} value={cjForm.backoff_limit} onChange={e => setCjForm({ ...cjForm, backoff_limit: parseInt(e.target.value) || 0 })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 mt-2">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Success History</label>
                    <input type="number" min={0} value={cjForm.successful_jobs_history_limit} onChange={e => setCjForm({ ...cjForm, successful_jobs_history_limit: parseInt(e.target.value) || 0 })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Failure History</label>
                    <input type="number" min={0} value={cjForm.failed_jobs_history_limit} onChange={e => setCjForm({ ...cjForm, failed_jobs_history_limit: parseInt(e.target.value) || 0 })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Service Account</label>
                    <input type="text" value={cjForm.service_account_name} onChange={e => setCjForm({ ...cjForm, service_account_name: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="default" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 mt-2">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Active Deadline (sec)</label>
                    <input type="text" value={cjForm.active_deadline_seconds} onChange={e => setCjForm({ ...cjForm, active_deadline_seconds: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="Optional" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">TTL After Finished (sec)</label>
                    <input type="text" value={cjForm.ttl_seconds_after_finished} onChange={e => setCjForm({ ...cjForm, ttl_seconds_after_finished: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="Optional" />
                  </div>
                </div>
              </div>

              {/* Resources */}
              <div className="border-t pt-3">
                <h4 className="text-sm font-medium text-gray-700 mb-2">Resources</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CPU Request</label>
                    <input type="text" value={cjForm.cpu_request} onChange={e => setCjForm({ ...cjForm, cpu_request: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CPU Limit</label>
                    <input type="text" value={cjForm.cpu_limit} onChange={e => setCjForm({ ...cjForm, cpu_limit: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Memory Request</label>
                    <input type="text" value={cjForm.memory_request} onChange={e => setCjForm({ ...cjForm, memory_request: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Memory Limit</label>
                    <input type="text" value={cjForm.memory_limit} onChange={e => setCjForm({ ...cjForm, memory_limit: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
                  </div>
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setCreateCronJobDialog(false)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
              <button onClick={handleCreateCronJob} disabled={createCronJobMutation.isPending || !cjForm.name || !cjForm.image} className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
                {createCronJobMutation.isPending ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit CronJob Dialog */}
      {editCronJobDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[420px]">
            <h3 className="text-lg font-semibold mb-4">Edit CronJob: {editCronJobDialog.name}</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Schedule</label>
                <input type="text" value={editCjForm.schedule} onChange={e => setEditCjForm({ ...editCjForm, schedule: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Image</label>
                <input type="text" value={editCjForm.image} onChange={e => setEditCjForm({ ...editCjForm, image: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" />
              </div>
              <div className="flex items-center gap-3">
                <label className="text-sm font-medium text-gray-700">Suspended</label>
                <button onClick={() => setEditCjForm({ ...editCjForm, suspended: !editCjForm.suspended })} className={`relative w-12 h-6 rounded-full transition-colors ${editCjForm.suspended ? "bg-red-500" : "bg-green-500"}`}>
                  <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${editCjForm.suspended ? "translate-x-6" : ""}`} />
                </button>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setEditCronJobDialog(null)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
              <button onClick={handleUpdateCronJob} disabled={updateCronJobMutation.isPending} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {updateCronJobMutation.isPending ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* View CronJob Detail Dialog */}
      {viewCronJobDialog && <CronJobDetailDialog {...viewCronJobDialog} onClose={() => setViewCronJobDialog(null)} />}

      {/* Delete CronJob Confirmation */}
      {deleteCronJobConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="text-lg font-semibold mb-2 text-red-700">Delete CronJob</h3>
            <p className="text-gray-600 mb-4">
              Are you sure you want to delete <strong>{deleteCronJobConfirm.name}</strong> in namespace <strong>{deleteCronJobConfirm.namespace}</strong>? This cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteCronJobConfirm(null)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
              <button onClick={handleDeleteCronJob} disabled={deleteCronJobMutation.isPending} className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50">
                {deleteCronJobMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    );
  };

  // ── Render Node Pools Tab ─────────────────────────────────────────────

  const renderNodePoolsTab = () => {
    const { search: npSearch, setSearch: setNpSearch, page: npPage, setPage: setNpPage, filtered: filteredPools, totalPages: npTotalPages } = poolsPag;
    const pagedPools = pagedSortedPools;

    return (
    <div className="space-y-4">
      {/* Header with Sync / Refresh buttons */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <h2 className="text-xl font-semibold text-gray-800">
          Node Pools {selectedCluster && `- ${selectedCluster.name}`}
        </h2>
        {selectedCluster && (
          <div className="flex items-center gap-2">
            {canWrite && (
            <button
              onClick={() => nodePoolsRefresh.start(true)}
              disabled={nodePoolsRefresh.isRunning}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm"
            >
              {Icons.refresh(nodePoolsRefresh.isRunning ? "w-4 h-4 animate-spin" : "w-4 h-4")}
              {nodePoolsRefresh.isRunning ? "Syncing..." : "Sync from Azure"}
            </button>
            )}
          </div>
        )}
      </div>

      {/* Source & Last Sync Info */}
      {selectedCluster && nodePoolsData && (
        <div className="flex items-center gap-3">
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            nodePoolsData.source === "db" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
          }`}>
            Source: {nodePoolsData.source === "db" ? "Database" : "Azure Live"}
          </span>
          {nodePoolsData.last_sync && (
            <span className="text-sm text-gray-500">
              Last synced: {formatDate(nodePoolsData.last_sync)}
            </span>
          )}
          {!nodePoolsData.last_sync && (
            <span className="text-sm text-yellow-600">
              Not synced yet — cached table will update after background refresh
            </span>
          )}
          <BackgroundRefreshStatus sync={nodePoolsRefresh} />
        </div>
      )}

      {!selectedCluster ? (
        <div className="text-center py-16 text-gray-500">
          Select a cluster from the Clusters tab to manage node pools
        </div>
      ) : nodePoolsError ? (
        <div className="text-center py-12">
          <div className="text-red-600 font-medium mb-2">{Icons.warning("w-6 h-6 mx-auto mb-2")}Failed to load node pools</div>
          <div className="text-sm text-gray-500 max-w-md mx-auto">{(nodePoolsErr as Error)?.message || "Could not connect to the cluster. Check credentials and cluster state."}</div>
        </div>
      ) : loadingNodePools ? (
        <div className="text-center py-8 text-gray-500">Loading node pools...</div>
      ) : (
        <>
          {/* Summary Stats Row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              title="Total Pools"
              value={nodePoolsData?.count || 0}
              icon={Icons.cluster("h-5 w-5")}
              tone="blue"
            />
            <MetricCard
              title="Total Nodes"
              value={nodePoolsData?.node_pools?.reduce((s, p) => s + p.count, 0) || 0}
              icon={MetricCardIcons.server()}
              tone="green"
            />
            <MetricCard
              title="Autoscaling"
              value={nodePoolsData?.node_pools?.filter(p => p.enable_auto_scaling).length || 0}
              icon={Icons.scale("h-5 w-5")}
              tone="purple"
            />
            <MetricCard
              title="System Pools"
              value={nodePoolsData?.node_pools?.filter(p => p.mode === "System").length || 0}
              icon={MetricCardIcons.layers()}
              tone="orange"
            />
          </div>

          {/* Node Pools Table */}
          <div className={gridStyles.shell}>
            <GridSearchBar search={npSearch} onSearch={setNpSearch} onPage={setNpPage} totalItems={allPools.length} shownItems={filteredPools.length} placeholder="Search node pools..." />
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={`${gridStyles.headerCell} w-8`}></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Name" active={npSort.key === "name"} direction={npSort.direction} onClick={() => setNpSort(nextSortState(npSort, "name"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Mode" active={npSort.key === "mode"} direction={npSort.direction} onClick={() => setNpSort(nextSortState(npSort, "mode"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="VM Size" active={npSort.key === "vm_size"} direction={npSort.direction} onClick={() => setNpSort(nextSortState(npSort, "vm_size"))} /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Nodes" active={npSort.key === "count"} direction={npSort.direction} onClick={() => setNpSort(nextSortState(npSort, "count"))} align="center" /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Pods" active={npSort.key === "total_pods"} direction={npSort.direction} onClick={() => setNpSort(nextSortState(npSort, "total_pods"))} align="center" /></th>
                  <th className={gridStyles.headerCell}>Autoscaling</th>
                  <th className={gridStyles.headerCell}>Node Image</th>
                  <th className={gridStyles.headerCell}>Labels</th>
                  <th className={gridStyles.headerCell}><SortableHeader label="State" active={npSort.key === "provisioning_state"} direction={npSort.direction} onClick={() => setNpSort(nextSortState(npSort, "provisioning_state"))} /></th>
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedPools.map((pool) => (
                  <React.Fragment key={pool.name}>
                    {/* Main Row */}
                    <tr className={`${gridStyles.row} transition-colors`}>
                      {/* Expand toggle */}
                      <td className={gridStyles.cell}>
                        <button
                          onClick={() => togglePoolExpand(pool.name)}
                          className="text-gray-400 hover:text-gray-600"
                          title={expandedPools.has(pool.name) ? "Collapse" : "Expand details"}
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className={`w-4 h-4 transition-transform ${expandedPools.has(pool.name) ? "rotate-90" : ""}`}>
                            <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                          </svg>
                        </button>
                      </td>
                      {/* Name */}
                      <td className={gridStyles.strongCell}>
                        {pool.name}
                      </td>
                      {/* Mode badge */}
                      <td className={gridStyles.cell}>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          pool.mode === "System" ? "bg-purple-100 text-purple-800" : "bg-blue-100 text-blue-800"
                        }`}>
                          {pool.mode}
                        </span>
                      </td>
                      {/* VM Size */}
                      <td className={gridStyles.monoCell}>{pool.vm_size}</td>
                      {/* Nodes */}
                      <td className={`${gridStyles.centerCell} font-bold text-gray-800`}>{pool.count}</td>
                      {/* Pods */}
                      <td className={`${gridStyles.centerCell} font-bold text-blue-700`}>{pool.total_pods ?? "-"}</td>
                      {/* Autoscaling */}
                      <td className={gridStyles.cell}>
                        {pool.enable_auto_scaling ? (
                          <span className="text-green-700 text-xs font-medium">
                            {pool.min_count} – {pool.max_count}
                          </span>
                        ) : (
                          <span className="text-gray-400 text-xs">Off</span>
                        )}
                      </td>
                      {/* Node Image */}
                      <td className={gridStyles.cell}>
                        {pool.node_image_version ? (
                          <span className="font-mono text-[10px] text-gray-600 truncate block max-w-[180px]" title={pool.node_image_version}>{pool.node_image_version}</span>
                        ) : (
                          <span className="text-gray-400 text-xs">-</span>
                        )}
                      </td>
                      {/* Labels */}
                      <td className={gridStyles.cell}>
                        {pool.node_labels && Object.keys(pool.node_labels).length > 0 ? (
                          <div className="flex flex-wrap gap-1 max-w-[200px]">
                            {Object.entries(pool.node_labels).map(([k, v]) => (
                              <span key={k} className="text-[10px] bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full whitespace-nowrap">
                                {k}: {v}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-400 text-xs">-</span>
                        )}
                      </td>
                      {/* State */}
                      <td className={gridStyles.cell}>
                        <span className={`inline-flex items-center gap-1 text-xs font-medium ${
                          pool.power_state === "Running" ? "text-green-600" : "text-red-600"
                        }`}>
                          <span className={`w-2 h-2 rounded-full ${pool.power_state === "Running" ? "bg-green-500" : "bg-red-500"}`} />
                          {pool.power_state}
                        </span>
                      </td>
                      {/* Actions */}
                      <td className={gridStyles.centerCell}>
                        {canWrite && (
                        <div className="flex items-center justify-center gap-1">
                          <button
                            onClick={() => setNodePoolScaleDialog({ pool, nodeCount: pool.count })}
                            className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg"
                            title="Scale Node Pool"
                          >
                            {Icons.scale()}
                          </button>
                          <button
                            onClick={() =>
                              setAutoscaleDialog({
                                pool,
                                enable: pool.enable_auto_scaling,
                                minCount: pool.min_count || 1,
                                maxCount: pool.max_count || pool.count + 3,
                              })
                            }
                            className="p-2 text-purple-600 hover:bg-purple-50 rounded-lg"
                            title="Configure Autoscaling"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20}>
                              <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                            </svg>
                          </button>
                        </div>
                        )}
                      </td>
                    </tr>

                    {/* Expanded Detail Row */}
                    {expandedPools.has(pool.name) && (
                      <tr>
                        <td colSpan={11} className="bg-gray-50 px-6 py-4">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Left: Pool properties */}
                            <div className="space-y-2">
                              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Pool Details</h4>
                              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                                <span className="text-gray-500">OS Type</span>
                                <span className="text-gray-800">{pool.os_type}</span>
                                <span className="text-gray-500">Max Pods</span>
                                <span className="text-gray-800">{pool.max_pods}</span>
                                <span className="text-gray-500">K8s Version</span>
                                <span className="text-gray-800">{pool.kubernetes_version}</span>
                                <span className="text-gray-500">Provisioning</span>
                                <span className={`font-medium ${pool.provisioning_state === "Succeeded" ? "text-green-600" : pool.provisioning_state === "Failed" ? "text-red-600" : "text-yellow-600"}`}>
                                  {pool.provisioning_state}
                                </span>
                                {pool.availability_zones && pool.availability_zones.length > 0 && (
                                  <>
                                    <span className="text-gray-500">Zones</span>
                                    <span className="text-gray-800">{pool.availability_zones.join(", ")}</span>
                                  </>
                                )}
                              </div>
                              {pool.node_taints && pool.node_taints.length > 0 && (
                                <div className="mt-2">
                                  <span className="text-xs text-gray-500">Taints: </span>
                                  <span className="text-xs text-gray-700">{pool.node_taints.join(", ")}</span>
                                </div>
                              )}
                            </div>

                            {/* Right: Nodes */}
                            <div>
                              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                                Nodes ({pool.nodes?.length ?? 0})
                              </h4>
                              {pool.nodes && pool.nodes.length > 0 ? (
                                <div className="space-y-1 max-h-36 overflow-y-auto">
                                  {pool.nodes.map((node) => (
                                    <div key={node.name} className="flex items-center justify-between bg-white px-3 py-1.5 rounded border text-xs">
                                      <span className="font-mono text-gray-700 truncate max-w-[160px]" title={node.name}>{node.name}</span>
                                      <div className="flex items-center gap-3 text-gray-500">
                                        <span><strong className="text-blue-600">{node.pod_count}</strong> pods</span>
                                        <span>{node.allocatable_cpu} cpu</span>
                                        <span>{node.allocatable_memory} mem</span>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="text-xs text-gray-400 italic">No node details available</div>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
                {pagedPools.length === 0 && (
                  <tr><td colSpan={11} className="text-center py-8 text-gray-500">No node pools found</td></tr>
                )}
              </tbody>
            </table>
            <GridPager page={npPage} totalPages={npTotalPages} onPage={setNpPage} />
          </div>

          {/* Scale Node Pool Dialog */}
          {nodePoolScaleDialog && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
              <div className="bg-white rounded-lg p-6 w-96">
                <h3 className="text-lg font-semibold mb-4">Scale Node Pool</h3>
                <p className="text-gray-600 mb-4">
                  Scale <strong>{nodePoolScaleDialog.pool.name}</strong> (currently {nodePoolScaleDialog.pool.count} nodes)
                </p>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 mb-2">Node Count</label>
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    value={nodePoolScaleDialog.nodeCount}
                    onChange={(e) =>
                      setNodePoolScaleDialog({ ...nodePoolScaleDialog, nodeCount: parseInt(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 border rounded-lg"
                  />
                  {nodePoolScaleDialog.pool.enable_auto_scaling && (
                    <p className="text-xs text-yellow-600 mt-1">
                      Note: Autoscaling is enabled (min: {nodePoolScaleDialog.pool.min_count}, max: {nodePoolScaleDialog.pool.max_count}). Bounds will be adjusted if needed.
                    </p>
                  )}
                </div>
                <div className="flex justify-end gap-3">
                  <button
                    onClick={() => setNodePoolScaleDialog(null)}
                    className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleNodePoolScale}
                    disabled={scaleNodePoolMutation.isPending}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                  >
                    {scaleNodePoolMutation.isPending ? "Scaling..." : "Scale"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Autoscaling Config Dialog */}
          {autoscaleDialog && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
              <div className="bg-white rounded-lg p-6 w-96">
                <h3 className="text-lg font-semibold mb-4">Configure Autoscaling</h3>
                <p className="text-gray-600 mb-4">
                  Pool: <strong>{autoscaleDialog.pool.name}</strong>
                </p>
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <label className="text-sm font-medium text-gray-700">Enable Autoscaling</label>
                    <button
                      onClick={() => setAutoscaleDialog({ ...autoscaleDialog, enable: !autoscaleDialog.enable })}
                      className={`relative w-12 h-6 rounded-full transition-colors ${
                        autoscaleDialog.enable ? "bg-green-500" : "bg-gray-300"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                          autoscaleDialog.enable ? "translate-x-6" : ""
                        }`}
                      />
                    </button>
                  </div>
                  {autoscaleDialog.enable && (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Min Nodes</label>
                        <input
                          type="number"
                          min={1}
                          max={autoscaleDialog.maxCount}
                          value={autoscaleDialog.minCount}
                          onChange={(e) =>
                            setAutoscaleDialog({ ...autoscaleDialog, minCount: parseInt(e.target.value) || 1 })
                          }
                          className="w-full px-3 py-2 border rounded-lg"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Max Nodes</label>
                        <input
                          type="number"
                          min={autoscaleDialog.minCount}
                          max={1000}
                          value={autoscaleDialog.maxCount}
                          onChange={(e) =>
                            setAutoscaleDialog({ ...autoscaleDialog, maxCount: parseInt(e.target.value) || 1 })
                          }
                          className="w-full px-3 py-2 border rounded-lg"
                        />
                      </div>
                    </>
                  )}
                </div>
                <div className="flex justify-end gap-3 mt-6">
                  <button
                    onClick={() => setAutoscaleDialog(null)}
                    className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleAutoscalingUpdate}
                    disabled={updateAutoscalingMutation.isPending}
                    className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
                  >
                    {updateAutoscalingMutation.isPending ? "Updating..." : "Update"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
    );
  };

  // ── Render Scale History Tab ────────────────────────────────────────

  const renderHistoryTab = () => {
    const { search: hSearch, setSearch: setHSearch, page: hPage, setPage: setHPage, filtered: filteredHistory, totalPages: hTotalPages } = historyPag;
    const pagedHistory = pagedSortedHistory;

    return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-800">Scale History Audit Trail</h2>

      <div className={gridStyles.shell}>
      <GridSearchBar search={hSearch} onSearch={setHSearch} onPage={setHPage} totalItems={allHistory.length} shownItems={filteredHistory.length} placeholder="Search history..." />
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Timestamp" active={histSort.key === "timestamp"} direction={histSort.direction} onClick={() => setHistSort(nextSortState(histSort, "timestamp"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Cluster" active={histSort.key === "cluster_name"} direction={histSort.direction} onClick={() => setHistSort(nextSortState(histSort, "cluster_name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Deployment" active={histSort.key === "deployment_name"} direction={histSort.direction} onClick={() => setHistSort(nextSortState(histSort, "deployment_name"))} /></th>
              <th className={gridStyles.headerCellCenter}><SortableHeader label="Action" active={histSort.key === "action"} direction={histSort.direction} onClick={() => setHistSort(nextSortState(histSort, "action"))} align="center" /></th>
              <th className={gridStyles.headerCellCenter}>Change</th>
              <th className={gridStyles.headerCell}><SortableHeader label="User" active={histSort.key === "user_email"} direction={histSort.direction} onClick={() => setHistSort(nextSortState(histSort, "user_email"))} /></th>
            </tr>
          </thead>
          <tbody>
            {pagedHistory.map((entry) => (
              <tr key={entry.id} className={gridStyles.row}>
                <td className={gridStyles.cell}>
                  {formatDate(entry.timestamp)}
                </td>
                <td className={gridStyles.cell}>{entry.cluster_name}</td>
                <td className={gridStyles.cell}>
                  <div className="font-medium text-gray-800">{entry.deployment_name}</div>
                  <div className="text-xs text-gray-500">{entry.namespace}</div>
                </td>
                <td className={gridStyles.centerCell}>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    entry.action === "create" ? "bg-green-100 text-green-800" :
                    entry.action === "delete" ? "bg-red-100 text-red-800" :
                    entry.action === "update" ? "bg-blue-100 text-blue-800" :
                    "bg-gray-100 text-gray-800"
                  }`}>
                    {entry.action || "scale"}
                  </span>
                </td>
                <td className={gridStyles.centerCell}>
                  <span className="font-mono">
                    {entry.previous_replicas} → {entry.new_replicas}
                  </span>
                </td>
                <td className={gridStyles.cell}>{entry.user_email}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <GridPager page={hPage} totalPages={hTotalPages} onPage={setHPage} />
      </div>
    </div>
    );
  };

  // ── Main Render ─────────────────────────────────────────────────────

  return (
    <div className="py-6 space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">AKS Operations Center</h1>
          </div>
          <p className="text-sm text-gray-500 mt-1">Multi-cluster management, deployment control, and observability</p>
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200">
          <nav className="flex space-x-8 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
                  activeTab === tab.key
                    ? "border-blue-500 text-blue-600"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        {activeTab === "clusters" && renderClustersTab()}
        {activeTab === "nodepools" && renderNodePoolsTab()}
        {activeTab === "deployments" && renderDeploymentsTab()}
        {activeTab === "pods" && renderPodMetricsTab()}
        {activeTab === "cronjobs" && renderCronJobsTab()}
        {activeTab === "history" && renderHistoryTab()}
        {activeTab === "audit" && (
          <AuditHistoryTab clusterId={selectedCluster?.id} namespace={selectedNamespace || undefined} />
        )}
        {selectedCluster && ["services", "secrets", "configmaps", "ingress", "helm"].includes(activeTab) && (
          <>
            {activeTab === "services" && (
              <ServicesTab cluster={selectedCluster} namespace={selectedNamespace} namespaces={namespaceOptions}
                onNamespaceChange={setSelectedNamespace} canWrite={canWrite} showToast={showToast} formatDate={formatDate} />
            )}
            {activeTab === "secrets" && (
              <SecretsTab cluster={selectedCluster} namespace={selectedNamespace} namespaces={namespaceOptions}
                onNamespaceChange={setSelectedNamespace} canWrite={canWrite} showToast={showToast} formatDate={formatDate} />
            )}
            {activeTab === "configmaps" && (
              <ConfigMapsTab cluster={selectedCluster} namespace={selectedNamespace} namespaces={namespaceOptions}
                onNamespaceChange={setSelectedNamespace} canWrite={canWrite} showToast={showToast} formatDate={formatDate} />
            )}
            {activeTab === "ingress" && (
              <IngressTab cluster={selectedCluster} namespace={selectedNamespace} namespaces={namespaceOptions}
                onNamespaceChange={setSelectedNamespace} canWrite={canWrite} showToast={showToast} formatDate={formatDate} />
            )}
            {activeTab === "helm" && (
              <HelmTab cluster={selectedCluster} namespace={selectedNamespace} namespaces={namespaceOptions}
                onNamespaceChange={setSelectedNamespace} canWrite={canWrite} showToast={showToast} formatDate={formatDate} />
            )}
          </>
        )}
        {!selectedCluster && ["services", "secrets", "configmaps", "ingress", "helm"].includes(activeTab) && (
          <p className="text-sm text-gray-500 py-8">Select a cluster on the Clusters tab to continue.</p>
        )}

      {/* Generic Confirmation Modal */}
      {confirmDialog && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[60] p-4" onClick={() => setConfirmDialog(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md transform transition-all animate-in fade-in zoom-in-95" onClick={(e) => e.stopPropagation()}>
            {/* Icon + Title */}
            <div className="px-6 pt-6 pb-2 flex items-start gap-4">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 ${
                confirmDialog.variant === "danger" ? "bg-red-100" :
                confirmDialog.variant === "warning" ? "bg-amber-100" : "bg-blue-100"
              }`}>
                {confirmDialog.variant === "danger" ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-red-600"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                ) : confirmDialog.variant === "warning" ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-amber-600"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-blue-600"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                )}
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-gray-900">{confirmDialog.title}</h3>
                <p className="text-sm text-gray-500 mt-1 leading-relaxed">{confirmDialog.message}</p>
              </div>
            </div>
            {/* Actions */}
            <div className="px-6 pb-5 pt-4 flex justify-end gap-3">
              <button
                onClick={() => setConfirmDialog(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => { confirmDialog.onConfirm(); setConfirmDialog(null); }}
                className={`px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors ${
                  confirmDialog.variant === "danger" ? "bg-red-600 hover:bg-red-700" :
                  confirmDialog.variant === "warning" ? "bg-amber-500 hover:bg-amber-600" : "bg-blue-600 hover:bg-blue-700"
                }`}
              >
                {confirmDialog.confirmLabel || "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

      {/* ── Pod Logs Viewer Modal ──────────────────────────────────── */}
      {podLogDialog && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <div>
                  <h3 className="text-white font-semibold text-sm">Pod Logs</h3>
                  <p className="text-gray-400 text-xs font-mono">{podLogDialog.namespace}/{podLogDialog.pod_name}</p>
                </div>
              </div>
              <button onClick={() => setPodLogDialog(null)} className="text-gray-400 hover:text-white p-1">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>

            {/* Controls Bar */}
            <div className="flex flex-wrap items-center gap-3 px-5 py-3 border-b border-gray-700 bg-gray-800">
              {/* Container select */}
              <div className="flex items-center gap-2">
                <label className="text-gray-400 text-xs">Container:</label>
                <select value={podLogContainer} onChange={(e) => setPodLogContainer(e.target.value)}
                  className="bg-gray-700 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:ring-1 focus:ring-blue-500">
                  <option value="">All</option>
                  {(podContainersData?.containers || podLogDialog.containers || []).map((c: any) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>

              {/* Tail lines */}
              <div className="flex items-center gap-2">
                <label className="text-gray-400 text-xs">Tail:</label>
                <select value={podLogTailLines} onChange={(e) => setPodLogTailLines(Number(e.target.value))}
                  className="bg-gray-700 text-white text-xs px-2 py-1.5 rounded border border-gray-600">
                  {[100, 500, 1000, 2000, 5000].map((n) => <option key={n} value={n}>{n} lines</option>)}
                </select>
              </div>

              {/* Time filter */}
              <div className="flex items-center gap-2">
                <label className="text-gray-400 text-xs">Since:</label>
                <select value={podLogSinceSeconds ?? ""} onChange={(e) => setPodLogSinceSeconds(e.target.value ? Number(e.target.value) : undefined)}
                  className="bg-gray-700 text-white text-xs px-2 py-1.5 rounded border border-gray-600">
                  <option value="">All time</option>
                  <option value="300">Last 5m</option>
                  <option value="900">Last 15m</option>
                  <option value="3600">Last 1h</option>
                  <option value="21600">Last 6h</option>
                  <option value="86400">Last 24h</option>
                </select>
              </div>

              {/* Auto-refresh */}
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={podLogAutoRefresh} onChange={() => setPodLogAutoRefresh(!podLogAutoRefresh)}
                  className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500" />
                <span className="text-gray-400 text-xs">Auto-refresh</span>
                {podLogAutoRefresh && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
              </label>

              <div className="flex-1" />

              {/* Search Errors toggle */}
              <button onClick={() => setPodLogSearchActive(!podLogSearchActive)}
                className={`text-xs px-3 py-1.5 rounded font-medium transition-colors ${
                  podLogSearchActive ? "bg-red-600 text-white" : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                }`}>
                {podLogSearchActive ? "← Back to Logs" : "🔍 Search Errors"}
              </button>

              {!podLogSearchActive && (
                <button onClick={() => refetchPodLogs()} className="text-xs px-3 py-1.5 bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                  ↻ Refresh
                </button>
              )}

              {/* Download logs */}
              <button
                onClick={() => {
                  const content = podLogSearchActive && podLogSearchData?.matches
                    ? podLogSearchData.matches.map((m: PodLogSearchResult["matches"][0]) => `[${m.severity?.toUpperCase()}] L${m.line_number}: ${m.text}`).join("\n")
                    : podLogsData?.logs || "";
                  if (!content) return;
                  const blob = new Blob([content], { type: "text/plain" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `${podLogDialog.namespace}_${podLogDialog.pod_name}_${new Date().toISOString().replace(/[:.]/g, "-")}.log`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                disabled={!podLogsData?.logs && !(podLogSearchActive && podLogSearchData?.matches?.length)}
                className="text-xs px-3 py-1.5 bg-gray-700 text-gray-300 rounded hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                title="Download logs as .log file"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Download
              </button>
            </div>

            {/* Error search bar (when search mode active) */}
            {podLogSearchActive && (
              <div className="flex items-center gap-3 px-5 py-2 bg-gray-850 border-b border-gray-700 bg-gray-800/50">
                <input type="text" value={podLogSearchPattern} onChange={(e) => setPodLogSearchPattern(e.target.value)}
                  placeholder="Regex pattern (e.g. error|exception|fail)"
                  className="flex-1 bg-gray-700 text-white text-xs px-3 py-1.5 rounded border border-gray-600 font-mono focus:ring-1 focus:ring-red-500" />
                {podLogSearchData && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="px-2 py-0.5 rounded bg-red-900/50 text-red-400 font-medium">{podLogSearchData.severity_counts?.error || 0} errors</span>
                    <span className="px-2 py-0.5 rounded bg-yellow-900/50 text-yellow-400 font-medium">{podLogSearchData.severity_counts?.warning || 0} warnings</span>
                    <span className="px-2 py-0.5 rounded bg-blue-900/50 text-blue-400 font-medium">{podLogSearchData.severity_counts?.info || 0} info</span>
                    <span className="text-gray-500">({podLogSearchData.match_count} / {podLogSearchData.total_log_lines} lines)</span>
                  </div>
                )}
              </div>
            )}

            {/* Log Content */}
            <div className="flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed min-h-[300px] max-h-[60vh]">
              {(loadingPodLogs || loadingPodLogSearch) ? (
                <div className="text-gray-500 text-center py-8">Loading logs...</div>
              ) : podLogSearchActive && podLogSearchData ? (
                /* Search results view */
                podLogSearchData.matches && podLogSearchData.matches.length > 0 ? (
                  <div className="space-y-0.5">
                    {podLogSearchData.matches.map((m: PodLogSearchResult["matches"][0], i: number) => (
                      <div key={i} className={`flex gap-2 px-2 py-0.5 rounded ${
                        m.severity === "error" ? "bg-red-900/30 text-red-300" :
                        m.severity === "warning" ? "bg-yellow-900/20 text-yellow-300" :
                        "bg-blue-900/20 text-blue-300"
                      }`}>
                        <span className="text-gray-600 select-none w-10 text-right flex-shrink-0">{m.line_number}</span>
                        <span className={`px-1 rounded text-[10px] font-bold flex-shrink-0 ${
                          m.severity === "error" ? "bg-red-700 text-red-100" :
                          m.severity === "warning" ? "bg-yellow-700 text-yellow-100" :
                          "bg-blue-700 text-blue-100"
                        }`}>{m.severity?.toUpperCase()}</span>
                        <span className="whitespace-pre-wrap break-all">{m.text}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-green-400 text-center py-8">✓ No matches found for pattern "{podLogSearchPattern}"</div>
                )
              ) : podLogsData?.logs ? (
                /* Raw logs view */
                <div className="space-y-0">
                  {podLogsData.logs.split("\n").map((line: string, i: number) => {
                    const isError = /error|exception|fail|panic|fatal|crash/i.test(line);
                    const isWarn = /warn|warning/i.test(line);
                    return (
                      <div key={i} className={`flex gap-2 px-1 hover:bg-gray-800/50 ${
                        isError ? "bg-red-900/20 text-red-300" :
                        isWarn ? "bg-yellow-900/10 text-yellow-300" :
                        "text-gray-300"
                      }`}>
                        <span className="text-gray-600 select-none w-10 text-right flex-shrink-0">{i + 1}</span>
                        <span className="whitespace-pre-wrap break-all">{line}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-gray-500 text-center py-8">No logs available</div>
              )}
              <div ref={logEndRef} />
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-5 py-2 border-t border-gray-700 text-xs text-gray-500">
              <span>{podLogsData?.line_count ?? 0} lines loaded</span>
              <span>Container: {podLogsData?.container || "all"}</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Pod Exec Dialog ──────────────────────────────────────── */}
      {podExecDialog && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-green-600 flex items-center justify-center">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                </div>
                <div>
                  <h3 className="text-white font-semibold text-sm">Pod Terminal</h3>
                  <p className="text-gray-400 text-xs font-mono">{podExecDialog.namespace}/{podExecDialog.pod_name}</p>
                </div>
              </div>
              <button onClick={() => setPodExecDialog(null)} className="text-gray-400 hover:text-white p-1">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>

            {/* Container + Quick Commands */}
            <div className="flex flex-wrap items-center gap-3 px-5 py-2 border-b border-gray-700 bg-gray-800">
              <div className="flex items-center gap-2">
                <label className="text-gray-400 text-xs">Container:</label>
                <select value={execContainer} onChange={(e) => setExecContainer(e.target.value)}
                  className="bg-gray-700 text-white text-xs px-2 py-1.5 rounded border border-gray-600">
                  <option value="">Default</option>
                  {(podContainersData?.containers || podExecDialog.containers || []).map((c: any) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div className="h-4 w-px bg-gray-600" />
              <span className="text-gray-500 text-xs">Quick:</span>
              {["ls -la", "env", "df -h", "ps aux", "cat /etc/os-release", "whoami", "hostname"].map((cmd) => (
                <button key={cmd} onClick={() => { setExecCommand(cmd); }}
                  className="text-xs px-2 py-1 bg-gray-700 text-gray-300 rounded hover:bg-gray-600 font-mono">{cmd}</button>
              ))}
            </div>

            {/* Output Area */}
            <div className="flex-1 overflow-auto p-4 font-mono text-xs min-h-[250px] max-h-[50vh]">
              {execHistory.length === 0 ? (
                <div className="text-gray-500 text-center py-8">
                  <svg className="w-12 h-12 mx-auto mb-3 text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                  <p>Enter a command below to execute in this pod</p>
                  <p className="text-gray-600 mt-1">Or use the quick commands above</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {execHistory.map((entry, i) => (
                    <div key={i}>
                      <div className="flex items-center gap-2 text-green-400">
                        <span className="text-gray-500">$</span>
                        <span>{entry.command}</span>
                      </div>
                      <pre className={`whitespace-pre-wrap mt-1 pl-4 ${entry.success ? "text-gray-300" : "text-red-400"}`}>{entry.output || "(no output)"}</pre>
                    </div>
                  ))}
                </div>
              )}
              <div ref={execEndRef} />
            </div>

            {/* Command Input */}
            <div className="flex items-center gap-2 px-5 py-3 border-t border-gray-700 bg-gray-800">
              <span className="text-green-400 font-mono text-sm">$</span>
              <input type="text" value={execCommand} onChange={(e) => setExecCommand(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleExecCommand(); }}
                placeholder="Enter command..."
                className="flex-1 bg-gray-700 text-white text-sm px-3 py-2 rounded border border-gray-600 font-mono focus:ring-1 focus:ring-green-500 focus:border-green-500" />
              <button onClick={handleExecCommand} disabled={!execCommand.trim() || execPodMutation.isPending}
                className="px-4 py-2 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed">
                {execPodMutation.isPending ? "Running..." : "Run"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Pod Metrics Detail Modal ─────────────────────────────── */}
      {podMetricsDialog && (() => {
        const pod = podMetricsDialog;
        const cpuUsed = pod.total_cpu_millicores;
        const cpuReq = pod.total_cpu_request || 0;
        const cpuLim = pod.total_cpu_limit || 0;
        const memUsed = pod.total_memory_mb;
        const memReq = pod.total_memory_request_mb || 0;
        const memLim = pod.total_memory_limit_mb || 0;
        const cpuPctOfLim = cpuLim > 0 ? Math.round((cpuUsed / cpuLim) * 100) : null;
        const memPctOfLim = memLim > 0 ? Math.round((memUsed / memLim) * 100) : null;
        const cpuPctOfReq = cpuReq > 0 ? Math.round((cpuUsed / cpuReq) * 100) : null;
        const memPctOfReq = memReq > 0 ? Math.round((memUsed / memReq) * 100) : null;

        const gaugeColor = (pct: number | null) => !pct ? "#6b7280" : pct > 80 ? "#ef4444" : pct > 60 ? "#f59e0b" : "#10b981";
        const gaugeLabel = (pct: number | null) => !pct ? "N/A" : `${pct}%`;

        // Data for radial bar gauges
        const cpuGaugeData = [{ name: "CPU", value: Math.min(cpuPctOfLim ?? 0, 100), fill: gaugeColor(cpuPctOfLim) }];
        const memGaugeData = [{ name: "Memory", value: Math.min(memPctOfLim ?? 0, 100), fill: gaugeColor(memPctOfLim) }];

        return (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-auto">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center text-purple-600">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">Pod Resource Metrics</h3>
                    <p className="text-sm text-gray-500 font-mono">{pod.namespace}/{pod.pod_name}</p>
                  </div>
                </div>
                <button onClick={() => setPodMetricsDialog(null)} className="text-gray-400 hover:text-gray-600 p-1">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>

              {/* Pod Info Banner */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-6 py-4 bg-gray-50 border-b text-sm">
                <div><span className="text-gray-500">Phase:</span> <span className={`font-medium ${pod.phase === "Running" ? "text-green-700" : "text-yellow-700"}`}>{pod.phase}</span></div>
                <div><span className="text-gray-500">Node:</span> <span className="font-mono text-xs">{pod.node || "—"}</span></div>
                <div><span className="text-gray-500">QoS:</span> <span className="font-medium">{pod.qos_class || "—"}</span></div>
                <div><span className="text-gray-500">Restarts:</span> <span className={`font-bold ${(pod.total_restarts ?? 0) > 0 ? "text-red-600" : "text-gray-700"}`}>{pod.total_restarts ?? 0}</span></div>
              </div>

              {/* Gauge Charts */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 p-6">
                {/* CPU Gauge */}
                <div className="bg-white border rounded-xl p-4 text-center">
                  <h4 className="font-semibold text-gray-800 mb-2">CPU Utilization</h4>
                  <div className="relative">
                    <ResponsiveContainer width="100%" height={200}>
                      <RadialBarChart cx="50%" cy="50%" innerRadius="60%" outerRadius="85%" startAngle={180} endAngle={0}
                        data={cpuGaugeData} barSize={14}>
                        <RadialBar background dataKey="value" cornerRadius={8} />
                      </RadialBarChart>
                    </ResponsiveContainer>
                    <div className="absolute inset-0 flex flex-col items-center justify-center" style={{ top: "20px" }}>
                      <span className={`text-3xl font-bold ${cpuPctOfLim !== null && cpuPctOfLim > 80 ? "text-red-600" : cpuPctOfLim !== null && cpuPctOfLim > 60 ? "text-yellow-600" : "text-green-600"}`}>
                        {gaugeLabel(cpuPctOfLim)}
                      </span>
                      <span className="text-xs text-gray-500">of Limit</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
                    <div className="bg-blue-50 rounded-lg p-2">
                      <div className="text-gray-500">Used</div>
                      <div className="font-bold text-blue-700">{Math.round(cpuUsed)}m</div>
                    </div>
                    <div className="bg-green-50 rounded-lg p-2">
                      <div className="text-gray-500">Request</div>
                      <div className="font-bold text-green-700">{cpuReq}m</div>
                      {cpuPctOfReq !== null && <div className="text-gray-400">{cpuPctOfReq}%</div>}
                    </div>
                    <div className="bg-purple-50 rounded-lg p-2">
                      <div className="text-gray-500">Limit</div>
                      <div className="font-bold text-purple-700">{cpuLim}m</div>
                    </div>
                  </div>
                </div>

                {/* Memory Gauge */}
                <div className="bg-white border rounded-xl p-4 text-center">
                  <h4 className="font-semibold text-gray-800 mb-2">Memory Utilization</h4>
                  <div className="relative">
                    <ResponsiveContainer width="100%" height={200}>
                      <RadialBarChart cx="50%" cy="50%" innerRadius="60%" outerRadius="85%" startAngle={180} endAngle={0}
                        data={memGaugeData} barSize={14}>
                        <RadialBar background dataKey="value" cornerRadius={8} />
                      </RadialBarChart>
                    </ResponsiveContainer>
                    <div className="absolute inset-0 flex flex-col items-center justify-center" style={{ top: "20px" }}>
                      <span className={`text-3xl font-bold ${memPctOfLim !== null && memPctOfLim > 80 ? "text-red-600" : memPctOfLim !== null && memPctOfLim > 60 ? "text-yellow-600" : "text-green-600"}`}>
                        {gaugeLabel(memPctOfLim)}
                      </span>
                      <span className="text-xs text-gray-500">of Limit</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
                    <div className="bg-blue-50 rounded-lg p-2">
                      <div className="text-gray-500">Used</div>
                      <div className="font-bold text-blue-700">{Math.round(memUsed)}MB</div>
                    </div>
                    <div className="bg-green-50 rounded-lg p-2">
                      <div className="text-gray-500">Request</div>
                      <div className="font-bold text-green-700">{Math.round(memReq)}MB</div>
                      {memPctOfReq !== null && <div className="text-gray-400">{memPctOfReq}%</div>}
                    </div>
                    <div className="bg-purple-50 rounded-lg p-2">
                      <div className="text-gray-500">Limit</div>
                      <div className="font-bold text-purple-700">{Math.round(memLim)}MB</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Container-level breakdown */}
              {pod.containers && pod.containers.length > 0 && (
                <div className="px-6 pb-6">
                  <h4 className="font-semibold text-gray-800 mb-3">Container Breakdown</h4>
                  <div className="overflow-x-auto">
                    <table className={gridStyles.table}>
                      <thead className={gridStyles.head}>
                        <tr>
                          <th className={gridStyles.headerCell}>Container</th>
                          <th className={gridStyles.headerCell}>State</th>
                          <th className={`${gridStyles.headerCell} text-right`}>CPU Used</th>
                          <th className={`${gridStyles.headerCell} text-right`}>CPU Req</th>
                          <th className={`${gridStyles.headerCell} text-right`}>CPU Lim</th>
                          <th className={`${gridStyles.headerCell} text-right`}>Mem Used</th>
                          <th className={`${gridStyles.headerCell} text-right`}>Mem Req</th>
                          <th className={`${gridStyles.headerCell} text-right`}>Mem Lim</th>
                          <th className={gridStyles.headerCellCenter}>CPU Bar</th>
                          <th className={gridStyles.headerCellCenter}>Mem Bar</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pod.containers.map((c) => {
                          const cCpuPct = c.cpu_limit_m && c.cpu_limit_m > 0 ? Math.round((c.cpu_millicores / c.cpu_limit_m) * 100) : null;
                          const cMemPct = c.memory_limit_mb && c.memory_limit_mb > 0 ? Math.round((c.memory_mb / c.memory_limit_mb) * 100) : null;
                          return (
                            <tr key={c.name} className={gridStyles.row}>
                              <td className={`${gridStyles.cell} font-mono font-medium text-xs`}>{c.name}</td>
                              <td className={gridStyles.cell}>
                                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                                  c.state === "running" ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"
                                }`}>{c.state || "unknown"}</span>
                              </td>
                              <td className={`${gridStyles.cell} text-right font-mono text-xs`}>{Math.round(c.cpu_millicores)}m</td>
                              <td className={`${gridStyles.cell} text-right font-mono text-xs text-gray-500`}>{c.cpu_request || "—"}</td>
                              <td className={`${gridStyles.cell} text-right font-mono text-xs text-gray-500`}>{c.cpu_limit || "—"}</td>
                              <td className={`${gridStyles.cell} text-right font-mono text-xs`}>{Math.round(c.memory_mb)}MB</td>
                              <td className={`${gridStyles.cell} text-right font-mono text-xs text-gray-500`}>{c.memory_request || "—"}</td>
                              <td className={`${gridStyles.cell} text-right font-mono text-xs text-gray-500`}>{c.memory_limit || "—"}</td>
                              <td className={gridStyles.centerCell}>
                                {cCpuPct !== null ? (
                                  <div className="w-20 mx-auto">
                                    <div className="w-full bg-gray-200 rounded-full h-2">
                                      <div className={`h-2 rounded-full ${cCpuPct > 80 ? "bg-red-500" : cCpuPct > 60 ? "bg-yellow-500" : "bg-green-500"}`}
                                        style={{ width: `${Math.min(cCpuPct, 100)}%` }} />
                                    </div>
                                    <div className="text-center text-[10px] text-gray-500 mt-0.5">{cCpuPct}%</div>
                                  </div>
                                ) : <span className="text-gray-400 text-center block">—</span>}
                              </td>
                              <td className={gridStyles.centerCell}>
                                {cMemPct !== null ? (
                                  <div className="w-20 mx-auto">
                                    <div className="w-full bg-gray-200 rounded-full h-2">
                                      <div className={`h-2 rounded-full ${cMemPct > 80 ? "bg-red-500" : cMemPct > 60 ? "bg-yellow-500" : "bg-green-500"}`}
                                        style={{ width: `${Math.min(cMemPct, 100)}%` }} />
                                    </div>
                                    <div className="text-center text-[10px] text-gray-500 mt-0.5">{cMemPct}%</div>
                                  </div>
                                ) : <span className="text-gray-400 text-center block">—</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
};

// ── CronJob Detail Dialog (standalone) ────────────────────────────────

function CronJobDetailDialog({ cluster_id, namespace, name, onClose }: { cluster_id: string; namespace: string; name: string; onClose: () => void }) {
  const { formatDate } = usePortalTimezone();
  const { data, isLoading, isError, error } = useCronJobDetail(cluster_id, namespace, name);
  const [expandedConfigMap, setExpandedConfigMap] = useState<string | null>(null);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-[620px] max-h-[85vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">CronJob: {name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        {isLoading ? (
          <div className="text-center py-8 text-gray-500">Loading details...</div>
        ) : isError ? (
          <div className="text-center py-8">
            <div className="text-red-500 font-medium">Failed to load CronJob details.</div>
            <div className="text-xs text-gray-400 mt-2">{(error as Error)?.message || "Unknown error"}</div>
          </div>
        ) : data ? (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2">
              <div className="text-gray-500">Namespace</div><div className="font-medium">{data.namespace}</div>
              <div className="text-gray-500">Schedule</div><div className="font-mono">{data.schedule}</div>
              <div className="text-gray-500">Suspended</div><div>{data.suspended ? <span className="text-red-600 font-medium">Yes</span> : <span className="text-green-600 font-medium">No</span>}</div>
              <div className="text-gray-500">Concurrency</div><div>{data.concurrency_policy || "Allow"}</div>
              <div className="text-gray-500">Active Jobs</div><div>{data.active_count}</div>
              <div className="text-gray-500">Last Scheduled</div><div>{data.last_schedule_time ? formatDate(data.last_schedule_time) : "Never"}</div>
              <div className="text-gray-500">Last Successful</div><div>{data.last_successful_time ? formatDate(data.last_successful_time) : "Never"}</div>
              <div className="text-gray-500">Created</div><div>{data.created_at ? formatDate(data.created_at) : "—"}</div>
            </div>
            {data.image && (
              <div className="pt-2 border-t">
                <div className="text-gray-500 mb-1">Container Image</div>
                <div className="font-mono text-xs bg-gray-50 p-2 rounded break-all">{data.image}</div>
              </div>
            )}
            {data.command && data.command.length > 0 && (
              <div>
                <div className="text-gray-500 mb-1">Command</div>
                <div className="font-mono text-xs bg-gray-50 p-2 rounded">{data.command.join(" ")}</div>
              </div>
            )}
            {data.args && data.args.length > 0 && (
              <div>
                <div className="text-gray-500 mb-1">Args</div>
                <div className="font-mono text-xs bg-gray-50 p-2 rounded">{data.args.join(" ")}</div>
              </div>
            )}
            {data.resources && data.resources.requests && data.resources.limits && (Object.keys(data.resources.requests).length > 0 || Object.keys(data.resources.limits).length > 0) && (
              <div className="pt-2 border-t">
                <div className="text-gray-500 mb-1">Resources</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-gray-400">Requests:</span> {Object.entries(data.resources.requests).map(([k,v]) => `${k}=${v}`).join(", ") || "—"}</div>
                  <div><span className="text-gray-400">Limits:</span> {Object.entries(data.resources.limits).map(([k,v]) => `${k}=${v}`).join(", ") || "—"}</div>
                </div>
              </div>
            )}
            {data.labels && Object.keys(data.labels).length > 0 && (
              <div className="pt-2 border-t">
                <div className="text-gray-500 mb-1">Labels</div>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(data.labels).map(([k, v]) => (
                    <span key={k} className="text-xs bg-gray-100 px-2 py-0.5 rounded">{k}: {v}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Volume Mounts */}
            {data.volume_mounts && data.volume_mounts.length > 0 && (
              <div className="pt-2 border-t">
                <div className="text-gray-500 mb-1 font-medium">Volume Mounts</div>
                <div className="space-y-1">
                  {data.volume_mounts.map((vm, i) => (
                    <div key={i} className="text-xs bg-gray-50 p-2 rounded flex gap-4">
                      <span><span className="text-gray-400">Name:</span> {vm.name}</span>
                      <span><span className="text-gray-400">Path:</span> <code className="font-mono">{vm.mount_path}</code></span>
                      {vm.sub_path && <span><span className="text-gray-400">SubPath:</span> {vm.sub_path}</span>}
                      {vm.read_only === "True" && <span className="text-orange-600">read-only</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ConfigMap References (volumes) */}
            {data.configmap_refs && data.configmap_refs.length > 0 && (
              <div className="pt-2 border-t">
                <div className="text-gray-500 mb-2 font-medium flex items-center gap-1">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={14} height={14}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                  ConfigMaps (Volume Mounted)
                </div>
                <div className="space-y-2">
                  {data.configmap_refs.map((ref) => (
                    <div key={ref.configmap_name} className="border rounded-lg overflow-hidden">
                      <button
                        onClick={() => setExpandedConfigMap(expandedConfigMap === ref.configmap_name ? null : ref.configmap_name)}
                        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-xs"
                      >
                        <span className="font-medium text-indigo-700">{ref.configmap_name}</span>
                        <span className="text-gray-400 flex items-center gap-2">
                          <span>vol: {ref.volume_name}</span>
                          {ref.items.length > 0 && <span>{ref.items.length} key(s)</span>}
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={12} height={12} className={`transition-transform ${expandedConfigMap === ref.configmap_name ? "rotate-180" : ""}`}><polyline points="6 9 12 15 18 9"/></svg>
                        </span>
                      </button>
                      {expandedConfigMap === ref.configmap_name && (
                        <ConfigMapContent cluster_id={cluster_id} namespace={namespace} name={ref.configmap_name} />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ConfigMap References (envFrom) */}
            {data.env_configmap_refs && data.env_configmap_refs.length > 0 && (
              <div className="pt-2 border-t">
                <div className="text-gray-500 mb-2 font-medium flex items-center gap-1">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={14} height={14}><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
                  ConfigMaps (Environment)
                </div>
                <div className="space-y-2">
                  {data.env_configmap_refs.map((ref) => (
                    <div key={ref.name} className="border rounded-lg overflow-hidden">
                      <button
                        onClick={() => setExpandedConfigMap(expandedConfigMap === ref.name ? null : ref.name)}
                        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-xs"
                      >
                        <span className="font-medium text-indigo-700">{ref.name}</span>
                        <span className="text-gray-400 flex items-center gap-2">
                          {ref.prefix && <span>prefix: {ref.prefix}</span>}
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={12} height={12} className={`transition-transform ${expandedConfigMap === ref.name ? "rotate-180" : ""}`}><polyline points="6 9 12 15 18 9"/></svg>
                        </span>
                      </button>
                      {expandedConfigMap === ref.name && (
                        <ConfigMapContent cluster_id={cluster_id} namespace={namespace} name={ref.name} />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
        <div className="flex justify-end mt-4">
          <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Close</button>
        </div>
      </div>
    </div>
  );
}

// ── ConfigMap Content Viewer (lazy-loaded) ────────────────────────────

function ConfigMapContent({ cluster_id, namespace, name }: { cluster_id: string; namespace: string; name: string }) {
  const { data, isLoading, isError } = useConfigMapDetail(cluster_id, namespace, name);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  if (isLoading) return <div className="px-3 py-4 text-center text-xs text-gray-400">Loading ConfigMap...</div>;
  if (isError) return <div className="px-3 py-4 text-center text-xs text-red-400">Failed to load ConfigMap</div>;
  if (data?.detail_source === "unavailable") {
    return (
      <div className="px-3 py-4 text-center text-xs text-amber-600">
        ConfigMap content is unavailable from the live cluster.
        {data.data_unavailable_reason ? <div className="mt-1 text-[11px] text-amber-500">{data.data_unavailable_reason}</div> : null}
      </div>
    );
  }
  if (!data || !data.data || Object.keys(data.data).length === 0) return <div className="px-3 py-4 text-center text-xs text-gray-400">No data keys</div>;

  const entries = Object.entries(data.data);
  const q = search.trim().toLowerCase();
  const filtered = q
    ? entries.filter(([key, value]) => key.toLowerCase().includes(q) || value.toLowerCase().includes(q))
    : entries;

  return (
    <div className="border-t">
      {entries.length > 3 ? (
        <div className="px-3 py-2 border-b bg-att-50/40">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search config keys..."
            className="w-full border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-att-400"
          />
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <div className="px-3 py-4 text-center text-xs text-gray-400">No keys match your search</div>
      ) : (
        filtered.map(([key, value]) => (
          <div key={key} className="border-b last:border-b-0">
            <button
              onClick={() => setExpandedKey(expandedKey === key ? null : key)}
              className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-att-50 text-xs"
            >
              <span className="font-mono text-att-700">{key}</span>
              <span className="text-gray-400 flex items-center gap-1">
                {value.length > 100 ? `${(value.length / 1024).toFixed(1)} KB` : `${value.length} chars`}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={10} height={10} className={`transition-transform ${expandedKey === key ? "rotate-180" : ""}`}><polyline points="6 9 12 15 18 9"/></svg>
              </span>
            </button>
            {expandedKey === key && (
              <div className="px-3 pb-2">
                <pre className="font-mono text-xs bg-gray-900 text-green-300 p-3 rounded overflow-x-auto max-h-[300px] overflow-y-auto whitespace-pre-wrap">{value}</pre>
              </div>
            )}
          </div>
        ))
      )}
      {data.binary_data_keys && data.binary_data_keys.length > 0 && (
        <div className="px-3 py-2 text-xs text-gray-400">
          Binary data keys: {data.binary_data_keys.join(", ")}
        </div>
      )}
    </div>
  );
}

export default AKSOperationsPage;
