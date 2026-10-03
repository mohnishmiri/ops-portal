/**
 * Tests for PortalAccessGate — the frontend half of the authentication vs.
 * authorization split.
 *
 * The bug this guards against: a valid corporate identity with no portal
 * entitlement used to reach the full application shell, because MSAL
 * authentication succeeding was treated as authorization. The gate must render
 * Access Denied instead, and must not mount any data provider below it.
 *
 * It also guards the follow-up: an unentitled identity that was merely shown a
 * denial screen sat there indefinitely, which reads as a broken portal. The
 * denial must sign the session out on its own so the user cannot linger in a
 * half-dead session, and must record why so the login page can explain it.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

// The gate must behave as the real (non-dev) path.
vi.mock("../config/authConfig", () => ({ isDevMode: false }));

const logoutRedirect = vi.fn();
vi.mock("@azure/msal-react", () => ({
  useMsal: () => ({ instance: { logoutRedirect } }),
}));

import apiClient from "../services/apiClient";
import { NO_SUBSCRIPTION_ACCESS_EVENT } from "../services/accessEvents";
import { PortalAccessGate, useSession } from "./SessionContext";
import { peekAccessDenial, clearAccessDenial } from "../config/accessDenial";

const AUTHORIZED = {
  authenticated: true,
  authorized: true,
  user: { user_id: "u1", display_name: "Ops User", email: "ops@example.com" },
  roles: ["write"],
  is_admin: false,
  is_super_admin: false,
  can_write: true,
  permissions: ["AKS_VIEW", "AKS_POD_DELETE"],
  access: { has_subscription_access: true, admin_project_ids: [], readable_count: 4, writable_count: 2 },
};

const DENIED = {
  authenticated: true,
  authorized: false,
  user: { user_id: "u2", display_name: "Outsider", email: "outsider@example.com" },
  roles: [],
  is_admin: false,
  is_super_admin: false,
  can_write: false,
  permissions: [],
  access: { has_subscription_access: false, admin_project_ids: [] },
};

/** Sentinel standing in for the authenticated application shell. */
const Shell: React.FC = () => {
  const { hasCapability, isSuperAdmin, hasSubscriptionAccess, adminProjectIds } = useSession();
  return (
    <div>
      <span>APP SHELL</span>
      <span>{hasCapability("AKS_POD_DELETE") ? "can-delete" : "cannot-delete"}</span>
      <span>{isSuperAdmin ? "super-admin" : "not-super-admin"}</span>
      <span>{hasSubscriptionAccess ? "has-subscriptions" : "no-subscriptions"}</span>
      <span>admin-projects:{adminProjectIds.join(",")}</span>
    </div>
  );
};

function renderGate() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PortalAccessGate>
        <Shell />
      </PortalAccessGate>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // The denial marker outlives a render, so it must not leak between tests.
  clearAccessDenial();
});

