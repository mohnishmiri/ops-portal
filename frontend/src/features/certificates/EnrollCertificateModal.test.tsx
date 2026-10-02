/**
 * Tests for the Keyfactor-matching EnrollCertificateModal.
 *
 * Validates the pattern-driven form: required enrollment pattern, owner and
 * Keyfactor-defined metadata, CSR mode, and collection-scoped submission.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const idle = () => ({ mutateAsync: vi.fn(), isPending: false });

vi.mock("../../services/certificatesApi", () => ({
  useEnrollCertificate: vi.fn(),
  useLoadCertificateToAkv: vi.fn(() => idle()),
  useEnrollmentProfiles: vi.fn(() => ({ data: [] })),
  useCreateEnrollmentProfile: vi.fn(() => idle()),
  useUpdateEnrollmentProfile: vi.fn(() => idle()),
  useDeleteEnrollmentProfile: vi.fn(() => idle()),
  useEnrollmentPatterns: vi.fn(() => ({
    isLoading: false,
    data: [
      {
        id: 28,
        name: "Digicert-Standard-SHA2-4096Key",
        template_name: "Digicert-Standard-SHA2-4096Key",
        source: "configured",
        group: "att-ad.local",
        key_algorithms: [{ name: "RSA", key_sizes: [4096], curves: [] }],
        certificate_authorities: ["DigicertEP"],
      },
    ],
  })),
  useMetadataFields: vi.fn(() => ({
    isLoading: false,
    data: [
      { name: "MOTS-Profile-ID", data_type: "string", options: [], hint: "", validation: "", default_value: "", required: true },
      {
        name: "Environment",
        data_type: "choice",
        options: ["PROD", "NPRD"],
        hint: "",
        validation: "",
        default_value: "",
        required: true,
      },
    ],
  })),
  certificateErrorMessage: (err: unknown, fallback = "Operation failed") => {
    const detail = (err as any)?.response?.data?.detail;
    return typeof detail === "string" ? detail : fallback;
  },
}));

import * as certApi from "../../services/certificatesApi";
import { EnrollCertificateModal } from "./EnrollCertificateModal";

function setup(collectionId?: number) {
  const mutateAsync = vi.fn().mockResolvedValue({ thumbprint: "ABC", serial_number: "01" });
  vi.mocked(certApi.useEnrollCertificate).mockReturnValue({ mutateAsync, isPending: false } as any);
  const onSuccess = vi.fn();
  const onError = vi.fn();
  render(
    <EnrollCertificateModal collectionId={collectionId} onClose={vi.fn()} onSuccess={onSuccess} onError={onError} />,
  );
  return { onSuccess, onError, mutateAsync };
}

describe("EnrollCertificateModal validation", () => {
  it("requires an enrollment pattern, owner, common name and Keyfactor metadata", async () => {
    const { mutateAsync } = setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ENROLL" }));
    });
    expect(screen.getByText(/Enrollment Pattern is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Owner Role Name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Common Name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/MOTS-Profile-ID is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Environment is required/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("shows CSR validation when in CSR mode", async () => {
    const { mutateAsync } = setup();
    fireEvent.click(screen.getByRole("button", { name: "CSR Enrollment" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ENROLL" }));
    });
    expect(screen.getByText(/CSR is required/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("submits the pattern, metadata and selected collection", async () => {
    const { mutateAsync } = setup(2573);
    fireEvent.click(screen.getByRole("button", { name: "CSR Enrollment" }));
    const selects = screen.getAllByRole("combobox");
    // First combobox is the saved-profile picker; the pattern dropdown follows it.
    fireEvent.change(selects[1], { target: { value: "28" } });
    fireEvent.change(screen.getByPlaceholderText("e.g. AP-KF-ATTCC-31599"), { target: { value: "AP-KF-ATTCC-31599" } });
    fireEvent.change(screen.getByPlaceholderText("-----BEGIN CERTIFICATE REQUEST-----"), { target: { value: "csr" } });
    const textboxes = screen.getAllByRole("textbox");
    fireEvent.change(textboxes[textboxes.length - 1], { target: { value: "12345" } });
    const comboboxes = screen.getAllByRole("combobox");
    fireEvent.change(comboboxes[comboboxes.length - 1], { target: { value: "NPRD" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ENROLL" }));
    });

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.enrollment_pattern_id).toBe(28);
    expect(payload.collection_id).toBe(2573);
    expect(payload.certificate_authority).toBe("");
    expect(payload.metadata).toEqual({ "MOTS-Profile-ID": "12345", Environment: "NPRD" });
  });
});
