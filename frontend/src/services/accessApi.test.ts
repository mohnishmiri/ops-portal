/**
 * Tests for the access API's request-item building and request helpers.
 *
 * A request form selection (projects and/or apps, Prod / Non-Prod, a level)
 * must become exactly one backend item per project/app × tier — approvers
 * decide each line separately, so a missing or duplicated line is a wrong
 * grant or a confusing queue.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("./apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import apiClient from "./apiClient";
import {
  type AccessRequest,
  type CatalogProject,
  accessApi,
  buildRequestItems,
  clampLevel,
  isCancellable,
} from "./accessApi";

const CATALOG: CatalogProject[] = [
  {
    id: 1,
    name: "Commissions",
    description: null,
    apps: [
      { id: 10, name: "ATTCC", app_code: "31599", tiers: ["prod", "nonprod"] },
      { id: 11, name: "DWS", app_code: "17805", tiers: ["nonprod"] },
    ],
  },
  { id: 2, name: "BDS", description: null, apps: [{ id: 20, name: "HZNREP", app_code: "40001", tiers: ["prod"] }] },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("buildRequestItems", () => {
  it("creates one project item per tier", () => {
    expect(buildRequestItems({ projectIds: [1], appIds: [], tiers: ["prod", "nonprod"], level: "read" })).toEqual([
      { scope_type: "project", project_id: 1, tier: "prod", level: "read" },
      { scope_type: "project", project_id: 1, tier: "nonprod", level: "read" },
    ]);
  });

  it("creates one app item per tier, carrying app_id only", () => {
    expect(buildRequestItems({ projectIds: [], appIds: [10], tiers: ["nonprod"], level: "write" })).toEqual([
      { scope_type: "app", app_id: 10, tier: "nonprod", level: "write" },
    ]);
  });

  it("crosses every project and app with every tier", () => {
    const items = buildRequestItems({ projectIds: [2], appIds: [10, 11], tiers: ["prod", "nonprod"], level: "read" });
    expect(items).toHaveLength(6);
    expect(items.filter((item) => item.scope_type === "project")).toHaveLength(2);
    expect(items.filter((item) => item.scope_type === "app" && item.app_id === 10).map((i) => i.tier)).toEqual([
      "prod",
      "nonprod",
    ]);
  });

  it("emits tiers in canonical order and drops duplicates", () => {
    const items = buildRequestItems({
      projectIds: [1, 1],
      appIds: [20, 20],
      tiers: ["nonprod", "prod", "nonprod"],
      level: "read",
    });
    expect(items.map((item) => `${item.scope_type}:${item.project_id ?? item.app_id}:${item.tier}`)).toEqual([
      "project:1:prod",
      "project:1:nonprod",
      "app:20:prod",
      "app:20:nonprod",
    ]);
  });

  it("skips apps already covered by a selected project when the catalog is known", () => {
    const items = buildRequestItems({ projectIds: [1], appIds: [10, 20], tiers: ["prod"], level: "read" }, CATALOG);
    expect(items).toEqual([
      { scope_type: "project", project_id: 1, tier: "prod", level: "read" },
      { scope_type: "app", app_id: 20, tier: "prod", level: "read" },
    ]);
  });

  it("returns nothing without a tier or a target", () => {
    expect(buildRequestItems({ projectIds: [1], appIds: [10], tiers: [], level: "read" })).toEqual([]);
    expect(buildRequestItems({ projectIds: [], appIds: [], tiers: ["prod"], level: "read" })).toEqual([]);
  });
});

describe("clampLevel", () => {
  it("caps a read-role user at read", () => {
    expect(clampLevel("write", "read")).toBe("read");
    expect(clampLevel("read", "read")).toBe("read");
  });

  it("leaves a write-role user's choice alone", () => {
    expect(clampLevel("write", "write")).toBe("write");
    expect(clampLevel("read", "write")).toBe("read");
  });
});

describe("isCancellable", () => {
  const base: AccessRequest = {
    id: 1,
    requester_id: "u1",
    requester_email: "u1@example.com",
    requester_name: "User One",
    justification: "on-call support",
    status: "pending",
    created_at: null,
    updated_at: null,
    items: [],
  };
  const item = (status: "pending" | "approved" | "rejected" | "cancelled") => ({
    id: Math.random(),
    scope_type: "project" as const,
    project_id: 1,
    project_name: "Commissions",
    app_id: null,
    app_name: null,
    tier: "prod" as const,
    requested_level: "read" as const,
    status,
    granted_level: null,
    decided_by: null,
    decided_at: null,
    decision_comment: null,
    can_decide: false,
  });

  it("allows cancelling while every line is pending", () => {
    expect(isCancellable({ ...base, items: [item("pending"), item("pending")] })).toBe(true);
  });

  it("refuses once any line was decided, even though the request is still pending", () => {
    expect(isCancellable({ ...base, items: [item("pending"), item("approved")] })).toBe(false);
  });

  it("refuses a request that is no longer pending", () => {
    expect(isCancellable({ ...base, status: "cancelled", items: [item("cancelled")] })).toBe(false);
  });
});

describe("accessApi calls", () => {
  it("posts the built items with the justification", async () => {
    (apiClient.post as any).mockResolvedValue({ data: { id: 7, items: [] } });
    const items = buildRequestItems({ projectIds: [1], appIds: [20], tiers: ["prod"], level: "read" }, CATALOG);
    await accessApi.submitRequest({ justification: "Need ATTCC prod for releases", items });
    expect(apiClient.post).toHaveBeenCalledWith("/access/requests", {
      justification: "Need ATTCC prod for releases",
      items: [
        { scope_type: "project", project_id: 1, tier: "prod", level: "read" },
        { scope_type: "app", app_id: 20, tier: "prod", level: "read" },
      ],
    });
  });

  it("sends a per-item decision to the item route", async () => {
    (apiClient.post as any).mockResolvedValue({ data: {} });
    await accessApi.decideItem(3, 9, { decision: "approve", level: "read", comment: "ok" });
    expect(apiClient.post).toHaveBeenCalledWith("/access/admin/requests/3/items/9/decision", {
      decision: "approve",
      level: "read",
      comment: "ok",
    });
  });

  it("omits empty grant filters", async () => {
    (apiClient.get as any).mockResolvedValue({ data: [] });
    await accessApi.getGrants({});
    expect(apiClient.get).toHaveBeenCalledWith("/access/admin/grants", { params: {} });
    await accessApi.getGrants({ project_id: 4, user_id: "u9" });
    expect(apiClient.get).toHaveBeenLastCalledWith("/access/admin/grants", { params: { project_id: 4, user_id: "u9" } });
  });
});
