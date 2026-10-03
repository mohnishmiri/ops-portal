/**
 * Tests for the Deployment and Pod drill-down modals and their
 * "Download all logs" action.
 */

import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useDeploymentDetail: vi.fn(),
  usePodDetail: vi.fn(),
  downloadLogArchive: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { DeploymentDetailModal } from "./DeploymentDetailModal";
import { useLogArchiveDownload } from "./LogArchiveDownload";
import { PodDetailModal } from "./PodDetailModal";

const CLUSTER_ID =
  "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-01";

function pod(name: string, overrides: Partial<aksApi.WorkloadPod> = {}): aksApi.WorkloadPod {
  return {
    pod_name: name,
    namespace: "apps",
    phase: "Running",
    status: "Running",
    ready: true,
    node: "aks-node-1",
    pod_ip: "10.0.0.5",
    started_at: new Date().toISOString(),
    restarts: 0,
    containers: ["app"],
    revision: "3",
    ...overrides,
  };
}

function deployment(overrides: Partial<aksApi.DeploymentDetail> = {}): aksApi.DeploymentDetail {
  return {
    kind: "Deployment",
    name: "web",
    namespace: "apps",
    uid: "dep-1",
    labels: { app: "web" },
    annotations: {},
    selector: { app: "web" },
    images: ["repo/web:1.0.158"],
    containers: [{ name: "app", image: "repo/web:1.0.158", ports: ["8080/TCP"], cpu_request: "100m", cpu_limit: "", memory_request: "", memory_limit: "" }],
    created_at: null,
    generation: 3,
    observed_generation: 3,
    desired: 2,
    ready: 2,
    updated: 2,
    available: 2,
    unavailable: 0,
    update_strategy: "RollingUpdate",
    max_surge: "25%",
    max_unavailable: "25%",
    min_ready_seconds: 0,
    revision_history_limit: 10,
    progress_deadline_seconds: 600,
    paused: false,
    revision: "3",
    node_selector: {},
    service_account: "default",
    cpu_request: "100m",
    cpu_limit: "",
    memory_request: "",
    memory_limit: "",
    conditions: [],
    status: "Healthy",
    pods: [pod("web-7b9c-a"), pod("web-7b9c-b", { status: "CrashLoopBackOff", ready: false, restarts: 4 })],
    revisions: [],
    events: [
      { type: "Warning", reason: "FailedCreate", message: "exceeded quota", count: 2, last_seen: null, object: "ReplicaSet/web-7b9c" },
    ],
    hpa: null,
    yaml: "kind: Deployment",
    ...overrides,
  };
}

function useDownload(showToast = vi.fn()) {
  return renderHook(() => useLogArchiveDownload(showToast)).result;
}

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:archive");
  URL.revokeObjectURL = vi.fn();
});

