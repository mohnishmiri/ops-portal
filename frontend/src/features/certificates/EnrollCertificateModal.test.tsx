/**
 * Tests for the Keyfactor-matching EnrollCertificateModal.
 *
 * Validates that the PFX form shows validation errors for required AT&T
 * metadata fields and that switching to CSR mode requires a CSR.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/certificatesApi", () => ({
  useEnrollCertificate: vi.fn(),
  useTemplates: vi.fn(() => ({ data: [] })),
  useAuthorities: vi.fn(() => ({ data: [] })),
  certificateErrorMessage: (err: unknown, fallback = "Operation failed") => {
    const detail = (err as any)?.response?.data?.detail;
    return typeof detail === "string" ? detail : fallback;
  },
}));

import * as certApi from "../../services/certificatesApi";
import { EnrollCertificateModal } from "./EnrollCertificateModal";

function setup() {
  const mutateAsync = vi.fn().mockResolvedValue({ thumbprint: "ABC", serial_number: "01" });
  vi.mocked(certApi.useEnrollCertificate).mockReturnValue({ mutateAsync, isPending: false } as any);
  const onSuccess = vi.fn();
  const onError = vi.fn();
  render(<EnrollCertificateModal onClose={vi.fn()} onSuccess={onSuccess} onError={onError} />);
  return { onSuccess, onError, mutateAsync };
}

describe("EnrollCertificateModal validation", () => {
  it("shows validation errors for PFX mode when required fields are empty", async () => {
    const { mutateAsync } = setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ENROLL" }));
    });
    // PFX-specific required fields
    expect(screen.getByText(/Template is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Certificate Authority is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Common Name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/MOTS-Profile-ID is required/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("shows CSR validation when in CSR mode", async () => {
    const { mutateAsync } = setup();
    // Switch to CSR mode
    fireEvent.click(screen.getByRole("button", { name: "CSR Enrollment" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ENROLL" }));
    });
    expect(screen.getByText(/CSR is required/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("does not submit PFX without all AT&T metadata fields", async () => {
    const { mutateAsync } = setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ENROLL" }));
    });
    expect(screen.getByText(/Requester ATT User ID is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Manager ATT User ID is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Server Type is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Environment is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Port is required/i)).toBeInTheDocument();
    expect(screen.getByText(/PCI Data is required/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
