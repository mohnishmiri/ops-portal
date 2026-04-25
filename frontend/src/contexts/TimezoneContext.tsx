/**
 * TimezoneContext — portal-wide timezone for date display.
 *
 * Fetches the admin-configured IANA timezone from
 * GET /admin/portal-timezone and exposes it via React context so every
 * grid, tooltip, and label can render dates in the same zone.
 */

import React, { createContext, useContext, useMemo } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import apiClient from "../services/apiClient";

// ── Common IANA timezone options offered in the Admin panel ────────────

export const TIMEZONE_OPTIONS: { value: string; label: string }[] = [
  { value: "UTC", label: "UTC (Coordinated Universal Time)" },
  { value: "America/New_York", label: "US Eastern (ET)" },
  { value: "America/Chicago", label: "US Central (CT)" },
  { value: "America/Denver", label: "US Mountain (MT)" },
  { value: "America/Los_Angeles", label: "US Pacific (PT)" },
  { value: "America/Anchorage", label: "US Alaska (AKT)" },
  { value: "Pacific/Honolulu", label: "US Hawaii (HST)" },
  { value: "America/Phoenix", label: "US Arizona (MST, no DST)" },
  { value: "Europe/London", label: "London (GMT/BST)" },
  { value: "Europe/Berlin", label: "Central Europe (CET/CEST)" },
  { value: "Asia/Kolkata", label: "India (IST)" },
  { value: "Asia/Tokyo", label: "Japan (JST)" },
  { value: "Asia/Shanghai", label: "China (CST)" },
  { value: "Australia/Sydney", label: "Sydney (AEST/AEDT)" },
];

// ── Context type ──────────────────────────────────────────────────────

interface TimezoneCtx {
  /** IANA timezone string, e.g. "America/Chicago" */
  timezone: string;
  /** Is the initial fetch still in flight? */
  isLoading: boolean;
  /** Format an ISO date string (or Date) for grid / label display. */
  formatDate: (value: string | Date | null | undefined) => string;
  /** Short date-only format (no time). */
  formatShortDate: (value: string | Date | null | undefined) => string;
}

const TimezoneContext = createContext<TimezoneCtx>({
  timezone: "UTC",
  isLoading: true,
  formatDate: () => "",
  formatShortDate: () => "",
});

// ── Provider ──────────────────────────────────────────────────────────

export const TimezoneProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { data, isLoading } = useQuery<{ timezone: string }>({
    queryKey: ["admin", "portal-timezone"],
    queryFn: async () => {
      const { data } = await apiClient.get("/admin/portal-timezone");
      return data;
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: true,
  });

  const timezone = data?.timezone ?? "UTC";

  const ctx = useMemo<TimezoneCtx>(() => {
    const formatDate = (value: string | Date | null | undefined): string => {
      if (!value) return "—";
      try {
        return new Date(value as string).toLocaleString(undefined, {
          timeZone: timezone,
          year: "numeric",
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          timeZoneName: "short",
        });
      } catch {
        return String(value);
      }
    };

    const formatShortDate = (value: string | Date | null | undefined): string => {
      if (!value) return "—";
      try {
        return new Date(value as string).toLocaleDateString(undefined, {
          timeZone: timezone,
          year: "numeric",
          month: "short",
          day: "numeric",
        });
      } catch {
        return String(value);
      }
    };

    return { timezone, isLoading, formatDate, formatShortDate };
  }, [timezone, isLoading]);

  return <TimezoneContext.Provider value={ctx}>{children}</TimezoneContext.Provider>;
};

// ── Hooks ─────────────────────────────────────────────────────────────

/** Read the portal timezone and formatting helpers. */
export function usePortalTimezone() {
  return useContext(TimezoneContext);
}

/** Mutation to update the portal timezone (admin only). */
export function useUpdatePortalTimezone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tz: string) => {
      const { data } = await apiClient.put("/admin/config", {
        config_key: "portal_timezone",
        config_value: tz,
        config_type: "string",
        description: "IANA timezone for portal-wide date display",
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "portal-timezone"] });
      qc.invalidateQueries({ queryKey: ["admin", "config"] });
    },
  });
}
