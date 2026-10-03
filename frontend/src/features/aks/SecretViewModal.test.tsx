/**
 * Opening a Kubernetes Secret only asks the API for plaintext values when the
 * user may reveal them; everyone else sees the keys with masked values.
 */

import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useSecretDetail: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { SecretViewModal } from "./K8sResourceModals";

beforeEach(() => {
  vi.clearAllMocks();
});

function renderModal(canReveal: boolean, values: Record<string, string>) {
  (aksApi.useSecretDetail as any).mockReturnValue({
    data: { name: "db-creds", namespace: "apps", type: "Opaque", keys: Object.keys(values), data: values },
    isLoading: false,
    isError: false,
  });
  render(<SecretViewModal clusterId="c1" namespace="apps" name="db-creds" canReveal={canReveal} onClose={vi.fn()} />);
}

describe("SecretViewModal", () => {
  it("does not request plaintext for a user who may not reveal values", () => {
    renderModal(false, { password: "***" });

    expect(aksApi.useSecretDetail).toHaveBeenCalledWith("c1", "apps", "db-creds", false, true);
    expect(screen.getByText("password")).toBeTruthy();
    expect(screen.getByText(/Values are hidden/)).toBeTruthy();
  });

  it("requests plaintext for a user who may reveal values", () => {
    renderModal(true, { password: "s3cret" });

    expect(aksApi.useSecretDetail).toHaveBeenCalledWith("c1", "apps", "db-creds", true, true);
    expect(screen.getByText("s3cret")).toBeTruthy();
    expect(screen.queryByText(/Values are hidden/)).toBeNull();
  });
});
