/**
 * Certificate lists must refresh when a background sync finishes.
 *
 * Renew/enroll/revoke kick off a fire-and-forget sync and return immediately, so
 * the invalidation those mutations fire refetches data the sync has not rebuilt
 * yet. Without a second refresh on completion a renewal left the collection tile
 * showing its old count until the page was reloaded.
 *
 * These cover the two decisions that drive that refresh. The effect wiring
 * itself is not asserted here: React Query observers do not re-render under this
 * repo's Vitest pool, so a test cannot observe the transition it depends on.
 */

import { describe, expect, it } from "vitest";

import { CertificateSyncStatus, isRefreshableAfterSync, isSyncRunning } from "./certificatesApi";

const status = (s: string) =>
  ({
    certificates_in_db: 271,
    collections_in_db: 9,
    recent_syncs: [{ status: s }],
  }) as unknown as CertificateSyncStatus;

describe("isSyncRunning", () => {
  it("is true while the latest run is in progress", () => {
    expect(isSyncRunning(status("running"))).toBe(true);
  });

  it("is false once the run finishes, which is what triggers the refresh", () => {
    expect(isSyncRunning(status("completed"))).toBe(false);
    expect(isSyncRunning(status("partial"))).toBe(false);
    expect(isSyncRunning(status("failed"))).toBe(false);
  });

  it("is false before any sync has been recorded", () => {
    expect(isSyncRunning(undefined)).toBe(false);
    expect(isSyncRunning({ recent_syncs: [] } as unknown as CertificateSyncStatus)).toBe(false);
  });
});

describe("isRefreshableAfterSync", () => {
  it("refreshes the data a sync rebuilds", () => {
    // The collection tile and the grid are the two that disagreed.
    expect(isRefreshableAfterSync(["certificates", "collections"])).toBe(true);
    expect(isRefreshableAfterSync(["certificates", "list", { collection_id: 2573 }])).toBe(true);
    expect(isRefreshableAfterSync(["certificates", "collection-stats", 2573])).toBe(true);
  });

  it("excludes the sync status, which would loop", () => {
    // Invalidating it from its own completion handler refetches it, which
    // re-evaluates the handler.
    expect(isRefreshableAfterSync(["certificates", "sync-status"])).toBe(false);
  });

  it("leaves unrelated modules alone", () => {
    expect(isRefreshableAfterSync(["keyvault", "list"])).toBe(false);
    expect(isRefreshableAfterSync(["aks", "clusters"])).toBe(false);
  });
});
