/**
 * Tests for CredentialCheckPage — the details shown under a verdict.
 *
 * Each source reports a different subset of expiry / last use, so a gap must
 * read as "Not reported" (with the backend's reason) rather than vanish, and
 * "never expires" must not be confused with "not reported".
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("../contexts/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));
vi.mock("../contexts/PermissionsContext", () => ({ usePermissions: () => ({ hasCapability: () => true }) }));

import apiClient from "../services/apiClient";
import type { CredentialAccountDetails, CredentialCheckResult } from "../services/toolsApi";
import CredentialCheckPage from "./CredentialCheckPage";

const NOW = new Date("2026-10-12T12:00:00Z");

const account = (overrides: Partial<CredentialAccountDetails> = {}): CredentialAccountDetails => ({
  display_name: null,
  expires_at: null,
  never_expires: false,
  last_changed_at: null,
  last_used_at: null,
  last_used_note: null,
  account_expires_at: null,
  notes: [],
  ...overrides,
});

const result = (overrides: Partial<CredentialCheckResult>): CredentialCheckResult => ({
  kind: "domain",
  target: "ITSERVICES\\m52142",
  valid: true,
  status: "valid",
  message: "The password is correct and the account can sign in.",
  checked_at: "2026-10-12T12:00:00",
  details: {},
  account: null,
  ...overrides,
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CredentialCheckPage />
    </QueryClientProvider>,
  );
}

async function checkDomain(response: CredentialCheckResult) {
  vi.mocked(apiClient.post).mockResolvedValueOnce({ data: response });
  renderPage();
  fireEvent.change(screen.getAllByLabelText("Username")[0], { target: { value: "m52142" } });
  fireEvent.change(screen.getAllByLabelText("Password")[0], { target: { value: "secret" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Check" })[0]);
  await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CredentialCheckPage — account details", () => {
  it("shows a domain password's expiry, last change and last sign-in", async () => {
    await checkDomain(
      result({
        account: account({
          display_name: "Miri, Mohnish",
          expires_at: "2026-12-14T12:00:00Z",
          last_changed_at: "2026-09-15T12:00:00Z",
          last_used_at: "2026-10-01T12:00:00Z",
          last_used_note: "Approximate — Active Directory records sign-ins only every 9 to 14 days.",
        }),
      }),
    );

    expect(screen.getByText("Miri, Mohnish")).toBeInTheDocument();
    expect(screen.getByText("Password expires")).toBeInTheDocument();
    expect(screen.getByText("12-14-2026")).toBeInTheDocument();
    expect(screen.getByText("63d")).toBeInTheDocument();
    expect(screen.getByText("Password last changed")).toBeInTheDocument();
    expect(screen.getByText("27 days ago")).toBeInTheDocument();
    expect(screen.getByText("Last sign-in")).toBeInTheDocument();
    expect(screen.getByText("11 days ago")).toBeInTheDocument();
    expect(screen.getByText(/only every 9 to 14 days/)).toBeInTheDocument();
  });

  it("says why last use is missing instead of leaving a blank", async () => {
    const reason = "None recorded in the 9+ days before this check — the check itself is now the latest sign-in.";
    await checkDomain(result({ account: account({ last_used_note: reason }) }));

    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.getByText("Not reported")).toBeInTheDocument(); // the expiry row
  });

  it("tells 'never expires' apart from 'not reported'", async () => {
    await checkDomain(result({ account: account({ never_expires: true }) }));

    expect(screen.getByText("Never")).toBeInTheDocument();
  });

  it("shows the source's notes", async () => {
    const note = "The directory did not return details for this account.";
    await checkDomain(result({ account: account({ notes: [note] }) }));

    expect(screen.getByText(note)).toBeInTheDocument();
  });

  it("shows no details block for a verdict that carries none", async () => {
    await checkDomain(
      result({ valid: false, status: "locked", message: "The account is locked out.", account: null }),
    );

    expect(screen.getByText("The account is locked out.")).toBeInTheDocument();
    expect(screen.queryByText("Password expires")).not.toBeInTheDocument();
  });
});