describe("PortalAccessGate", () => {
  it("renders the app for an authorized identity", async () => {
    (apiClient.get as any).mockResolvedValue({ data: AUTHORIZED });
    renderGate();
    expect(await screen.findByText("APP SHELL")).toBeTruthy();
  });

  it("blocks an authenticated but unauthorized identity", async () => {
    (apiClient.get as any).mockResolvedValue({ data: DENIED });
    renderGate();

    expect(await screen.findByText("Access Denied")).toBeTruthy();
    // The denial must name the actual cause — AD group membership — rather
    // than a generic "not authorized", which sends users to the wrong fix.
    expect(
      screen.getByText(/not a member of any Active Directory group/i)
    ).toBeTruthy();
    // The application shell must never mount for them.
    expect(screen.queryByText("APP SHELL")).toBeNull();
  });

  it("offers sign-out on denial so the user can switch accounts", async () => {
    (apiClient.get as any).mockResolvedValue({ data: DENIED });
    renderGate();

    const signOut = await screen.findByRole("button", { name: /sign out/i });
    signOut.click();
    expect(logoutRedirect).toHaveBeenCalled();
  });

  it("signs an unentitled session out on its own, without user action", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      (apiClient.get as any).mockResolvedValue({ data: DENIED });
      renderGate();

      await screen.findByText("Access Denied");
      // The user gets a beat to read why before being bounced.
      expect(logoutRedirect).not.toHaveBeenCalled();

      await act(async () => {
        vi.advanceTimersByTime(9000);
      });

      expect(logoutRedirect).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("records the denial so the login page can explain the sign-out", async () => {
    (apiClient.get as any).mockResolvedValue({ data: DENIED });
    renderGate();

    const signOut = await screen.findByRole("button", { name: /sign out/i });
    signOut.click();

    // Survives the round trip through Microsoft's end-session endpoint, which
    // destroys component state and cannot carry a query parameter.
    expect(peekAccessDenial()).toEqual({ email: "outsider@example.com" });
  });

  it("fires sign-out only once when the countdown and the button race", async () => {
    // MSAL rejects a second interaction while one is in flight, so a
    // double-fire would surface as an error on top of the denial.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      (apiClient.get as any).mockResolvedValue({ data: DENIED });
      renderGate();

      const signOut = await screen.findByRole("button", { name: /sign out/i });
      signOut.click();
      await act(async () => {
        vi.advanceTimersByTime(9000);
      });

      expect(logoutRedirect).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the signed-in address on denial to reveal a wrong-account login", async () => {
    (apiClient.get as any).mockResolvedValue({ data: DENIED });
    renderGate();
    expect(await screen.findByText("outsider@example.com")).toBeTruthy();
  });

  it("queries the session endpoint exactly once", async () => {
    (apiClient.get as any).mockResolvedValue({ data: AUTHORIZED });
    renderGate();
    await screen.findByText("APP SHELL");
    expect(apiClient.get).toHaveBeenCalledWith("/auth/session");
  });

  it("exposes backend capabilities to the app", async () => {
    (apiClient.get as any).mockResolvedValue({ data: AUTHORIZED });
    renderGate();
    expect(await screen.findByText("can-delete")).toBeTruthy();
  });

  it("does not grant a capability the backend withheld", async () => {
    (apiClient.get as any).mockResolvedValue({
      data: { ...AUTHORIZED, permissions: ["AKS_VIEW"] },
    });
    renderGate();
    expect(await screen.findByText("cannot-delete")).toBeTruthy();
  });

  it("distinguishes a backend failure from a denial", async () => {
    // Telling an entitled user they are unauthorized because of a transient
    // error would be its own outage — this must be a retryable error state.
    (apiClient.get as any).mockRejectedValue(new Error("network down"));
    renderGate();

    // The gate retries once with backoff before giving up, so allow for it.
    expect(
      await screen.findByText(/Unable to verify access/i, undefined, { timeout: 5000 })
    ).toBeTruthy();
    expect(screen.queryByText("Access Denied")).toBeNull();
    expect(screen.queryByText("APP SHELL")).toBeNull();
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("shows a checking state while the session resolves", async () => {
    let resolve: (v: unknown) => void = () => {};
    (apiClient.get as any).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      })
    );
    renderGate();

    expect(screen.getByText(/Checking portal access/i)).toBeTruthy();
    expect(screen.queryByText("APP SHELL")).toBeNull();

    resolve({ data: AUTHORIZED });
    await waitFor(() => expect(screen.getByText("APP SHELL")).toBeTruthy());
  });

  it("exposes subscription access and admin projects from the session", async () => {
    (apiClient.get as any).mockResolvedValue({
      data: { ...AUTHORIZED, is_admin: true, access: { has_subscription_access: true, admin_project_ids: [3, 7] } },
    });
    renderGate();
    expect(await screen.findByText("has-subscriptions")).toBeTruthy();
    expect(screen.getByText("not-super-admin")).toBeTruthy();
    expect(screen.getByText("admin-projects:3,7")).toBeTruthy();
  });

  it("reports a user with no grant as having no subscription access", async () => {
    (apiClient.get as any).mockResolvedValue({
      data: { ...AUTHORIZED, access: { has_subscription_access: false, admin_project_ids: [] } },
    });
    renderGate();
    expect(await screen.findByText("no-subscriptions")).toBeTruthy();
  });

  it("treats a Super Admin as unrestricted", async () => {
    (apiClient.get as any).mockResolvedValue({
      data: {
        ...AUTHORIZED,
        roles: ["super_admin"],
        is_admin: true,
        is_super_admin: true,
        access: { has_subscription_access: true, admin_project_ids: [], readable_count: null, writable_count: null },
      },
    });
    renderGate();
    expect(await screen.findByText("super-admin")).toBeTruthy();
    expect(screen.getByText("has-subscriptions")).toBeTruthy();
  });

  it("does not lock everyone out when an older backend omits the access block", async () => {
    const { access: _omitted, is_super_admin: _alsoOmitted, ...legacy } = AUTHORIZED;
    (apiClient.get as any).mockResolvedValue({ data: legacy });
    renderGate();
    expect(await screen.findByText("has-subscriptions")).toBeTruthy();
    expect(screen.getByText("not-super-admin")).toBeTruthy();
  });

  it("re-reads the session when an API reports no subscription access", async () => {
    (apiClient.get as any).mockResolvedValue({ data: AUTHORIZED });
    renderGate();
    await screen.findByText("has-subscriptions");
    expect(apiClient.get).toHaveBeenCalledTimes(1);

    // A grant was revoked mid-session; the next module call 403s.
    (apiClient.get as any).mockResolvedValue({
      data: { ...AUTHORIZED, access: { has_subscription_access: false, admin_project_ids: [] } },
    });
    act(() => {
      window.dispatchEvent(new Event(NO_SUBSCRIPTION_ACCESS_EVENT));
    });

    expect(await screen.findByText("no-subscriptions")).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("keeps the last known session when a background refresh fails", async () => {
    (apiClient.get as any).mockResolvedValue({ data: AUTHORIZED });
    renderGate();
    await screen.findByText("APP SHELL");

    (apiClient.get as any).mockRejectedValue(new Error("network blip"));
    act(() => {
      window.dispatchEvent(new Event(NO_SUBSCRIPTION_ACCESS_EVENT));
    });

    // Initial load, the refresh, and the gate's single retry — then it settles in error.
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(3), { timeout: 5000 });
    await act(async () => {});
    // The portal must not be replaced by "Unable to verify access" for a blip.
    expect(screen.getByText("APP SHELL")).toBeTruthy();
    expect(screen.queryByText(/Unable to verify access/i)).toBeNull();
  });
});
