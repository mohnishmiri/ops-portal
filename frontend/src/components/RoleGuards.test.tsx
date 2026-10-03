/**
 * Tests for the role-gated routes.
 *
 * The portal-wide admin console (/admin, /admin/permissions) is Super Admin
 * only on the backend. A Project Admin (Entra Admin role, is_admin=true) must
 * get a clear denial pointing at Access Management — not a console whose
 * every call 403s. Access Management itself is for Super Admins and admins of
 * at least one project.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import React from "react";

vi.mock("../contexts/SessionContext", () => ({ useSession: vi.fn() }));

import { useSession } from "../contexts/SessionContext";
import { AccessAdminRoute, SuperAdminRoute } from "./RoleGuards";

const CONSOLE = "ADMIN CONSOLE";
const MANAGE = "ACCESS MANAGEMENT";

function mockSession(overrides: { isSuperAdmin?: boolean; adminProjectIds?: number[]; isAdmin?: boolean } = {}) {
  const { isSuperAdmin = false, adminProjectIds = [], isAdmin = false } = overrides;
  vi.mocked(useSession).mockReturnValue({
    session: {
      authenticated: true,
      authorized: true,
      roles: isSuperAdmin ? ["super_admin"] : isAdmin ? ["admin"] : ["write"],
      is_admin: isSuperAdmin || isAdmin,
      is_super_admin: isSuperAdmin,
      can_write: true,
      permissions: [],
    },
    hasCapability: () => false,
    isSuperAdmin,
    hasSubscriptionAccess: true,
    adminProjectIds,
    refreshSession: vi.fn(),
  });
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/admin"
          element={
            <SuperAdminRoute label="Admin Dashboard">
              <div>{CONSOLE}</div>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/admin/permissions"
          element={
            <SuperAdminRoute label="Access Control">
              <div>{CONSOLE}</div>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/access/manage"
          element={
            <AccessAdminRoute label="Access Management">
              <div>{MANAGE}</div>
            </AccessAdminRoute>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SuperAdminRoute — admin console", () => {
  it("opens /admin for a Super Admin", () => {
    mockSession({ isSuperAdmin: true });
    renderAt("/admin");
    expect(screen.getByText(CONSOLE)).toBeInTheDocument();
  });

  it("denies /admin to a Project Admin and points to Access Management", () => {
    mockSession({ isAdmin: true, adminProjectIds: [1] });
    renderAt("/admin");
    expect(screen.queryByText(CONSOLE)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
    expect(screen.getByText("Admin Dashboard")).toBeInTheDocument();
    expect(screen.getByText(/limited to Super Admins/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Access Management" })).toHaveAttribute("href", "/access/manage");
  });

  it("denies /admin to an Entra Admin with no assigned project", () => {
    mockSession({ isAdmin: true });
    renderAt("/admin");
    expect(screen.queryByText(CONSOLE)).not.toBeInTheDocument();
    expect(screen.getByText(/limited to Super Admins \(an Entra-only role\)/i)).toBeInTheDocument();
  });

  it("denies /admin/permissions to anyone but a Super Admin", () => {
    mockSession({ isAdmin: true, adminProjectIds: [1] });
    renderAt("/admin/permissions");
    expect(screen.queryByText(CONSOLE)).not.toBeInTheDocument();
    expect(screen.getByText("Access Control")).toBeInTheDocument();
  });
});

describe("AccessAdminRoute — Access Management", () => {
  it("opens for a Super Admin", () => {
    mockSession({ isSuperAdmin: true });
    renderAt("/access/manage");
    expect(screen.getByText(MANAGE)).toBeInTheDocument();
  });

  it("opens for an admin of at least one project", () => {
    mockSession({ isAdmin: true, adminProjectIds: [3] });
    renderAt("/access/manage");
    expect(screen.getByText(MANAGE)).toBeInTheDocument();
  });

  it("denies a regular user and points to My Access", () => {
    mockSession();
    renderAt("/access/manage");
    expect(screen.queryByText(MANAGE)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My Access" })).toHaveAttribute("href", "/access");
  });
});
