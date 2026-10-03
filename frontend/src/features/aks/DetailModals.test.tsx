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
  useConfigMapDetail: vi.fn(),
  useSecretDetail: vi.fn(),
  downloadLogArchive: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { DeploymentDetailModal } from "./DeploymentDetailModal";
import { useLogArchiveDownload } from "./LogArchiveDownload";
import { PodDetailModal } from "./PodDetailModal";
import { flattenSpec, projectedFilePaths } from "./PodVolumeDetail";

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

    fireEvent.click(screen.getByRole("tab", { name: "Pods (2)" }));
    expect(screen.getByText("CrashLoopBackOff")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "web-7b9c-b" }));
    expect(onOpenPod).toHaveBeenCalledWith(expect.objectContaining({ pod_name: "web-7b9c-b" }));

    fireEvent.click(screen.getAllByTitle("View Logs")[0]);
    expect(onViewPodLogs).toHaveBeenCalledWith(expect.objectContaining({ pod_name: "web-7b9c-a" }));
    expect(screen.queryByTitle("Delete Pod")).toBeNull(); // not granted
  });

  it("shows ReplicaSet events with the object they concern", () => {
    setup();

    fireEvent.click(screen.getByRole("tab", { name: "Events (1)" }));

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
  const CHECKSUM = "9dc0c284ac65" + "0".repeat(52);
  const oomContainer: aksApi.PodContainerDetail = {
    name: "app",
    image: "repo/web:1",
    image_id: `repo/web@sha256:${CHECKSUM}`,
    image_checksum: CHECKSUM,
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
    image_checksum: CHECKSUM,
    init_containers: [
      {
        ...oomContainer,
        name: "init-db",
        init: true,
        image_checksum: null,
        image_id: null,
        restart_count: 0,
        last_state: null,
        state: { state: "terminated", reason: "Completed", exit_code: 0 },
        volume_mounts: [],
      },
    ],
    containers: [
      {
        ...oomContainer,
        volume_mounts: [
          { name: "config", mount_path: "/etc/app", read_only: true, sub_path: null },
          { name: "creds", mount_path: "/opt/att/aaf", read_only: true, sub_path: null },
        ],
      },
    ],
    volumes: [
      { name: "config", type: "ConfigMap", source: "web-config", spec: { name: "web-config", defaultMode: 420 } },
      { name: "creds", type: "Secret", source: "aaf-cred", spec: { secretName: "aaf-cred", items: [{ key: "user", path: "user.txt" }] } },
    ],
    events: [],
    yaml: "kind: Pod",
  };

  function setup() {
    (aksApi.usePodDetail as any).mockReturnValue({ data: podDetail, isLoading: false, isError: false });
    (aksApi.useConfigMapDetail as any).mockReturnValue({
      data: { name: "web-config", namespace: "apps", data: { "application.properties": "server.port=8080" }, binary_data_keys: [] },
      isLoading: false,
      isError: false,
    });
    (aksApi.useSecretDetail as any).mockReturnValue({
      data: { name: "aaf-cred", namespace: "apps", type: "Opaque", keys: ["user", "password"], data: { user: "********", password: "********" } },
      isLoading: false,
      isError: false,
    });
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
    fireEvent.click(screen.getByRole("tab", { name: "Containers (2)" }));
    expect(screen.getByText("OOMKilled · exit 137")).toBeTruthy(); // Last Termination column
    expect(screen.getByText("init")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "app" })); // expand the row
    expect(screen.getByText(/Terminated: OOMKilled \(exit code 137\)/)).toBeTruthy();
  });

  it("shows the running image checksum in the overview and per container", () => {
    setup();

    expect(screen.getByText(CHECKSUM)).toBeTruthy(); // overview, in full
    fireEvent.click(screen.getByRole("tab", { name: "Containers (2)" }));
    expect(screen.getByText(`${CHECKSUM.slice(0, 12)}…`)).toBeTruthy(); // grid shows the short form
    expect(screen.getByText("not available — the container has not started")).toBeTruthy(); // init-db
    fireEvent.click(screen.getByRole("button", { name: "app" })); // expanded row has the full value and image ID
    expect(screen.getByText(CHECKSUM)).toBeTruthy();
    expect(screen.getByText(`repo/web@sha256:${CHECKSUM}`)).toBeTruthy();
  });

  it("expands a ConfigMap volume to its keys, values, and in-container file paths", () => {
    setup();

    fireEvent.click(screen.getByRole("tab", { name: "Volumes (2)" }));
    expect(screen.getByText("app:/etc/app")).toBeTruthy(); // mounted-at column
    fireEvent.click(screen.getByRole("button", { name: "config" }));

    expect(aksApi.useConfigMapDetail).toHaveBeenCalledWith(CLUSTER_ID, "apps", "web-config");
    expect(screen.getByText("0644 (420)")).toBeTruthy();
    expect(screen.getByText("app:/etc/app/application.properties")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /application\.properties/ }));
    expect(screen.getByText("server.port=8080")).toBeTruthy();
  });

  it("lists Secret keys without revealing values", () => {
    setup();

    fireEvent.click(screen.getByRole("tab", { name: "Volumes (2)" }));
    fireEvent.click(screen.getByRole("button", { name: "creds" }));

    expect(aksApi.useSecretDetail).toHaveBeenCalledWith(CLUSTER_ID, "apps", "aaf-cred", false, true);
    expect(screen.getByText("app:/opt/att/aaf/user.txt")).toBeTruthy();
    expect(screen.getByText("not projected (not listed in items)")).toBeTruthy(); // "password"
    expect(screen.queryByText("********")).toBeNull();
  });

  it("jumps from a container mount to that volume's details", () => {
    setup();

    fireEvent.click(screen.getByRole("tab", { name: "Containers (2)" }));
    fireEvent.click(screen.getByRole("button", { name: "app" })); // mounts are listed in the expanded row
    fireEvent.click(screen.getAllByTitle("View volume details")[0]); // app's /etc/app ← config

    expect(screen.getByRole("button", { name: "config" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("app:/etc/app/application.properties")).toBeTruthy();
  });

  it("opens the log viewer with every container, init containers included", () => {
    const { onViewLogs } = setup();

    fireEvent.click(screen.getByRole("button", { name: /View logs/ }));

    expect(onViewLogs).toHaveBeenCalledWith(expect.objectContaining({ pod_name: "web-7b9c-a", containers: ["init-db", "app"] }));
  });
});

