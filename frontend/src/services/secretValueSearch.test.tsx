import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// vi.mock is hoisted above the file body, so the spy has to be hoisted with it.
const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("./apiClient", () => ({
  default: { get },
  initializeMsal: vi.fn(),
  setSubscriptionScopeParam: vi.fn(),
  getSubscriptionScopeParam: vi.fn(() => null),
  getAuthToken: vi.fn(async () => null),
  msalInstance: {},
}));

import {
  SECRET_VALUE_SEARCH_MIN_CHARS,
  SecretSearchResult,
  useSecretValueSearch,
} from "./costApi";

const VAULT = "https://demo-kv.vault.azure.net/";

const result: SecretSearchResult = {
  scope: "name_and_value",
  results: [
    {
      name: "api-key",
      id: `${VAULT}secrets/api-key`,
      content_type: "",
      enabled: true,
      created: null,
      updated: null,
      expires: null,
      not_before: null,
      tags: {},
      managed: false,
      matched_in: ["value_base64"],
    },
  ],
  total_secrets: 605,
  scanned: 605,
  unreadable: 0,
  base64_matches: 1,
  skipped_disabled: 0,
  truncated: false,
  timed_out: false,
  read_error: null,
};

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useSecretValueSearch", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: result });
  });

  it("asks the backend to match names and values", async () => {
    const { result: hook } = renderHook(
      () => useSecretValueSearch(VAULT, "  prod-token  ", true),
      { wrapper }
    );

    await waitFor(() => expect(hook.current.isSuccess).toBe(true));

    expect(get).toHaveBeenCalledWith(
      "/keyvault/secrets/search",
      expect.objectContaining({
        params: { vault_uri: VAULT, q: "prod-token", scope: "name_and_value" },
      })
    );
    expect(hook.current.data?.results[0].matched_in).toEqual(["value_base64"]);
    expect(hook.current.data?.base64_matches).toBe(1);
  });

  it("does not scan the vault for terms below the minimum length", async () => {
    const short = "x".repeat(SECRET_VALUE_SEARCH_MIN_CHARS - 1);
    const { result: hook } = renderHook(() => useSecretValueSearch(VAULT, short, true), {
      wrapper,
    });

    await waitFor(() => expect(hook.current.fetchStatus).toBe("idle"));
    expect(get).not.toHaveBeenCalled();
  });

  it("stays idle when value search is not available to the user", async () => {
    const { result: hook } = renderHook(
      () => useSecretValueSearch(VAULT, "prod-token", false),
      { wrapper }
    );

    await waitFor(() => expect(hook.current.fetchStatus).toBe("idle"));
    expect(get).not.toHaveBeenCalled();
  });

  it("stays idle until a vault is selected", async () => {
    const { result: hook } = renderHook(
      () => useSecretValueSearch(null, "prod-token", true),
      { wrapper }
    );

    await waitFor(() => expect(hook.current.fetchStatus).toBe("idle"));
    expect(get).not.toHaveBeenCalled();
  });
});
