/**
 * Tests for RevokeCertificateModal — the destructive revoke action must be
 * blocked until the user types the confirmation word, and it submits with the
 * selected RFC 5280 reason.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/certificatesApi", () => ({
  useRevokeCertificate: vi.fn(),
  REVOCATION_REASONS: [
    "unspecified", "keyCompromise", "caCompromise", "affiliationChanged",
    "superseded", "cessationOfOperation", "certificateHold", "removeFromCRL",
    "privilegeWithdrawn", "aaCompromise",
  ],
  certificateErrorMessage: (err: unknown, fallback = "Operation failed") => {
    const detail = (err as any)?.response?.data?.detail;
    return typeof detail === "string" ? detail : fallback;
  },
}));

import * as certApi from "../../services/certificatesApi";
import { RevokeCertificateModal } from "./RevokeCertificateModal";

const CERT: certApi.Certificate = {
  id: 42,
  common_name: "app.example.com",
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

function setup() {
  const mutateAsync = vi.fn().mockResolvedValue({ certificate_id: 42, reason: "keyCompromise", revoked: true });
  vi.mocked(certApi.useRevokeCertificate).mockReturnValue({ mutateAsync, isPending: false } as any);
  const onSuccess = vi.fn();
  const onError = vi.fn();
  const onClose = vi.fn();
  render(
    <RevokeCertificateModal certificate={CERT} onClose={onClose} onSuccess={onSuccess} onError={onError} />
  );
  return { onSuccess, onError, onClose, mutateAsync };
}

describe("RevokeCertificateModal confirmation guard", () => {
  it("disables the revoke button until confirmation is typed", () => {
    setup();
    const revokeBtn = screen.getByRole("button", { name: "Revoke" });
    expect(revokeBtn).toBeDisabled();
  });

  it("does not submit when confirmation text is wrong", () => {
    const { mutateAsync } = setup();
    fireEvent.change(screen.getByLabelText(/Type REVOKE to confirm/i), {
      target: { value: "nope" },
    });
    const revokeBtn = screen.getByRole("button", { name: "Revoke" });
    expect(revokeBtn).toBeDisabled();
    fireEvent.click(revokeBtn);
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("submits with the chosen reason once confirmed", async () => {
    const { onSuccess, mutateAsync } = setup();
    fireEvent.change(screen.getByLabelText(/Revocation Reason/i), {
      target: { value: "keyCompromise" },
    });
    fireEvent.change(screen.getByLabelText(/Type REVOKE to confirm/i), {
      target: { value: "REVOKE" },
    });
    const revokeBtn = screen.getByRole("button", { name: "Revoke" });
    expect(revokeBtn).toBeEnabled();
    await act(async () => {
      fireEvent.click(revokeBtn);
    });
    expect(mutateAsync).toHaveBeenCalledWith({
      id: 42,
      data: { reason: "keyCompromise", comment: "" },
    });
    expect(onSuccess).toHaveBeenCalled();
  });
});
