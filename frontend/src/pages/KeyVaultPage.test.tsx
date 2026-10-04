/**
 * Key Vault page: KPI tiles filter the grids beneath them, vault and item
 * names open drill-down views, certificate search covers CN / SAN / serial,
 * and secret values are only offered to write roles.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../contexts/SubscriptionContext", () => ({
  useSubscriptionScope: () => ({ effectiveSubscriptionIds: [], isLoading: false }),
}));

import apiClient from "../services/apiClient";
import { useAuth } from "../contexts/AuthContext";
import KeyVaultPage from "./KeyVaultPage";

const PROD = "https://kv-attcc-prod.vault.azure.net/";
const DEV = "https://kv-attcc-dev.vault.azure.net/";
const daysFromNow = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 19);

const DASHBOARD = {
  total_vaults: 2,
  total_secrets: 15,
  total_keys: 3,
  total_certificates: 2,
  expired_count: 1,
  expiring_within_30_days: 1,
  expiring_within_90_days: 2,
  expiring_within_360_days: 3,
  expiring_items: [
    { name: "db-password", vault_name: "kv-attcc-prod", type: "secret", expires: daysFromNow(-3), days_remaining: -3, enabled: true },
    { name: "api-token", vault_name: "kv-attcc-dev", type: "secret", expires: daysFromNow(12), days_remaining: 12, enabled: true },
    { name: "web-cert", vault_name: "kv-attcc-prod", type: "certificate", expires: daysFromNow(45), days_remaining: 45, enabled: true },
    { name: "old-token", vault_name: "kv-attcc-dev", type: "secret", expires: daysFromNow(200), days_remaining: 200, enabled: true },
  ],
  vault_summaries: [
    { name: "kv-attcc-prod", vault_uri: PROD, location: "eastus2", subscription_id: "sub-1", secrets_count: 10, keys_count: 0, certificates_count: 2, soft_delete: true, purge_protection: true, rbac_enabled: false },
    { name: "kv-attcc-dev", vault_uri: DEV, location: "eastus2", subscription_id: "sub-1", secrets_count: 5, keys_count: 3, certificates_count: 0, soft_delete: true, purge_protection: false, rbac_enabled: true },
  ],
  generated_at: "2026-10-04T10:00:00",
  source: "database",
};

const SECRETS = [
  { name: "db-password", id: `${PROD}secrets/db-password`, content_type: "text/plain", enabled: true, created: "2025-01-01T00:00:00", updated: "2025-10-01T00:00:00", expires: daysFromNow(-3), not_before: null, tags: { owner: "attcc" }, managed: false },
];

const CERTS = [
  {
    name: "attccdashboard-web-att-com", id: `${PROD}certificates/attccdashboard-web-att-com`, enabled: true, created: null, updated: null,
    expires: daysFromNow(39), not_before: null, cn_name: "attccgui.web.att.com",
    san: ["attccgui.web.att.com", "kibana.web.att.com", "horizonreports.web.att.com"],
    serial_number: "BA10CEDB97F1435", thumbprint: "AAAA", tags: {},
  },
  {
    name: "cesdataroutergears-web-att-com", id: `${PROD}certificates/cesdataroutergears-web-att-com`, enabled: true, created: null, updated: null,
    expires: daysFromNow(34), not_before: null, cn_name: "cesdataroutergears.web.att.com",
    san: ["cesdataroutergears.web.att.com"], serial_number: "B871222109390AF", thumbprint: "BBBB", tags: {},
  },
];

const VERSIONS = [
  { version: "v2current", id: `${PROD}secrets/db-password/v2current`, enabled: true, created: "2025-10-01T00:00:00", updated: null, not_before: null, expires: daysFromNow(-3), recovery_level: "Recoverable", content_type: "text/plain", managed: false, thumbprint: "", tags: {}, is_current: true },
  { version: "v1old", id: `${PROD}secrets/db-password/v1old`, enabled: false, created: "2025-01-01T00:00:00", updated: null, not_before: null, expires: null, recovery_level: "Recoverable", content_type: "text/plain", managed: false, thumbprint: "", tags: {}, is_current: false },
];

const AKS_REFS = [
  {
    cluster_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-prod",
    cluster_name: "aks-prod", resource_group: "rg", subscription_id: "sub-1", namespace: "apps", name: "db-password-akvs",
    object_name: "db-password", object_type: "secret", object_kind: "secret", object_version: null, output_kind: "secret",
    output_name: "db-credentials", output_data_key: "password", status: "Failed", status_reason: "Secret expired",
    last_azure_update: "2026-10-01T00:00:00", inventory_synced_at: "2026-10-04T00:00:00",
  },
];

const VAULT_DETAIL = {
  vault: { name: "kv-attcc-prod", vault_uri: PROD, id: "/subscriptions/sub-1/resourceGroups/rg-kv/providers/Microsoft.KeyVault/vaults/kv-attcc-prod", location: "eastus2", resource_group: "rg-kv", subscription_id: "sub-1", tags: { env: "prod" } },
  properties: {
    sku: "standard", sku_family: "A", tenant_id: "t-1", provisioning_state: "Succeeded", soft_delete_enabled: true, soft_delete_retention_days: 90,
    purge_protection_enabled: true, rbac_enabled: false, enabled_for_deployment: false, enabled_for_disk_encryption: false,
    enabled_for_template_deployment: false, public_network_access: "Disabled", network_default_action: "Deny", network_bypass: "AzureServices",
    ip_rules: [], virtual_network_rules: [],
    private_endpoints: [{ name: "pe-kv-attcc-prod", private_endpoint_id: "/subscriptions/sub-1/pe", status: "Approved", description: null, provisioning_state: "Succeeded" }],
    access_policies: [{ object_id: "obj-123", tenant_id: "t-1", application_id: null, secrets: ["get", "list"], keys: [], certificates: [], storage: [] }],
    created_at: null, created_by: null, last_modified_at: null, last_modified_by: null,
  },
  arm: { id: "x" },
  arm_error: null,
};

function mockApi() {
  (apiClient.get as any).mockImplementation(async (url: string, config?: { params?: Record<string, string> }) => {
    const params = config?.params ?? {};
    if (url === "/keyvault/dashboard") return { data: DASHBOARD };
    if (url === "/keyvault/vaults") return { data: [] };
    if (url.startsWith("/keyvault/sync/status")) {
      return {
        data: {
          recent_syncs: [
            {
              id: 1, sync_type: "full", status: "partial", started_at: "2026-10-04T09:40:00", completed_at: "2026-10-04T09:46:12",
              vaults_synced: 2, secrets_synced: 15, keys_synced: 3, certificates_synced: 2, triggered_by: "scheduler",
              error_message: "Vaults preserved from cache after item fetch failures (1): kv-attcc-dev",
            },
          ],
        },
      };
    }
    if (url.startsWith("/keyvault/secrets?vault_uri=")) return { data: SECRETS };
    if (url.startsWith("/keyvault/keys?vault_uri=")) return { data: [] };
    if (url.startsWith("/keyvault/certificates?vault_uri=")) return { data: CERTS };
    if (url === "/keyvault/secrets/db-password/versions") return { data: { versions: VERSIONS } };
    if (url === "/keyvault/secrets/db-password") {
      return { data: { name: "db-password", version: params.version ?? "v2current", value: "cMOkc3N3w7ZyZA==", content_type: "text/plain", is_base64: true, decoded_value: null, enabled: true, created: null, updated: null, not_before: null, expires: null } };
    }
    if (url === "/keyvault/aks-references") return { data: { references: params.name === "db-password" || !params.name ? AKS_REFS : [] } };
    if (url.startsWith("/keyvault/history")) return { data: { history: [], count: 0 } };
    if (url === "/keyvault/vaults/detail") return { data: VAULT_DETAIL };
    throw new Error(`unexpected GET ${url}`);
  });
}

function renderPage(path = "/keyvault", canWrite = true) {
  vi.mocked(useAuth).mockReturnValue({ canWrite, isAdmin: false } as any);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={qc}>
        <KeyVaultPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const expiringGrid = () => screen.getByLabelText("Expiry window").closest("div.overflow-hidden") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  window.requestAnimationFrame = ((cb: FrameRequestCallback) => { cb(0); return 0; }) as typeof window.requestAnimationFrame;
  Element.prototype.scrollIntoView = vi.fn();
  mockApi();
});

describe("KeyVaultPage tiles", () => {
  it("filters the expiring grid from the Expired and 30-day tiles", async () => {
    renderPage();
    await screen.findByText("Azure Key Vault");

    // Default: expiring within 90 days — not the expired secret, not the 200-day one.
    let grid = expiringGrid();
    expect(within(grid).getByText("api-token")).toBeInTheDocument();
    expect(within(grid).getByText("web-cert")).toBeInTheDocument();
    expect(within(grid).queryByText("db-password")).toBeNull();
    expect(within(grid).queryByText("old-token")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show expired items" }));
    grid = expiringGrid();
    expect(within(grid).getByText("db-password")).toBeInTheDocument();
    expect(within(grid).getByText("Expired 3d ago")).toBeInTheDocument();
    expect(within(grid).queryByText("api-token")).toBeNull();
    expect(screen.getByText("Expired items")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show expired items" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Show items expiring within 30 days" }));
    grid = expiringGrid();
    expect(within(grid).getByText("api-token")).toBeInTheDocument();
    expect(within(grid).queryByText("web-cert")).toBeNull();

    // Clicking the active tile again clears it.
    fireEvent.click(screen.getByRole("button", { name: "Show items expiring within 30 days" }));
    expect(within(expiringGrid()).getByText("web-cert")).toBeInTheDocument();
  });

  it("narrows the vault inventory from the Keys tile", async () => {
    renderPage();
    await screen.findByText("Azure Key Vault");
    const inventory = () => screen.getByPlaceholderText("Search vaults...").closest("div.overflow-hidden") as HTMLElement;
    expect(within(inventory()).getByText("kv-attcc-prod")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show the vaults that hold keys, most first" }));
    expect(within(inventory()).queryByText("kv-attcc-prod")).toBeNull();
    expect(within(inventory()).getByText("kv-attcc-dev")).toBeInTheDocument();
    expect(screen.getByText("Vaults with keys")).toBeInTheDocument();
  });

  it("explains partial syncs instead of truncating the message", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Sync warnings \(1\)/ }));
    expect(screen.getByText("Vaults preserved from cache after item fetch failures (1): kv-attcc-dev")).toBeInTheDocument();
    // Naive API timestamps are UTC; the portal timezone defaults to UTC.
    expect(screen.getByText(/Last synced: Oct 4, 2026, 9:46 AM UTC/)).toBeInTheDocument();
  });
});

describe("KeyVaultPage drill-downs", () => {
  it("opens a vault's details from its name", async () => {
    renderPage();
    const inventory = (await screen.findByPlaceholderText("Search vaults...")).closest("div.overflow-hidden") as HTMLElement;
    fireEvent.click(within(inventory).getByRole("button", { name: "kv-attcc-prod" }));

    const dialog = await screen.findByRole("dialog", { name: "kv-attcc-prod" });
    expect(within(dialog).getByText("Azure Key Vault")).toBeInTheDocument();
    expect(await within(dialog).findByText("90-day retention")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("tab", { name: /^Network/ }));
    expect(within(dialog).getByText("pe-kv-attcc-prod")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("tab", { name: /^Access/ }));
    expect(within(dialog).getByText("obj-123")).toBeInTheDocument();
  });

  it("opens a secret's details from the expiring grid with versions and AKS usage", async () => {
    renderPage("/keyvault?expiry=expired");
    await screen.findByText("Azure Key Vault");
    fireEvent.click(within(expiringGrid()).getByRole("button", { name: "db-password" }));

    const dialog = await screen.findByRole("dialog", { name: "db-password" });
    expect(within(dialog).getByText("Key Vault Secret")).toBeInTheDocument();
    expect(await within(dialog).findByRole("tab", { name: "Versions (2)" })).toBeInTheDocument();
    expect(await within(dialog).findByRole("tab", { name: "Used by AKS (1)" })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("tab", { name: "Used by AKS (1)" }));
    expect(within(dialog).getByText("aks-prod")).toBeInTheDocument();
    expect(within(dialog).getByText("db-credentials")).toBeInTheDocument();
  });

  it("reads a secret value only when asked, decoding Base64 as UTF-8", async () => {
    renderPage("/keyvault?expiry=expired");
    await screen.findByText("Azure Key Vault");
    fireEvent.click(within(expiringGrid()).getByRole("button", { name: "db-password" }));
    const dialog = await screen.findByRole("dialog", { name: "db-password" });

    await waitFor(() => expect(within(dialog).getByRole("tab", { name: "Versions (2)" })).toBeInTheDocument());
    expect((apiClient.get as any).mock.calls.some(([url]: [string]) => url === "/keyvault/secrets/db-password")).toBe(false);

    fireEvent.click(within(dialog).getByRole("tab", { name: "Value" }));
    const value = (await within(dialog).findByLabelText("Value of db-password")) as HTMLTextAreaElement;
    expect(value.value).toBe("cMOkc3N3w7ZyZA==");
    fireEvent.click(within(dialog).getByRole("button", { name: "Decoded (Base64 → UTF-8)" }));
    expect((within(dialog).getByLabelText("Value of db-password") as HTMLTextAreaElement).value).toBe("pässwörd");
  });

  it("hides values and fixes from read-only users", async () => {
    renderPage("/keyvault?expiry=expired", false);
    await screen.findByText("Azure Key Vault");
    expect(within(expiringGrid()).queryByRole("button", { name: /Fix/ })).toBeNull();

    fireEvent.click(within(expiringGrid()).getByRole("button", { name: "db-password" }));
    const dialog = await screen.findByRole("dialog", { name: "db-password" });
    expect(within(dialog).queryByRole("tab", { name: "Value" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /Delete/ })).toBeNull();
  });
});

describe("Certificate search", () => {
  it("finds certificates by a SAN hidden behind “+N more” and by serial", async () => {
    renderPage("/keyvault?vault=kv-attcc-prod&tab=certificates");
    const search = await screen.findByPlaceholderText("Search name, CN, SAN, serial, thumbprint…");

    fireEvent.change(search, { target: { value: "horizonreports" } });
    expect(screen.getByText("1 of 2 certificates")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "attccdashboard-web-att-com" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "cesdataroutergears-web-att-com" })).toBeNull();
    // The matching SAN is shown (and marked) even though it is the third one.
    expect(screen.getByText("horizonreports", { selector: "mark" })).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "B8:71:22" } });
    expect(screen.getByRole("button", { name: "cesdataroutergears-web-att-com" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "attccdashboard-web-att-com" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Certificate search field"), { target: { value: "name" } });
    expect(screen.getByText("No certificates match “B8:71:22”")).toBeInTheDocument();
  });
});
