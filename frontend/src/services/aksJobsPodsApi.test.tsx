/**
 * Tests for the pod-delete and job APIs.
 *
 * Two things matter here beyond "it calls the endpoint":
 *  • the pod/job name is URL-encoded, so names with awkward characters do not
 *    silently target the wrong resource
 *  • the grid queries are invalidated on success, which is what lets the UI
 *    refresh without the user reloading the browser
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// vi.hoisted, because vi.mock is lifted above ordinary top-level consts.
const { del, get } = vi.hoisted(() => ({ del: vi.fn(), get: vi.fn() }));

vi.mock("./apiClient", () => ({
  default: {
    get,
    delete: del,
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import { deleteJob, deletePod, fetchJobPods, useDeleteJob, useDeletePod } from "./aksApi";

const CLUSTER_ID =
  "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-01";

function wrapper(queryClient: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function newClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("deletePod", () => {
  it("targets the namespaced pod path with the cluster as a query param", async () => {
    del.mockResolvedValue({ data: { success: true } });

    await deletePod(CLUSTER_ID, "com-att-prod", "application-7d8f9c8b9-x2abc");

    const [url, config] = del.mock.calls[0];
    expect(url).toBe("/aks/pods/com-att-prod/application-7d8f9c8b9-x2abc");
    expect(config.params.get("cluster_id")).toBe(CLUSTER_ID);
  });

  it("URL-encodes namespace and pod name", async () => {
    del.mockResolvedValue({ data: { success: true } });

    await deletePod(CLUSTER_ID, "ns/weird", "pod name");

    expect(del.mock.calls[0][0]).toBe("/aks/pods/ns%2Fweird/pod%20name");
  });
});

describe("useDeletePod", () => {
  it("invalidates the pod grid so the UI refreshes without a reload", async () => {
    del.mockResolvedValue({ data: { success: true, will_be_recreated: true } });
    const queryClient = newClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useDeletePod(), { wrapper: wrapper(queryClient) });

    await act(async () => {
      await result.current.mutateAsync({
        clusterId: CLUSTER_ID,
        namespace: "com-att-prod",
        podName: "p1",
      });
    });

    const invalidatedKeys = invalidate.mock.calls.map((c) => (c[0] as any).queryKey[0]);
    expect(invalidatedKeys).toContain("aks-pod-metrics");
    expect(invalidatedKeys).toContain("aks-audit-history");
  });

  it("does not invalidate when the delete fails", async () => {
    del.mockRejectedValue({ response: { data: { detail: "nope" } } });
    const queryClient = newClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useDeletePod(), { wrapper: wrapper(queryClient) });

    await act(async () => {
      await result.current
        .mutateAsync({ clusterId: CLUSTER_ID, namespace: "n", podName: "p" })
        .catch(() => undefined);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("deleteJob", () => {
  it("defaults to Background propagation", async () => {
    del.mockResolvedValue({ data: { success: true } });

    await deleteJob(CLUSTER_ID, "com-att-prod", "report-job");

    const [url, config] = del.mock.calls[0];
    expect(url).toBe("/aks/jobs/com-att-prod/report-job");
    expect(config.params.get("propagation_policy")).toBe("Background");
  });

  it("passes Orphan through when pods should be retained", async () => {
    del.mockResolvedValue({ data: { success: true } });

    await deleteJob(CLUSTER_ID, "com-att-prod", "report-job", "Orphan");

    expect(del.mock.calls[0][1].params.get("propagation_policy")).toBe("Orphan");
  });
});

describe("useDeleteJob", () => {
  it("invalidates jobs, job detail, and pods on success", async () => {
    del.mockResolvedValue({ data: { success: true } });
    const queryClient = newClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useDeleteJob(), { wrapper: wrapper(queryClient) });

    await act(async () => {
      await result.current.mutateAsync({
        clusterId: CLUSTER_ID,
        namespace: "com-att-prod",
        jobName: "report-job",
      });
    });

    const invalidatedKeys = invalidate.mock.calls.map((c) => (c[0] as any).queryKey[0]);
    expect(invalidatedKeys).toContain("aks-jobs");
    expect(invalidatedKeys).toContain("aks-job-detail");
    // A deleted Job's pods go with it, so the pod grid is stale too.
    expect(invalidatedKeys).toContain("aks-pod-metrics");
  });
});

describe("fetchJobPods", () => {
  it("requests the job's pods by namespace and name", async () => {
    get.mockResolvedValue({ data: { pods: [], count: 0 } });

    await fetchJobPods(CLUSTER_ID, "com-att-prod", "report-job");

    const [url, config] = get.mock.calls[0];
    expect(url).toBe("/aks/jobs/com-att-prod/report-job/pods");
    expect(config.params.get("cluster_id")).toBe(CLUSTER_ID);
  });
});
