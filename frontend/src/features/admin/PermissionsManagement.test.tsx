/**
 * Tests for PermissionsManagement — focuses on the label-mapping helpers and
 * the Resources/Permissions/Matrix tab structure.
 *
 * The component depends on API queries so we mock the permissionsApi module
 * to return controlled data without hitting the network.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Mock the permissionsApi module ────────────────────────────────────────────
vi.mock("../../services/permissionsApi", () => ({
  useResources: vi.fn(),
  usePermissions: vi.fn(),
  useTeams: vi.fn(),
  useCreateResource: vi.fn(),
  useCreatePermission: vi.fn(),
  useDeleteResource: vi.fn(),
  useDeletePermission: vi.fn(),
}));

import * as permApi from "../../services/permissionsApi";
import PermissionsManagement from "./PermissionsManagement";

const MOCK_RESOURCES = [
  { id: 1, resource_type: "module", resource_name: "cost_management",
    description: "Cost mgmt", parent_id: null, route_path: null, is_system: true,
    created_at: null, updated_at: null },
  { id: 2, resource_type: "page",   resource_name: "leadership_dashboard",
    description: "Leadership", parent_id: 1, route_path: "/", is_system: true,
    created_at: null, updated_at: null },
  { id: 3, resource_type: "module", resource_name: "aks_operations",
    description: "AKS ops", parent_id: null, route_path: "/aks", is_system: true,
    created_at: null, updated_at: null },
  { id: 4, resource_type: "page",   resource_name: "aks_main",
    description: "AKS main page", parent_id: 3, route_path: "/aks", is_system: true,
    created_at: null, updated_at: null },
  { id: 5, resource_type: "module", resource_name: "custom_module",
    description: "Custom", parent_id: null, route_path: null, is_system: false,
    created_at: null, updated_at: null },
];

const MOCK_PERMISSIONS = [
  { id: 1, subject_type: "role", subject_id: "read",
    resource_id: 1, resource_name: "cost_management", resource_type: "module",
    permission_type: "view", created_at: null },
];

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function setup() {
  const qc = makeQueryClient();
  const mutationStub = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false };
  vi.mocked(permApi.useResources).mockReturnValue({ data: MOCK_RESOURCES, isLoading: false } as any);
  vi.mocked(permApi.usePermissions).mockReturnValue({ data: MOCK_PERMISSIONS, isLoading: false } as any);
  vi.mocked(permApi.useTeams).mockReturnValue({ data: [], isLoading: false } as any);
  vi.mocked(permApi.useCreateResource).mockReturnValue(mutationStub as any);
  vi.mocked(permApi.useCreatePermission).mockReturnValue(mutationStub as any);
  vi.mocked(permApi.useDeleteResource).mockReturnValue(mutationStub as any);
  vi.mocked(permApi.useDeletePermission).mockReturnValue(mutationStub as any);

  render(
    <QueryClientProvider client={qc}>
      <PermissionsManagement />
    </QueryClientProvider>
  );
}

// ── Label mapping tests (pure logic) ─────────────────────────────────────────

describe("Resource display labels", () => {
  it("maps known module names to friendly labels in the Resources tab", () => {
    setup();
    // Labels appear in both the table and the parent-module dropdown → getAllByText
    expect(screen.getAllByText("Cost Management").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AKS Operations").length).toBeGreaterThan(0);
  });

  it("maps known page names to friendly labels", () => {
    setup();
    expect(screen.getAllByText("Leadership Dashboard").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AKS Main").length).toBeGreaterThan(0);
  });

  it("shows the raw resource_name as mono key", () => {
    setup();
    // resource_name appears in table row AND in parent-module dropdown option
    expect(screen.getAllByText("cost_management").length).toBeGreaterThan(0);
    expect(screen.getAllByText("aks_operations").length).toBeGreaterThan(0);
  });

  it("marks system resources as protected (not deletable)", () => {
    setup();
    const protectedCells = screen.getAllByText("protected");
    expect(protectedCells.length).toBeGreaterThan(0);
  });

  it("marks non-system resource as custom", () => {
    setup();
    expect(screen.getByText("custom")).toBeInTheDocument();
  });
});

// ── Tab navigation ────────────────────────────────────────────────────────────

describe("Tab navigation", () => {
  it("renders Resources tab by default", () => {
    setup();
    expect(screen.getByText("Add Custom Resource")).toBeInTheDocument();
  });

  it("switches to Permissions tab", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Permissions" }));
    // "Grant Permission" is both a heading and a button — getAllByText is safe
    expect(screen.getAllByText("Grant Permission").length).toBeGreaterThan(0);
  });

  it("switches to Access Matrix tab", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Access Matrix" }));
    expect(screen.getByText("Role Access Matrix")).toBeInTheDocument();
  });

  it("shows admin/write/read columns in Matrix tab", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Access Matrix" }));
    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByText("write")).toBeInTheDocument();
    expect(screen.getByText("read")).toBeInTheDocument();
  });
});

// ── Permissions tab ───────────────────────────────────────────────────────────

describe("Permissions tab grant form", () => {
  it("shows subject type dropdown with Role and User options", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Permissions" }));
    const selects = screen.getAllByRole("combobox");
    expect(selects.length).toBeGreaterThan(0);
    // "Role" appears as the default option — may appear in multiple select elements
    expect(screen.getAllByText("Role").length).toBeGreaterThan(0);
  });

  it("shows resource dropdown with friendly labels grouped by type", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Permissions" }));
    // optgroup labels
    expect(screen.getByRole("group", { name: "Modules" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Pages" })).toBeInTheDocument();
  });

  it("shows existing permissions in the granted list", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Permissions" }));
    expect(screen.getByText("Granted Permissions")).toBeInTheDocument();
    // "read" appears as a dropdown option AND as the subject_id in the granted table
    expect(screen.getAllByText("read").length).toBeGreaterThan(0);
  });
});
