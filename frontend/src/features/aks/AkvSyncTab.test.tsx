/**
 * AKV Sync grid actions: view/delete icons gated by capability, and the delete
 * confirmation (keep or remove the synced output, Helm-managed warning).
 */

import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../hooks/useAksLiveWatch", () => ({ useAksLiveWatch: vi.fn() }));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useCachedAkvs: vi.fn(),
  useAkvsController: vi.fn(() => ({ data: undefined })),
  useAksBackgroundSync: vi.fn(() => ({ isRunning: false, start: vi.fn() })),
  useAkvsDetail: vi.fn(() => ({ data: undefined, isLoading: true, isError: false })),
  useAkvsVaultCheck: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteAkvs: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { AkvSyncTab } from "./AkvSyncTab";

const CLUSTER = { id: "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-01", name: "aks-01" } as any;

function akvs(overrides: Partial<aksApi.AkvsItem> = {}): aksApi.AkvsItem {
  return {
    name: "agent-llm-base-url-sync",
    namespace: "opsportal",
    vault_name: "attcc-eastus2-stge-kv",
    object_name: "opsportal-backend-agent-llm-base-url",
    object_type: "secret",
    object_version: null,
    content_type: null,
    output_kind: "secret",
    output_name: "ops-portal-backend-agent-llm-base-url",
    output_data_key: "AGENT_LLM_BASE_URL",
    output_type: "Opaque",
    transforms: [],
    output_exists: true,
    key_present: true,
    secret_hash: null,
    last_azure_update: "2026-10-03T22:00:00Z",
    last_event: null,
    labels: {},
    created_at: null,
    status: "Synced",
    status_reason: "",
    ...overrides,
  };
}

const mutate = vi.fn();

function setup(items: aksApi.AkvsItem[], canDelete: boolean) {
  (aksApi.useCachedAkvs as any).mockReturnValue({
    data: { source: "db", last_sync: "2026-10-04T00:00:00Z", items, count: items.length, summary: { total: items.length } },
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  });
  (aksApi.useDeleteAkvs as any).mockReturnValue({ mutate, isPending: false });
  render(
    <AkvSyncTab
      cluster={CLUSTER}
      namespace=""
      namespaces={["opsportal"]}
      onNamespaceChange={vi.fn()}
      showToast={vi.fn()}
      formatDate={(v) => v}
      canDelete={canDelete}
    />
  );
}

describe("AkvSyncTab actions", () => {
  beforeEach(() => mutate.mockReset());

  it("shows only the view action to read-only users", () => {
    setup([akvs()], false);

    expect(screen.queryByTitle("Delete AzureKeyVaultSecret")).toBeNull();
    fireEvent.click(screen.getByTitle("View Details"));
    expect(aksApi.useAkvsDetail).toHaveBeenLastCalledWith(CLUSTER.id, "opsportal", "agent-llm-base-url-sync");
  });

  it("deletes and can keep the synced output Secret", () => {
    setup([akvs()], true);

    fireEvent.click(screen.getByTitle("Delete AzureKeyVaultSecret"));
    expect(screen.getByText(/Pods that read this Secret will fail to start/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Synced Secret/), { target: { value: "keep" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({
      clusterId: CLUSTER.id,
      namespace: "opsportal",
      name: "agent-llm-base-url-sync",
      keepOutput: true,
    });
  });

  it("warns that Helm recreates a chart-managed object, and skips the output choice when there is none", () => {
    setup([akvs({ status: "Failed", output_exists: false, labels: { "app.kubernetes.io/managed-by": "Helm" } })], true);

    fireEvent.click(screen.getByTitle("Delete AzureKeyVaultSecret"));

    expect(screen.getByText(/does not exist, so nothing else is removed/)).toBeTruthy();
    expect(screen.getByText(/managed by Helm/)).toBeTruthy();
    expect(screen.queryByLabelText(/Synced Secret/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(mutate.mock.calls[0][0].keepOutput).toBe(false);
  });
});
