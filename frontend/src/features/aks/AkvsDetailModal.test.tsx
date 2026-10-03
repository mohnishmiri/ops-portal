/**
 * AzureKeyVaultSecret drill-down: source vs target, the output keys grid
 * (flagging a data key the controller never wrote), and controller events.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useAkvsDetail: vi.fn(),
  useAkvsVaultCheck: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import * as aksApi from "../../services/aksApi";
import { AkvsDetailModal } from "./AkvSyncTab";

const item: aksApi.AkvsDetail = {
  name: "attcc-db-password",
  namespace: "apps",
  vault_name: "kv-attcc-prod",
  object_name: "attcc-db-password",
  object_type: "secret",
  object_version: null,
  content_type: null,
  output_kind: "secret",
  output_name: "attcc-db-credentials",
  output_data_key: "password",
  output_type: "Opaque",
  transforms: [],
  output_exists: true,
  key_present: false,
  secret_hash: "abc123",
  last_azure_update: "2026-10-03T22:00:00Z",
  last_event: null,
  labels: { team: "attcc" },
  created_at: null,
  status: "Degraded",
  status_reason: "Output Secret attcc-db-credentials has no key password.",
  events: [
    { type: "Warning", reason: "ErrAzureVault", message: "Failed to get secret", count: 2, last_seen: "2026-10-03T22:05:00Z" },
    { type: "Normal", reason: "SecretUpdated", message: "secret updated", count: 1, last_seen: "2026-10-03T21:00:00Z" },
  ],
  output_keys: ["username"],
};

function renderModal() {
  (aksApi.useAkvsDetail as any).mockReturnValue({ data: item, isLoading: false, isError: false });
  render(<AkvsDetailModal clusterId="c1" namespace="apps" name={item.name} formatDate={(v) => v} showToast={vi.fn()} onClose={vi.fn()} />);
}

describe("AkvsDetailModal", () => {
  it("shows the Key Vault source next to the Kubernetes target", () => {
    renderModal();

    expect(screen.getByText("Azure Key Vault Source")).toBeTruthy();
    expect(screen.getByText("Kubernetes Target")).toBeTruthy();
    expect(screen.getByText("Output Secret attcc-db-credentials has no key password.")).toBeTruthy();
    expect(screen.getAllByText("kv-attcc-prod").length).toBeGreaterThan(0);
  });

  it("flags the synced data key as missing from the output", () => {
    renderModal();

    fireEvent.click(screen.getByRole("tab", { name: "Output Keys (2)" }));

    expect(screen.getByText("username")).toBeTruthy();
    expect(screen.getByText("Missing from output")).toBeTruthy();
  });

  it("lists controller events with a warning filter", () => {
    renderModal();

    fireEvent.click(screen.getByRole("tab", { name: "Controller Events (2)" }));
    fireEvent.change(screen.getByLabelText("Filter events"), { target: { value: "Warning" } });

    expect(screen.getByText("ErrAzureVault")).toBeTruthy();
    expect(screen.queryByText("SecretUpdated")).toBeNull();
  });
});
