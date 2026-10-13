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
vi.mock("../contexts/PermissionsContext", () => ({
  usePermissions: () => ({ hasCapability: () => true, canEditPage: () => true }),
}));

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
  account_status: null,
  account_status_note: null,
  failed_sign_ins: null,
  last_failed_at: null,
  failed_sign_ins_note: null,
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
  inventory_updated: false,
  directory: "ITSERVICES",
  account_name: "m52142",
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
  vi.mocked(apiClient.get).mockResolvedValue({ data: [] });
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

describe("CredentialCheckPage — JFrog instance and the inventory", () => {
  it("checks a JFrog token on the instance chosen", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [] });
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: result({ kind: "jfrog", target: "svc@att.com (Gold)" }) });
    renderPage();

    fireEvent.change(screen.getByLabelText("Instance"), { target: { value: "gold" } });
    fireEvent.change(screen.getAllByLabelText("Username")[1], { target: { value: "svc@att.com" } });
    fireEvent.change(screen.getByLabelText("Token"), { target: { value: "tok" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Check" })[1]);

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/tools/credential-checks/jfrog", {
        instance: "gold",
        username: "svc@att.com",
        token: "tok",
      }),
    );
  });

  it("fills in the check card from an inventory row and focuses its secret field", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: [
        {
          id: 7,
          application: "ATTCC",
          app_code: null,
          account_type: "aaf",
          directory: "nonprod",
          account_name: "m1@com.att.attcc",
          owner: null,
          expiry_date: null,
          never_expires: false,
          password_changed_date: null,
          last_login_date: null,
          failed_logins: null,
          directory_synced_at: null,
          reset_url: null,
          notes: null,
          last_checked_at: null,
          last_check_status: null,
          last_checked_by: null,
          created_by: null,
          created_at: null,
          updated_by: null,
          updated_at: null,
        },
      ],
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Check m1@com.att.attcc" }));

    expect((screen.getByLabelText("Environment") as HTMLSelectElement).value).toBe("nonprod");
    expect((screen.getByLabelText("Account") as HTMLInputElement).value).toBe("m1@com.att.attcc");
    expect(document.activeElement).toBe(screen.getAllByLabelText("Password")[1]);
  });
});

describe("CredentialCheckPage — add a checked account to the inventory", () => {
  it("lists the account with the expiry, last sign-in and name the check just read", async () => {
    await checkDomain(
      result({
        directory: "TESTITSERVICES",
        account_name: "m47355",
        account: account({
          display_name: "m47355 - KAREN RIDGEWAY (kr873u)",
          expires_at: "2027-09-30T15:00:00Z",
          last_changed_at: "2026-09-30T15:00:00Z",
          last_used_at: "2026-10-11T08:00:00Z",
        }),
      }),
    );
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { id: 1, application: "ATTCC" } });

    fireEvent.click(screen.getByRole("button", { name: "Add to inventory" }));
    fireEvent.change(screen.getByLabelText("Add to the inventory under application"), { target: { value: "ATTCC" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(screen.getByText(/Added to the inventory under/)).toBeInTheDocument());
    expect(apiClient.post).toHaveBeenLastCalledWith(
      "/tools/accounts",
      expect.objectContaining({
        application: "ATTCC",
        account_type: "domain",
        directory: "TESTITSERVICES",
        account_name: "m47355",
        expiry_date: "2027-09-30",
        password_changed_date: "2026-09-30",
        last_login_date: "2026-10-11",
        owner: "m47355 - KAREN RIDGEWAY (kr873u)",
      }),
    );
  });

  it("is not offered once the account is listed, or for a credential that failed", async () => {
    await checkDomain(result({ inventory_updated: true }));
    expect(screen.queryByRole("button", { name: "Add to inventory" })).not.toBeInTheDocument();
  });
});

describe("CredentialCheckPage — reading and clearing an answer", () => {
  it("says when the check ran and clears the answer when dismissed", async () => {
    await checkDomain(result({ target: "ITSERVICES\\m47355", checked_at: "2026-10-12T11:55:00" }));

    expect(screen.getByText(/^Checked /)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss the result for ITSERVICES\\m47355" }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    // The card stays filled in, ready to check the same account again.
    expect((screen.getAllByLabelText("Username")[0] as HTMLInputElement).value).toBe("m52142");
  });

  it("clears a failed check the same way", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [] });
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("boom"));
    renderPage();
    fireEvent.change(screen.getAllByLabelText("Username")[0], { target: { value: "m52142" } });
    fireEvent.change(screen.getAllByLabelText("Password")[0], { target: { value: "secret" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Check" })[0]);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Dismiss this message" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("CredentialCheckPage — the lockout caution", () => {
  it("is not on the page until a password is actually refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [] });
    renderPage();

    expect(screen.queryByText(/counted as a failed sign-in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/lock this account out/)).not.toBeInTheDocument();
  });

  it("appears with a refused domain password", async () => {
    await checkDomain(
      result({ valid: false, status: "invalid", message: "Incorrect password.", account: null }),
    );

    expect(screen.getByText(/That counted as a failed sign-in/)).toBeInTheDocument();
    expect(screen.getByText(/lock this account out in Active Directory/)).toBeInTheDocument();
  });

  it("stays away when the password was right, or was never the problem", async () => {
    await checkDomain(result({ valid: false, status: "expired", message: "The password has expired." }));
    expect(screen.queryByText(/counted as a failed sign-in/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Dismiss the result/ }));
    await checkDomain(result({ status: "error", valid: false, message: "Could not reach the directory." }));
    expect(screen.queryByText(/counted as a failed sign-in/)).not.toBeInTheDocument();
  });
});
