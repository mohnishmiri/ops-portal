/**
 * Tests for ProtectedRoute component.
 *
 * ProtectedRoute depends on three contexts (AuthContext + PermissionsContext
 * + SessionContext), so all are mocked to control the scenario under test.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

// ── Mock contexts ─────────────────────────────────────────────────────────────

vi.mock("../contexts/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../contexts/PermissionsContext", () => ({
  usePermissions: vi.fn(),
}));

vi.mock("../contexts/SessionContext", () => ({
  useSession: vi.fn(),
}));

import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import { useSession } from "../contexts/SessionContext";
import ProtectedRoute from "./ProtectedRoute";

const PAGE_CONTENT = "Protected Page Content";

function mockSession(overrides: { isSuperAdmin?: boolean; hasSubscriptionAccess?: boolean } = {}) {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    hasCapability: () => true,
    isSuperAdmin: false,
    hasSubscriptionAccess: true,
    adminProjectIds: [],
    refreshSession: vi.fn(),
    ...overrides,
  });
}

function setup(authOverrides = {}, permOverrides = {}, sessionOverrides = {}) {
  mockSession(sessionOverrides);
  vi.mocked(useAuth).mockReturnValue({ isAdmin: false, ...authOverrides } as any);
  vi.mocked(usePermissions).mockReturnValue({
    isLoading: false,
    canViewModule: () => true,
    canViewPage: () => true,
    ...permOverrides,
  } as any);

  render(
    <MemoryRouter>
      <ProtectedRoute module="aks_operations" page="aks_main" label="AKS Operations">
        <div>{PAGE_CONTENT}</div>
      </ProtectedRoute>
    </MemoryRouter>
  );
}

describe("ProtectedRoute — admin bypass", () => {
  it("renders children immediately for admin users regardless of permissions", () => {
    setup({ isAdmin: true });
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });
});

describe("ProtectedRoute — loading state", () => {
  it("shows a spinner while permissions are loading", () => {
    setup({}, { isLoading: true });
    // Children should not be visible yet
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    // A spinner element is rendered (div with animate-spin class)
    const spinner = document.querySelector(".animate-spin");
    expect(spinner).toBeInTheDocument();
  });
});

describe("ProtectedRoute — access granted", () => {
  it("renders children when module and page access is granted", () => {
    setup({}, { canViewModule: () => true, canViewPage: () => true });
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });
});

describe("ProtectedRoute — access denied", () => {
  it("shows AccessDenied when module access is denied", () => {
    setup({}, { canViewModule: () => false, canViewPage: () => true });
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
    expect(screen.getByText("AKS Operations")).toBeInTheDocument();
  });

  it("shows AccessDenied when page access is denied", () => {
    setup({}, { canViewModule: () => true, canViewPage: () => false });
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
  });

  it("uses label prop in the denied message", () => {
    setup({}, { canViewModule: () => false });
    expect(screen.getByText("AKS Operations")).toBeInTheDocument();
  });
});

describe("ProtectedRoute — no subscription access", () => {
  const NO_ACCESS = /You don.t have access to any subscription yet/i;

  it("shows the request-access panel instead of loading the page", () => {
    setup({}, {}, { hasSubscriptionAccess: false });
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: NO_ACCESS })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /request access/i })).toHaveAttribute("href", "/access");
  });

  it("applies to admins too — a Project Admin's access comes from projects, not the Entra role", () => {
    setup({ isAdmin: true }, {}, { hasSubscriptionAccess: false });
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: NO_ACCESS })).toBeInTheDocument();
  });

  it("never blocks a Super Admin", () => {
    setup({ isAdmin: true }, {}, { isSuperAdmin: true, hasSubscriptionAccess: false });
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });

  it("keeps Access Denied for a page the user may not open at all", () => {
    setup({}, { canViewModule: () => false }, { hasSubscriptionAccess: false });
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: NO_ACCESS })).not.toBeInTheDocument();
  });

  it("re-checks the session from the panel", () => {
    const refreshSession = vi.fn();
    setup({}, {}, { hasSubscriptionAccess: false, refreshSession });
    screen.getByRole("button", { name: /check again/i }).click();
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });
});

describe("ProtectedRoute — no module or page specified", () => {
  it("renders children when no module/page guards are specified", () => {
    mockSession({ hasSubscriptionAccess: false });
    vi.mocked(useAuth).mockReturnValue({ isAdmin: false } as any);
    vi.mocked(usePermissions).mockReturnValue({
      isLoading: false,
      canViewModule: () => false,
      canViewPage: () => false,
    } as any);

    render(
      <MemoryRouter>
        <ProtectedRoute>
          <div>{PAGE_CONTENT}</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    // No module/page → open route, children always shown
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });
});
