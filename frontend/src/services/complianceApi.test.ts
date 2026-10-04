import { describe, expect, it, vi } from "vitest";

vi.mock("./apiClient", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

import { summarizeChecksumRun, type ChecksumRunResponse } from "./complianceApi";

const base: ChecksumRunResponse = {
  run_id: "run-1",
  execution_date: "2026-10-05T00:00:00",
  total: 10,
  passed: 8,
  failed: 2,
  results: [],
};

describe("summarizeChecksumRun", () => {
  it("keeps the run id of a single-workspace run and mentions the emailed report", () => {
    const summary = summarizeChecksumRun(base, "ops@example.com");
    expect(summary.runId).toBe("run-1");
    expect(summary.message).toBe("Verification complete: 8 PASS, 2 FAIL — report emailed to ops@example.com");
    expect(summary.type).toBe("warning");
  });

  it("reports a failed run as an error instead of '0 PASS, 0 FAIL'", () => {
    const summary = summarizeChecksumRun(
      { ...base, passed: 0, failed: 0, status: "failed", error: "Workspace unreachable" },
      "ops@example.com",
    );
    expect(summary).toEqual({ runId: null, message: "Workspace unreachable", type: "error" });
  });

  it("drops the unsaved batch run id and reports unreachable workspaces", () => {
    const summary = summarizeChecksumRun(
      { ...base, run_id: "batch-x", mode: "batch", module_type: "synapse", workspaces_processed: 5, workspaces_failed: 1 },
      "ops@example.com",
    );
    expect(summary.runId).toBeNull();
    expect(summary.message).toBe(
      "Verification complete across 5 workspace(s): 8 PASS, 2 FAIL — 1 workspace(s) could not be verified",
    );
    expect(summary.message).not.toContain("emailed");
    expect(summary.type).toBe("warning");
  });

  it("labels AKS batch runs by cluster", () => {
    const summary = summarizeChecksumRun({
      ...base,
      failed: 0,
      passed: 10,
      mode: "batch",
      module_type: "aks",
      clusters_processed: 3,
      clusters_failed: 0,
    });
    expect(summary.message).toBe("Verification complete across 3 cluster(s): 10 PASS, 0 FAIL");
    expect(summary.type).toBe("success");
  });
});
