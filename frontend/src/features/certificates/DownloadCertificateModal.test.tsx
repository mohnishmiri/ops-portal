/**
 * Tests for DownloadCertificateModal format handling.
 *
 * The keystore formats (PFX and JKS) must be offered whenever the backend can
 * reach a private key — including an escrowed one, which is the only source
 * left for certificates Keyfactor never archived — and must stay behind the
 * WRITE role and a keystore password.
 */

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";

vi.mock("../../services/certificatesApi", () => ({
  useDownloadCertificate: vi.fn(),
  DOWNLOAD_FORMATS: ["PEM", "CER", "CRT", "DER", "P7B", "PFX", "JKS"],
  KEYSTORE_FORMATS: ["PFX", "JKS"],
  certificateErrorMessage: (_err: unknown, fallback = "Download failed") => fallback,
}));

import * as certApi from "../../services/certificatesApi";
import { DownloadCertificateModal } from "./DownloadCertificateModal";

const CERT = {
  id: 31097770,
  common_name: "cesdataroutergears.dev.att.com",
  thumbprint: "7C7ADA424978D8904259E2F86E39B186E3FEBBBF",
} as unknown as certApi.Certificate;

function setup(overrides: Partial<certApi.Certificate> = {}, canWrite = true) {
  const mutateAsync = vi.fn().mockResolvedValue(new Blob(["keystore"]));
  vi.mocked(certApi.useDownloadCertificate).mockReturnValue({
    mutateAsync,
    isPending: false,
  } as any);
  render(
    <DownloadCertificateModal
      certificate={{ ...CERT, ...overrides }}
      collectionId={2573}
      canWrite={canWrite}
      onClose={vi.fn()}
      onSuccess={vi.fn()}
      onError={vi.fn()}
    />
  );
  return mutateAsync;
}

const formatOptions = () =>
  Array.from(screen.getByLabelText(/File Format/i).querySelectorAll("option")).map(
    (o) => (o as HTMLOptionElement).value
  );

beforeEach(() => vi.clearAllMocks());

describe("DownloadCertificateModal PFX availability", () => {
  it("offers PFX for an escrowed certificate Keyfactor cannot export", () => {
    // has_private_key=false previously hid PFX outright, leaving no way to get
    // the key even though escrow holds it.
    setup({ key_escrowed: true, has_private_key: false });
    expect(formatOptions()).toContain("PFX");
    expect(screen.queryByText(/PFX format is not available/i)).not.toBeInTheDocument();
  });

  it("explains that the typed password protects the escrowed key", () => {
    setup({ key_escrowed: true, has_private_key: false });
    fireEvent.change(screen.getByLabelText(/File Format/i), { target: { value: "PFX" } });
    expect(screen.getByText(/re-protected with this password/i)).toBeInTheDocument();
  });

  it("still offers PFX when Keyfactor holds an exportable key", () => {
    setup({ key_escrowed: false, has_private_key: true });
    expect(formatOptions()).toContain("PFX");
  });

  it("hides PFX and points at renewal when no key is reachable", () => {
    setup({ key_escrowed: false, has_private_key: false });
    expect(formatOptions()).not.toContain("PFX");
    expect(screen.getByText(/Renewing it through the portal escrows the key/i)).toBeInTheDocument();
  });

  it("keeps PFX behind the WRITE role even when escrowed", () => {
    setup({ key_escrowed: true, has_private_key: false }, false);
    expect(formatOptions()).not.toContain("PFX");
  });

  it("requires a 12-character password before download is enabled", () => {
    setup({ key_escrowed: true });
    fireEvent.change(screen.getByLabelText(/File Format/i), { target: { value: "PFX" } });
    const button = screen.getByRole("button", { name: "DOWNLOAD" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "short" } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "download-password" } });
    expect(button).toBeEnabled();
  });
});

describe("DownloadCertificateModal JKS format", () => {
  const selectJks = () =>
    fireEvent.change(screen.getByLabelText(/File Format/i), { target: { value: "JKS" } });

  it("offers JKS alongside the other formats", () => {
    setup({ has_private_key: true });
    expect(formatOptions()).toContain("JKS");
  });

  it("gates JKS behind the WRITE role and a reachable key", () => {
    setup({ has_private_key: true }, false);
    expect(formatOptions()).not.toContain("JKS");

    cleanup();
    setup({ key_escrowed: false, has_private_key: false });
    expect(formatOptions()).not.toContain("JKS");
  });

  it("offers JKS for an escrowed certificate Keyfactor cannot export", () => {
    setup({ key_escrowed: true, has_private_key: false });
    expect(formatOptions()).toContain("JKS");
  });

  it("requires a keystore password before download is enabled", () => {
    setup({ has_private_key: true });
    selectJks();
    const button = screen.getByRole("button", { name: "DOWNLOAD" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Keystore Password/i), { target: { value: "short" } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Keystore Password/i), {
      target: { value: "keystore-password" },
    });
    expect(button).toBeEnabled();
  });

  it("submits the keystore password and keeps the chain", async () => {
    // A JKS entry carries its issuing chain, unlike a bare PFX download.
    const mutateAsync = setup({ has_private_key: true });
    selectJks();
    fireEvent.change(screen.getByLabelText(/Keystore Password/i), {
      target: { value: "keystore-password" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "DOWNLOAD" }));
    });
    const sent = mutateAsync.mock.calls[0][0].data;
    expect(sent.file_format).toBe("JKS");
    expect(sent.pfx_password).toBe("keystore-password");
    expect(sent.include_chain).toBe(true);
    expect(sent.jks_alias).toBeUndefined();
  });

  it("passes an alias override through trimmed", async () => {
    const mutateAsync = setup({ has_private_key: true });
    selectJks();
    fireEvent.change(screen.getByLabelText(/Keystore Password/i), {
      target: { value: "keystore-password" },
    });
    fireEvent.change(screen.getByLabelText(/Entry Alias/i), {
      target: { value: "  Tomcat-TLS  " },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "DOWNLOAD" }));
    });
    expect(mutateAsync.mock.calls[0][0].data.jks_alias).toBe("Tomcat-TLS");
  });

  it("hides the chain-order choice, which JKS fixes at leaf-first", () => {
    setup({ has_private_key: true });
    expect(screen.getByText(/Chain Order/i)).toBeInTheDocument();
    selectJks();
    expect(screen.queryByText(/Chain Order/i)).not.toBeInTheDocument();
  });

  it("does not offer the alias field for PFX", () => {
    setup({ has_private_key: true });
    fireEvent.change(screen.getByLabelText(/File Format/i), { target: { value: "PFX" } });
    expect(screen.queryByLabelText(/Entry Alias/i)).not.toBeInTheDocument();
  });
});
