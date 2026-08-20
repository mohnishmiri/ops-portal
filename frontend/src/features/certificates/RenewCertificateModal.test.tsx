import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import React from "react";

vi.mock("../../services/certificatesApi", () => ({
  useRenewCertificate: vi.fn(),
  certificateErrorMessage: (_err: unknown, fallback = "Operation failed") => fallback,
}));

import * as certApi from "../../services/certificatesApi";
import { RenewCertificateModal } from "./RenewCertificateModal";

const CERT = {
  id: 7,
  common_name: "app.example.com",
  certificate_authority: "ca",
  template: "template",
} as certApi.Certificate;

function setup() {
  const mutateAsync = vi.fn().mockResolvedValue({ thumbprint: "NEW" });
  vi.mocked(certApi.useRenewCertificate).mockReturnValue({ mutateAsync, isPending: false } as any);
  render(
    <RenewCertificateModal
      certificate={CERT}
      collectionId={42}
      onClose={vi.fn()}
      onSuccess={vi.fn()}
      onError={vi.fn()}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "CONFIGURE WITH PFX" }));
  return mutateAsync;
}

describe("RenewCertificateModal PFX password validation", () => {
  it("keeps renewal disabled for blank and short passwords", () => {
    setup();
    const renewButton = screen.getByRole("button", { name: "Renew" });
    const password = screen.getByLabelText(/Password \(min 12 chars\)/i);
    expect(renewButton).toBeDisabled();
    fireEvent.change(password, { target: { value: "            " } });
    expect(renewButton).toBeDisabled();
    fireEvent.change(password, { target: { value: "short" } });
    expect(renewButton).toBeDisabled();
  });

  it("submits a valid PFX renewal with collection context", async () => {
    const mutateAsync = setup();
    fireEvent.change(screen.getByLabelText(/Password \(min 12 chars\)/i), {
      target: { value: "validpassword" },
    });
    fireEvent.change(screen.getByLabelText(/Owner Role Name/i), {
      target: { value: "Certificate Owners" },
    });
    const renewButton = screen.getByRole("button", { name: "Renew" });
    expect(renewButton).toBeEnabled();
    await act(async () => {
      fireEvent.click(renewButton);
    });
    expect(mutateAsync).toHaveBeenCalledWith({
      id: 7,
      data: {
        mode: "pfx",
        certificate_authority: "ca",
        template: "template",
        collection_id: 42,
        password: "validpassword",
        key_type: "RSA",
        key_length: 4096,
        owner_role_name: "Certificate Owners",
      },
    });
  });
});