describe("volume helpers", () => {
  const mounts = [
    { container: "app", mount_path: "/etc/app/", read_only: true, sub_path: null },
    { container: "sidecar", mount_path: "/config/log4j2.xml", read_only: true, sub_path: "log4j2.xml" },
  ];

  it("maps each key to the file it becomes in every mounting container", () => {
    expect(projectedFilePaths("log4j2.xml", undefined, mounts)).toEqual([
      "app:/etc/app/log4j2.xml",
      "sidecar:/config/log4j2.xml", // subPath mounts the single file at mountPath
    ]);
    expect(projectedFilePaths("other.yaml", undefined, mounts)).toEqual(["app:/etc/app/other.yaml"]);
  });

  it("honours items remapping and drops unlisted keys", () => {
    const items = [{ key: "log4j2.xml", path: "conf/log4j2.xml" }];
    expect(projectedFilePaths("log4j2.xml", items, mounts)).toEqual(["app:/etc/app/conf/log4j2.xml"]);
    expect(projectedFilePaths("other.yaml", items, mounts)).toEqual([]);
  });

  it("flattens nested specs and shows file modes in octal", () => {
    expect(flattenSpec({ driver: "file.csi.azure.com", volumeAttributes: { shareName: "logs" }, items: [{ key: "a", mode: 384 }], defaultMode: 420 })).toEqual([
      ["driver", "file.csi.azure.com"],
      ["volumeAttributes.shareName", "logs"],
      ["items[0].key", "a"],
      ["items[0].mode", "0600 (384)"],
      ["defaultMode", "0644 (420)"],
    ]);
  });
});
