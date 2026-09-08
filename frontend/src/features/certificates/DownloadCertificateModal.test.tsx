/**
 * Tests for DownloadCertificateModal format availability.
 *
 * PFX must be offered whenever the backend can reach a private key — including
 * an escrowed one, which is the only source left for certificates Keyfactor
 * never archived.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";

vi.mock("../../services/certificatesApi", () => ({
  useDownloadCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  DOWNLOAD_FORMATS: ["PEM", "CER", "CRT", "DER", "P7B", "PFX"],
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
