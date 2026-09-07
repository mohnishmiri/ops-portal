/**
 * Tests for CertificatesPage — rendering, loading/empty/error states, and
 * role-based visibility of write and destructive actions.
 *
 * The certificate API hooks and auth/permission contexts are mocked so the
 * component renders deterministically without network or MSAL.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../services/certificatesApi", () => ({
  useCertificates: vi.fn(),
  useCollectionCertStats: vi.fn(() => ({ data: undefined, isLoading: false })),
  useCertificateSyncStatus: vi.fn(() => ({ data: undefined })),
  useCertificateSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useCertificate: vi.fn(() => ({ data: null, isLoading: false, isError: false })),
  useEnrollCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useRenewCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useRevokeCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useUpdateCertificateMetadata: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useDeleteCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useDownloadCertificate: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useCollections: vi.fn(() => ({
    data: [{ id: 42, name: "Test Collection", description: "", certificate_count: 1 }],
  })),
  useTemplates: vi.fn(() => ({ data: [] })),
  useAuthorities: vi.fn(() => ({ data: [] })),
  REVOCATION_REASONS: [
    "unspecified", "keyCompromise", "caCompromise", "affiliationChanged",
    "superseded", "cessationOfOperation", "certificateHold", "removeFromCRL",
    "privilegeWithdrawn", "aaCompromise",
  ],
  DOWNLOAD_FORMATS: ["PEM", "CER", "CRT", "DER", "P7B"],
  STATUS_LABEL: { valid: "Valid", expiring_soon: "Expiring Soon", expired: "Expired", revoked: "Revoked", unknown: "Unknown" },
  certificateErrorMessage: (err: unknown, fallback = "Operation failed") => {
    const detail = (err as any)?.response?.data?.detail;
    return typeof detail === "string" ? detail : fallback;
  },
}));

vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../contexts/PermissionsContext", () => ({ usePermissions: vi.fn() }));

import * as certApi from "../services/certificatesApi";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import CertificatesPage from "./CertificatesPage";

const CERT: certApi.Certificate = {
  id: 1,
  common_name: "app.example.com",
  subject_dn: "CN=app.example.com",
  issuer_dn: "CN=Test CA",
  serial_number: "01",
  thumbprint: "ABC123",
  template: "WebServer",
  certificate_authority: "ca",
  not_before: "2026-01-01T00:00:00+00:00",
  not_after: "2027-01-01T00:00:00+00:00",
  sans: ["app.example.com"],
  revoked: false,
  revocation_reason: null,
  status: "valid",
  metadata: {},
  import_date: null,
  effective_date: null,
  san_count: 1,
  key_algorithm: "RSA",
  key_size: 4096,
  key_usage: "Digital Signature",
  extended_key_usage: "Server Authentication",
  signing_algorithm: "SHA-256withRSA",
  requester: "mz7819",
  principal_name: "",
  locations: [],
  location_count: 0,
  collection: "",
};

function mockList(overrides: Record<string, unknown>, cert: certApi.Certificate = CERT) {
  vi.mocked(certApi.useCertificates).mockReturnValue({
    data: { items: [cert], total: 1, page: 1, page_size: 25 },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
    ...overrides,
  } as any);
}

function setRole(opts: { isAdmin: boolean; canEdit: boolean }) {
  vi.mocked(useAuth).mockReturnValue({ isAdmin: opts.isAdmin } as any);
  vi.mocked(usePermissions).mockReturnValue({ canEditPage: () => opts.canEdit } as any);
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={qc}>
      <CertificatesPage />
    </QueryClientProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: /Test Collection/i }));
  return result;
}

/** Row actions live behind a kebab menu that is portalled onto <body>. */
function openRowActions() {
  fireEvent.click(screen.getByRole("button", { name: /Certificate actions/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CertificatesPage rendering states", () => {
  it("renders certificate rows", () => {
    setRole({ isAdmin: true, canEdit: true });
    mockList({});
    renderPage();
    expect(screen.getByText("app.example.com")).toBeInTheDocument();
    expect(screen.getByText("Valid")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    setRole({ isAdmin: false, canEdit: false });
    mockList({ data: undefined, isLoading: true });
    renderPage();
    expect(screen.getByText(/Loading certificates/i)).toBeInTheDocument();
  });

  it("shows empty state", () => {
    setRole({ isAdmin: false, canEdit: false });
    mockList({ data: { items: [], total: 0, page: 1, page_size: 25 } });
    renderPage();
    expect(screen.getByText(/No certificates found/i)).toBeInTheDocument();
  });

  it("shows error state with retry", () => {
    setRole({ isAdmin: false, canEdit: false });
    mockList({ data: undefined, isError: true, error: new Error("boom") });
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("CertificatesPage role gating", () => {
  it("admin sees enroll, revoke, and delete actions", () => {
    setRole({ isAdmin: true, canEdit: true });
    mockList({});
    renderPage();
    expect(screen.getByRole("button", { name: /Enroll Certificate/i })).toBeInTheDocument();
    openRowActions();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("read-only user cannot see write or destructive actions", () => {
    setRole({ isAdmin: false, canEdit: false });
    mockList({});
    renderPage();
    expect(screen.queryByRole("button", { name: /Enroll Certificate/i })).not.toBeInTheDocument();
    openRowActions();
    expect(screen.queryByRole("button", { name: /Renew Certificate/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    // Read-only users can still view details and download
    expect(screen.getByRole("button", { name: /View Certificate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
  });

  it("write (non-admin) user sees certificate lifecycle actions", () => {
    setRole({ isAdmin: false, canEdit: true });
    mockList({});
    renderPage();
    openRowActions();
    expect(screen.getByRole("button", { name: /Renew Certificate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
});

describe("CertificatesPage row action menu", () => {
  beforeEach(() => {
    setRole({ isAdmin: true, canEdit: true });
    mockList({});
  });

  it("renders the menu outside the clipping grid shell and toggles it", () => {
    renderPage();
    const trigger = screen.getByRole("button", { name: /Certificate actions/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    const menuItem = screen.getByRole("button", { name: /View Certificate/i });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    // Portalled to <body>, so the grid's overflow-hidden cannot clip it.
    expect(menuItem.closest("table")).toBeNull();

    fireEvent.click(trigger);
    expect(screen.queryByRole("button", { name: /View Certificate/i })).not.toBeInTheDocument();
  });

  it("closes on outside click and on Escape", () => {
    renderPage();
    const trigger = screen.getByRole("button", { name: /Certificate actions/i });

    fireEvent.click(trigger);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("button", { name: /View Certificate/i })).not.toBeInTheDocument();

    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("button", { name: /View Certificate/i })).not.toBeInTheDocument();
  });

  it("keeps the menu open while the page scrolls", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Certificate actions/i }));
    fireEvent.scroll(window);
    expect(screen.getByRole("button", { name: /View Certificate/i })).toBeInTheDocument();
  });
});

describe("CertificatesPage key escrow state", () => {
  beforeEach(() => setRole({ isAdmin: true, canEdit: true }));

  it("hides the Key column when the backend reports no escrow state", () => {
    // key_escrowed is omitted entirely when escrow is not configured; showing a
    // column of "no key" badges then would be noise, not information.
    mockList({});
    renderPage();
    expect(screen.queryByRole("columnheader", { name: "Key" })).not.toBeInTheDocument();
    expect(screen.queryByText("Escrowed")).not.toBeInTheDocument();
    expect(screen.queryByText("No key")).not.toBeInTheDocument();
  });

  it("marks a certificate whose private key is escrowed", () => {
    mockList({}, { ...CERT, key_escrowed: true });
    renderPage();
    expect(screen.getByRole("columnheader", { name: "Key" })).toBeInTheDocument();
    expect(screen.getByText("Escrowed")).toBeInTheDocument();
  });

  it("flags a missing escrowed key explicitly", () => {
    mockList({}, { ...CERT, key_escrowed: false });
    renderPage();
    expect(screen.getByRole("columnheader", { name: "Key" })).toBeInTheDocument();
    expect(screen.getByText("No key")).toBeInTheDocument();
  });
});
