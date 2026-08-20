/**
 * Tests for DeleteCertificateModal — delete is blocked until the confirmation
 * word is typed (negative test for a destructive operation).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/certificatesApi", () => ({
  useDeleteCertificate: vi.fn(),
  certificateErrorMessage: (err: unknown, fallback = "Operation failed") => {
    const detail = (err as any)?.response?.data?.detail;
    return typeof detail === "string" ? detail : fallback;
  },
}));

import * as certApi from "../../services/certificatesApi";
import { DeleteCertificateModal } from "./DeleteCertificateModal";

const CERT: certApi.Certificate = {
  id: 7,
  common_name: "gone.example.com",
  subject_dn: "",
  issuer_dn: "",
  serial_number: "",
  thumbprint: "",
  template: "",
  certificate_authority: "",
  not_before: null,
  not_after: null,
  sans: [],
  revoked: false,
  revocation_reason: null,
  status: "valid",
  metadata: {},
  import_date: null,
  effective_date: null,
  san_count: 0,
  key_algorithm: "RSA",
  key_size: 4096,
  key_usage: "",
  extended_key_usage: "",
  signing_algorithm: "",
  requester: "",
  principal_name: "",
  locations: [],
  location_count: 0,
  collection: "",
};

function setupMock() {
  const mutateAsync = vi.fn().mockResolvedValue({ certificate_id: 7, deleted: true });
  vi.mocked(certApi.useDeleteCertificate).mockReturnValue({ mutateAsync, isPending: false } as any);
  return mutateAsync;
}

describe("DeleteCertificateModal confirmation guard", () => {
  it("keeps delete disabled until DELETE is typed", () => {
    setupMock();
    render(
      <DeleteCertificateModal certificate={CERT} onClose={vi.fn()} onSuccess={vi.fn()} onError={vi.fn()} />
    );
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type DELETE to confirm/i), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("submits once confirmed", async () => {
    const mutateAsync = setupMock();
    const onSuccess = vi.fn();
    render(
      <DeleteCertificateModal certificate={CERT} onClose={vi.fn()} onSuccess={onSuccess} onError={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText(/Type DELETE to confirm/i), { target: { value: "DELETE" } });
    const deleteBtn = screen.getByRole("button", { name: "Delete" });
    expect(deleteBtn).toBeEnabled();
    await act(async () => {
      fireEvent.click(deleteBtn);
    });
    expect(mutateAsync).toHaveBeenCalledWith({
      id: 7,
      collectionId: undefined,
      notAfter: null,
      revoked: false,
    });
    expect(onSuccess).toHaveBeenCalled();
  });
});
