/**
 * Tests for the credential account inventory under the Credential Check.
 *
 * The tiles must filter the same rows the export asks the backend for, a
 * reader must not be offered changes, and an import must only send the rows
 * the preview accepted.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const permissions = { canWrite: true, canEditPage: true };
vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => ({ canWrite: permissions.canWrite }) }));
vi.mock("../../contexts/PermissionsContext", () => ({
  usePermissions: () => ({ canEditPage: () => permissions.canEditPage, hasCapability: () => true }),
}));

import apiClient from "../../services/apiClient";
import type { CredentialAccount, ImportPreview } from "../../services/toolsApi";
import AccountInventory from "./AccountInventory";

const NOW = new Date("2026-10-12T12:00:00Z");

const account = (overrides: Partial<CredentialAccount>): CredentialAccount => ({
  id: 1,
  application: "ATTCC",
  app_code: null,
  account_type: "domain",
  directory: "ITSERVICES",
  account_name: "m52142",
  owner: "Jane Doe",
  account_status: "active",
  expiry_date: "2027-06-01",
  never_expires: false,
  password_changed_date: null,
  last_login_date: null,
  failed_logins: 0,
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
  ...overrides,
});

const ACCOUNTS: CredentialAccount[] = [
  account({ id: 1, account_name: "svc-expired", expiry_date: "2026-10-01" }),
  account({ id: 2, account_name: "svc-soon", expiry_date: "2026-10-30", owner: "Raj" }),
  account({
    id: 3,
    application: "DWS",
    account_type: "jfrog",
    directory: "gold",
    account_name: "svc@att.com",
    never_expires: true,
    expiry_date: null,
    last_check_status: "locked",
    reset_url: "https://reset.example.com/jfrog",
    notes: "Used by the nightly build",
  }),
];

function renderInventory(onCheck = vi.fn(), canCheck = true) {
  vi.mocked(apiClient.get).mockResolvedValue({ data: ACCOUNTS });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AccountInventory canCheck={canCheck} onCheck={onCheck} />
    </QueryClientProvider>,
  );
  return { onCheck };
}

const gridRows = () => screen.getAllByRole("row").slice(1);

beforeEach(() => {
  vi.clearAllMocks();
  permissions.canWrite = true;
  permissions.canEditPage = true;
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AccountInventory — grid", () => {
  it("lists every account with owner, expiry, last check and reset link", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    expect(screen.getByText("Raj")).toBeInTheDocument();
    expect(screen.getByText("Never")).toBeInTheDocument();
    expect(screen.getByText("Locked out")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /reset password/i })).toHaveAttribute(
      "href",
      "https://reset.example.com/jfrog",
    );
    const jfrogRow = screen.getByText("svc@att.com").closest("tr") as HTMLElement;
    expect(within(jfrogRow).getByText("JFrog Gold")).toBeInTheDocument();
  });

  it("filters with the tiles", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    fireEvent.click(screen.getByRole("button", { name: /expiry date has passed/i }));
    expect(gridRows()).toHaveLength(1);
    expect(screen.getByText("svc-expired")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /expiring in the next 30 days/i }));
    expect(screen.getByText("svc-soon")).toBeInTheDocument();
    expect(gridRows()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /failed logins, or whose last check/i }));
    expect(screen.getByText("svc@att.com")).toBeInTheDocument();
    expect(gridRows()).toHaveLength(1);
  });

  it("narrows to one application", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    fireEvent.change(screen.getByLabelText("Application"), { target: { value: "DWS" } });

    expect(gridRows()).toHaveLength(1);
    expect(screen.getByText("svc@att.com")).toBeInTheDocument();
  });

  it("hands an account to the check cards", async () => {
    const { onCheck } = renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    fireEvent.click(screen.getByRole("button", { name: "Check svc-soon" }));

    expect(onCheck).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });

  it("offers a reader no way to change the inventory", async () => {
    permissions.canWrite = false;
    permissions.canEditPage = false;
    renderInventory(vi.fn(), false);
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    expect(screen.queryByRole("button", { name: /add account/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit /i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });

  it("exports the rows on screen — same filters, every page", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("Application"), { target: { value: "ATTCC" } });
    fireEvent.click(screen.getByRole("button", { name: /expiring in the next 30 days/i }));
    window.URL.createObjectURL = vi.fn(() => "blob:x");
    window.URL.revokeObjectURL = vi.fn();
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: "x", headers: {} });

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "CSV (.csv)" }));

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/tools/accounts/export", {
        params: { format: "csv", application: "ATTCC", directory: undefined, view: "expiring", q: undefined },
        responseType: "blob",
      }),
    );
  });
});

describe("AccountInventory — what a check fills in", () => {
  it("shows the directory's name for the account, and says when a check would fill a blank", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: [
        account({ id: 1, account_name: "m47355", owner: "m47355 - KAREN RIDGEWAY (kr873u)", expiry_date: null }),
      ],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AccountInventory canCheck onCheck={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("m47355 - KAREN RIDGEWAY (kr873u)")).toBeInTheDocument();
    expect(screen.getAllByText("Not read yet")).toHaveLength(2); // expiry and last login

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "ridgeway" } });
    expect(gridRows()).toHaveLength(1);
  });
});

describe("AccountInventory — whether an account can sign in", () => {
  it("shows the state the directory reports, separately from the password verdict", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: [
        account({ id: 1, account_name: "svc-off", account_status: "disabled", last_check_status: "valid" }),
        account({ id: 2, account_name: "svc-stale", account_status: "inactive" }),
        account({ id: 3, account_name: "svc-new", account_status: null }),
      ],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AccountInventory canCheck onCheck={vi.fn()} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    const disabled = screen.getByText("svc-off").closest("tr") as HTMLElement;
    // The account is disabled even though its password checked out.
    expect(within(disabled).getByText("Disabled")).toBeInTheDocument();
    expect(within(disabled).getByText("Valid")).toBeInTheDocument();
    const statusCell = (name: string) =>
      (screen.getByText(name).closest("tr") as HTMLTableRowElement).cells[2]; // Application, Account, Status
    expect(within(statusCell("svc-stale")).getByText("Inactive")).toBeInTheDocument();
    // Never read: the Status cell says so rather than implying it is fine.
    expect(within(statusCell("svc-new")).getByText("Not read yet")).toBeInTheDocument();
  });

  it("counts a disabled account as failing sign-in", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: [account({ id: 1, account_name: "svc-off", account_status: "disabled", failed_logins: 0 })],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AccountInventory canCheck onCheck={vi.fn()} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(gridRows()).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: /failed logins, or whose last check/i }));

    expect(gridRows()).toHaveLength(1);
  });
});

describe("AccountInventory — reading from the directory", () => {
  it("re-reads a domain account and says so", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { status: "ok", reason: null, account: ACCOUNTS[0] } });

    fireEvent.click(screen.getByRole("button", { name: /Read svc-expired from the ITSERVICES directory/ }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Read svc-expired from the ITSERVICES/));
    expect(apiClient.post).toHaveBeenCalledWith("/tools/accounts/1/refresh", {});
  });

  it("says why when the directory cannot answer", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { status: "unconfigured", reason: "No directory reader is configured for ITSERVICES.", account: ACCOUNTS[0] },
    });

    fireEvent.click(screen.getByRole("button", { name: /Read svc-expired from the ITSERVICES directory/ }));

    await waitFor(() => expect(screen.getByText("No directory reader is configured for ITSERVICES.")).toBeInTheDocument());
  });

  it("is not offered for JFrog or AAF accounts, which only a check can fill in", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));

    expect(screen.queryByRole("button", { name: /Read svc@att.com from/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check svc@att.com" })).toBeInTheDocument();
  });
});

describe("AccountInventory — the Add form", () => {
  it("asks only for what a person knows, and posts only that", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: {} });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));
    const dialog = screen.getByRole("dialog", { name: "Add account" });

    // Everything the directory answers for is absent — there is nothing to type it into.
    for (const label of [/^owner/i, /expiry date/i, /password last changed/i, /last login/i, /failed logins/i]) {
      expect(within(dialog).queryByLabelText(label)).not.toBeInTheDocument();
    }

    fireEvent.change(within(dialog).getByLabelText(/application/i), { target: { value: "ATTCC" } });
    fireEvent.change(within(dialog).getByLabelText(/app code/i), { target: { value: "31599" } });
    fireEvent.change(within(dialog).getByLabelText(/^account/i), { target: { value: "m47355" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add account" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/tools/accounts", {
        application: "ATTCC",
        app_code: "31599",
        account_type: "domain",
        directory: "ITSERVICES",
        account_name: "m47355",
        reset_url: null,
        notes: null,
      }),
    );
  });
});

describe("AccountInventory — import", () => {
  const PREVIEW: ImportPreview = {
    rows: [
      {
        row: 2,
        action: "create",
        label: "ITSERVICES\\m1",
        errors: [],
        account: {
          application: "ATTCC",
          app_code: null,
          account_type: "domain",
          directory: "ITSERVICES",
          account_name: "m1",
          reset_url: null,
          notes: null,
        },
      },
      { row: 3, action: "invalid", label: "ATTCC / m2", errors: ["Type 'Kerberos' is not one of ITSERVICES"], account: null },
    ],
    total: 2,
    create_count: 1,
    update_count: 0,
    invalid_count: 1,
  };

  it("previews the file and imports only the rows that passed", async () => {
    renderInventory();
    await waitFor(() => expect(gridRows()).toHaveLength(3));
    vi.mocked(apiClient.post)
      .mockResolvedValueOnce({ data: PREVIEW })
      .mockResolvedValueOnce({ data: { created: 1, updated: 0 } });

    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    const dialog = screen.getByRole("dialog", { name: "Import accounts" });
    const file = new File(["Application,Type,Account"], "ids.csv", { type: "text/csv" });
    fireEvent.change(within(dialog).getByLabelText("Choose an Excel or CSV file"), { target: { files: [file] } });

    await waitFor(() => expect(within(dialog).getByText("1 new")).toBeInTheDocument());
    expect(within(dialog).getByText(/is not one of ITSERVICES/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Import 1 account" }));

    await waitFor(() => expect(within(dialog).getByText("Imported: 1 new, 0 updated.")).toBeInTheDocument());
    expect(apiClient.post).toHaveBeenLastCalledWith("/tools/accounts/import", {
      accounts: [PREVIEW.rows[0].account],
    });
  });
});
