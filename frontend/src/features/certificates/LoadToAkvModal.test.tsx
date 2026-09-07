/**
 * Tests for the Load to AKV key-source selection.
 *
 * The escrowed key is the only source that survives past issuance, so it must
 * be offered and preferred whenever it exists — that is what allows the same
 * certificate to be loaded into a second environment's Key Vault.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";

vi.mock("../../services/certificatesApi", () => ({
  useLoadCertificateToAkv: vi.fn(),
  useRenewCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  certificateErrorMessage: (_err: unknown, fallback = "Operation failed") => fallback,
}));

vi.mock("./AkvTargetPicker", () => ({
  AkvTargetPicker: () => <div data-testid="akv-target-picker" />,
  isAkvTargetComplete: () => true,
}));

import * as certApi from "../../services/certificatesApi";
import { LoadToAkvModal } from "./LoadToAkvModal";

const CERT = {
  id: 7,
  common_name: "cesdataroutergears.dev.att.com",
  thumbprint: "3E49931A64AE04D987533E0DD1C237BDA701DA2C",
  certificate_authority: "ca",
  template: "WebServer",
  key_size: 4096,
  sans: [],
} as unknown as certApi.Certificate;

function setup(certOverrides: Partial<certApi.Certificate> = {}) {
  const mutateAsync = vi.fn().mockResolvedValue({
    status: "success",
    vault_name: "attcc-eastus2-uat-kv",
    certificates: [{ certificate_name: "cesdataroutergearsuat-stage-att-com", akv_id: "", enabled: true }],
    failed: [],
    key_source: "escrow",
  });
  vi.mocked(certApi.useLoadCertificateToAkv).mockReturnValue({ mutateAsync, isPending: false } as any);
  render(
    <LoadToAkvModal
      certificate={{ ...CERT, ...certOverrides }}
      collectionId={42}
      onClose={vi.fn()}
      onSuccess={vi.fn()}
      onError={vi.fn()}
    />
  );
  return mutateAsync;
}

beforeEach(() => vi.clearAllMocks());

describe("LoadToAkvModal key source", () => {
  it("offers and preselects the escrowed key when one exists", () => {
    setup({ key_escrowed: true, has_private_key: false });
    const escrow = screen.getByRole("radio", { name: /Use escrowed key/i });
    expect(escrow).toBeChecked();
    // The "no exportable key" warning must not fire when escrow covers it.
    expect(screen.queryByText(/cannot be\s+exported as a PFX/i)).not.toBeInTheDocument();
  });

  it("sends key_source=escrow so the backend never silently falls back", async () => {
    const mutateAsync = setup({ key_escrowed: true });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load to AKV" }));
    });
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 7,
        data: expect.objectContaining({ key_source: "escrow", collection_id: 42 }),
      })
    );
    // No PFX is attached — the backend reads the escrowed material itself.
    expect(mutateAsync.mock.calls[0][0].data.certificate_data).toBeUndefined();
  });

  it("reports which key source was used", async () => {
    setup({ key_escrowed: true });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load to AKV" }));
    });
    expect(screen.getByText(/Escrowed key — loadable into further vaults/i)).toBeInTheDocument();
  });

  it("falls back to a Keyfactor export when nothing is escrowed", async () => {
    const mutateAsync = setup({ key_escrowed: false, has_private_key: true });
    expect(screen.queryByRole("radio", { name: /Use escrowed key/i })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Use existing certificate/i })).toBeChecked();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load to AKV" }));
    });
    expect(mutateAsync.mock.calls[0][0].data.key_source).toBe("keyfactor");
  });

  it("warns and switches to generation when there is no key at all", () => {
    setup({ key_escrowed: false, has_private_key: false });
    expect(screen.getByRole("radio", { name: /Generate new certificate with PFX/i })).toBeChecked();
    expect(screen.getByText(/No escrowed key for this certificate/i)).toBeInTheDocument();
  });
});
