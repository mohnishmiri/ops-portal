/**
 * The shared date formatters: zone-less API timestamps are UTC, and a
 * date-only value keeps its calendar day in every timezone.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(async () => ({ data: { timezone: "America/Chicago" } })) },
}));

import { TimezoneProvider, usePortalTimezone } from "../contexts/TimezoneContext";
import { formatDateTime, isDateOnly, parseApiDate } from "./dateFormat";

describe("parseApiDate", () => {
  it("reads zone-less timestamps as UTC, not browser-local time", () => {
    expect(parseApiDate("2026-10-07T03:00:00")?.toISOString()).toBe("2026-10-07T03:00:00.000Z");
    expect(parseApiDate("2026-10-07T03:00:00.123456")?.toISOString()).toBe("2026-10-07T03:00:00.123Z");
    // Python's str(datetime) uses a space instead of "T".
    expect(parseApiDate("2026-10-07 03:00:00")?.toISOString()).toBe("2026-10-07T03:00:00.000Z");
  });

  it("keeps an explicit zone", () => {
    expect(parseApiDate("2026-10-07T03:00:00Z")?.toISOString()).toBe("2026-10-07T03:00:00.000Z");
    expect(parseApiDate("2026-10-07T03:00:00+05:30")?.toISOString()).toBe("2026-10-06T21:30:00.000Z");
  });

  it("returns null for empty or unparseable values", () => {
    expect(parseApiDate(null)).toBeNull();
    expect(parseApiDate("")).toBeNull();
    expect(parseApiDate("garbage")).toBeNull();
    expect(parseApiDate(new Date("nope"))).toBeNull();
  });

  it("recognises date-only values", () => {
    expect(isDateOnly("2026-10-07")).toBe(true);
    expect(isDateOnly("2026-10-07T00:00:00")).toBe(false);
    expect(isDateOnly(null)).toBe(false);
  });
});

describe("formatDateTime", () => {
  it("shows the same instant whether or not the API sent a zone", () => {
    expect(formatDateTime("2026-10-07T03:00:00")).toBe(formatDateTime("2026-10-07T03:00:00Z"));
    expect(formatDateTime("garbage")).toBe("garbage");
  });
});

describe("usePortalTimezone", () => {
  function wrapper({ children }: { children: React.ReactNode }) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return (
      <QueryClientProvider client={qc}>
        <TimezoneProvider>{children}</TimezoneProvider>
      </QueryClientProvider>
    );
  }

  it("converts zone-less UTC timestamps into the portal timezone", async () => {
    const { result } = renderHook(() => usePortalTimezone(), { wrapper });
    await waitFor(() => expect(result.current.timezone).toBe("America/Chicago"));

    // 03:00 UTC is 22:00 the previous evening in Chicago (CDT, UTC-5).
    expect(result.current.formatDate("2026-10-07T03:00:00")).toMatch(/Oct 6, 2026.*10:00:00\sPM/);
    expect(result.current.formatDate("2026-10-07T03:00:00")).toBe(result.current.formatDate("2026-10-07T03:00:00Z"));
    expect(result.current.formatShortDate("2026-10-07T03:00:00")).toBe("Oct 6, 2026");
  });

  it("keeps a date-only value's calendar day", async () => {
    const { result } = renderHook(() => usePortalTimezone(), { wrapper });
    await waitFor(() => expect(result.current.timezone).toBe("America/Chicago"));

    expect(result.current.formatShortDate("2026-10-07")).toBe("Oct 7, 2026");
    expect(result.current.formatDate("2026-10-07")).toBe("Oct 7, 2026");
  });

  it("shows unparseable values as they are", async () => {
    const { result } = renderHook(() => usePortalTimezone(), { wrapper });
    await waitFor(() => expect(result.current.timezone).toBe("America/Chicago"));

    expect(result.current.formatDate("not a date")).toBe("not a date");
    expect(result.current.formatShortDate(null)).toBe("—");
  });
});