describe("DeploymentDetailModal", () => {
  function setup(detail = deployment(), props: Partial<React.ComponentProps<typeof DeploymentDetailModal>> = {}) {
    (aksApi.useDeploymentDetail as any).mockReturnValue({ data: detail, isLoading: false, isError: false });
    const download = useDownload();
    const handlers = { onOpenPod: vi.fn(), onViewPodLogs: vi.fn(), onDeletePod: vi.fn(), onClose: vi.fn() };
    const view = render(
      <DeploymentDetailModal
        clusterId={CLUSTER_ID}
        namespace="apps"
        name="web"
        formatDate={(v) => v}
        logDownload={download.current}
        canDeletePod={false}
        {...handlers}
        {...props}
      />
    );
    return { ...handlers, download, view };
  }

  it("lists the deployment's pods and opens a pod from its name", () => {
    const { onOpenPod, onViewPodLogs } = setup();

    fireEvent.click(screen.getByRole("button", { name: "Pods (2)" }));
    expect(screen.getByText("CrashLoopBackOff")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "web-7b9c-b" }));
    expect(onOpenPod).toHaveBeenCalledWith(expect.objectContaining({ pod_name: "web-7b9c-b" }));

    fireEvent.click(screen.getAllByTitle("View Logs")[0]);
    expect(onViewPodLogs).toHaveBeenCalledWith(expect.objectContaining({ pod_name: "web-7b9c-a" }));
    expect(screen.queryByTitle("Delete Pod")).toBeNull(); // not granted
  });

  it("shows ReplicaSet events with the object they concern", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "Events (1)" }));

    expect(screen.getByText("FailedCreate")).toBeTruthy();
    expect(screen.getByText("ReplicaSet/web-7b9c")).toBeTruthy();
  });

  it("downloads the complete logs of every pod in the deployment", async () => {
    (aksApi.downloadLogArchive as any).mockResolvedValue({ blob: new Blob(["zip"]), filename: "web.zip" });
    const { download } = setup();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Download all logs \(2 pods\)/ }));
    });

    expect(aksApi.downloadLogArchive).toHaveBeenCalledWith(
      { clusterId: CLUSTER_ID, kind: "deployment", namespace: "apps", name: "web" },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(download.current.active).toBeNull();
  });

  it("disables the download when the deployment has no pods", () => {
    setup(deployment({ pods: [], desired: 0, ready: 0, status: "Idle" }));

    const button = screen.getByRole("button", { name: /Download all logs \(0 pods\)/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

describe("PodDetailModal", () => {
  const oomContainer: aksApi.PodContainerDetail = {
    name: "app",
    image: "repo/web:1",
    image_id: null,
    init: false,
    sidecar: false,
    ready: true,
    restart_count: 3,
    state: { state: "running", started_at: "2026-10-03T03:00:00Z" },
    last_state: { state: "terminated", reason: "OOMKilled", exit_code: 137, finished_at: "2026-10-03T02:59:00Z" },
    ports: ["8080/TCP (http)"],
    cpu_request: "100m",
    cpu_limit: "500m",
    memory_request: "128Mi",
    memory_limit: "256Mi",
    probes: { liveness: "http-get http://:8080/healthz delay=0s" },
    volume_mounts: [{ name: "config", mount_path: "/etc/app", read_only: true, sub_path: null }],
  };

  const podDetail: aksApi.PodDetail = {
    name: "web-7b9c-a",
    namespace: "apps",
    uid: "p1",
    phase: "Running",
    status: "Running",
    status_message: null,
    ready_containers: 1,
    total_containers: 1,
    restarts: 3,
    node: "aks-node-1",
    pod_ip: "10.0.0.5",
    pod_ips: ["10.0.0.5"],
    host_ip: "10.1.0.4",
    qos_class: "Burstable",
    service_account: "default",
    restart_policy: "Always",
    priority_class: null,
    termination_grace_period_seconds: 30,
    created_at: null,
    started_at: null,
    deletion_timestamp: null,
    owner: { kind: "ReplicaSet", name: "web-7b9c" },
    workload: { kind: "Deployment", name: "web" },
    labels: {},
    annotations: {},
    node_selector: {},
    tolerations: [],
    conditions: [],
    init_containers: [{ ...oomContainer, name: "init-db", init: true, restart_count: 0, last_state: null, state: { state: "terminated", reason: "Completed", exit_code: 0 } }],
    containers: [oomContainer],
    volumes: [{ name: "config", type: "ConfigMap", source: "web-config" }],
    events: [],
    yaml: "kind: Pod",
  };

  function setup() {
    (aksApi.usePodDetail as any).mockReturnValue({ data: podDetail, isLoading: false, isError: false });
    const onViewLogs = vi.fn();
    render(
      <PodDetailModal
        clusterId={CLUSTER_ID}
        namespace="apps"
        name="web-7b9c-a"
        formatDate={(v) => v}
        logDownload={useDownload().current}
        onViewLogs={onViewLogs}
        onClose={vi.fn()}
      />
    );
    return { onViewLogs };
  }

  it("shows the controlling Deployment and each container's last termination", () => {
    setup();

    expect(screen.getByText("Deployment/web")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Containers (2)" }));
    expect(screen.getByText(/Terminated: OOMKilled \(exit code 137\)/)).toBeTruthy();
    expect(screen.getByText("init")).toBeTruthy();
  });

  it("maps volumes to the containers that mount them", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "Volumes (1)" }));

    expect(screen.getByText("web-config")).toBeTruthy();
    expect(screen.getByText("init-db:/etc/app, app:/etc/app")).toBeTruthy();
  });

  it("opens the log viewer with every container, init containers included", () => {
    const { onViewLogs } = setup();

    fireEvent.click(screen.getByRole("button", { name: /View logs/ }));

    expect(onViewLogs).toHaveBeenCalledWith(expect.objectContaining({ pod_name: "web-7b9c-a", containers: ["init-db", "app"] }));
  });
});
