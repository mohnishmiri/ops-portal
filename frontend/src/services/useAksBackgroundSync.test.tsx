import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "./apiClient";
import { useAksBackgroundSync } from "./aksApi";

// Regression coverage for the "Sync from Azure" / "Syncing…" button spinning
// forever. The hook must always clear `isRunning` even when the background job
// never reaches a terminal status or the status poll keeps failing.

vi.mock("./apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

const mockedClient = apiClient as unknown as {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
};

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.useFakeTimers();
  mockedClient.get.mockReset();
  mockedClient.post.mockReset();
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

describe("useAksBackgroundSync recovery guards", () => {
  it("stops spinning when a job stays 'running' past the watchdog window", async () => {
    mockedClient.post.mockResolvedValue({
      data: { job_id: 1, status: "queued", job_type: "aks_resource_sync", idempotency_key: "k", reused: false },
    });
    // The job never reaches a terminal status — always reports "running".
    mockedClient.get.mockResolvedValue({
      data: { id: 1, job_type: "aks_resource_sync", status: "running", attempts: 1 },
    });

    const { result } = renderHook(
      () => useAksBackgroundSync({ resourceType: "clusters", auto: false }),
      { wrapper },
    );

    await act(async () => {
      result.current.start(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });

    // Spinner is on while the job is running.
    expect(result.current.isRunning).toBe(true);

    // After the watchdog window the hook gives up and clears the spinner.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    });

    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeTruthy();
  });

  it("stops spinning when the status poll keeps failing", async () => {
    mockedClient.post.mockResolvedValue({
      data: { job_id: 2, status: "queued", job_type: "aks_resource_sync", idempotency_key: "k", reused: false },
    });
    mockedClient.get.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(
      () => useAksBackgroundSync({ resourceType: "clusters", auto: false }),
      { wrapper },
    );

    await act(async () => {
      result.current.start(true);
    });
    await act(async () => {
      // Let the failing poll exhaust its retries, then the error guard fires.
      await vi.advanceTimersByTimeAsync(30 * 1000);
    });

    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeTruthy();
  });

  it("clears the spinner and clears error when the job completes", async () => {
    mockedClient.post.mockResolvedValue({
      data: { job_id: 3, status: "queued", job_type: "aks_resource_sync", idempotency_key: "k", reused: false },
    });
    mockedClient.get.mockResolvedValue({
      data: { id: 3, job_type: "aks_resource_sync", status: "completed", attempts: 1 },
    });

    const { result } = renderHook(
      () => useAksBackgroundSync({ resourceType: "clusters", auto: false }),
      { wrapper },
    );

    await act(async () => {
      result.current.start(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });

    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});
