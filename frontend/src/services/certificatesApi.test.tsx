import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./apiClient", () => ({
  default: {
    delete: vi.fn().mockResolvedValue({ data: { certificate_id: 7, deleted: true } }),
  },
}));

import {
  CertificateCollection,
  CollectionCertStats,
  useDeleteCertificate,
} from "./certificatesApi";

describe("useDeleteCertificate", () => {
  it("decrements the collection and every matching expiry tile", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const collections: CertificateCollection[] = [
      { id: 42, name: "Primary", description: "", certificate_count: 29 },
      { id: 43, name: "Other", description: "", certificate_count: 5 },
    ];
    queryClient.setQueryData(["certificates", "collections"], collections);
    queryClient.setQueryData<CollectionCertStats>(
      ["certificates", "collection-stats", 42],
      {
        total: 29,
        expired: 1,
        revoked: 2,
        deleted: 0,
        expiring30: 3,
        expiring60: 6,
        expiring90: 9,
      }
    );

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteCertificate(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        id: 7,
        collectionId: 42,
        notAfter: new Date(Date.now() + 45 * 86_400_000).toISOString(),
        revoked: false,
      });
    });

    expect(
      queryClient.getQueryData<CertificateCollection[]>(["certificates", "collections"])
    ).toEqual([
      { id: 42, name: "Primary", description: "", certificate_count: 28 },
      { id: 43, name: "Other", description: "", certificate_count: 5 },
    ]);
    expect(
      queryClient.getQueryData<CollectionCertStats>([
        "certificates",
        "collection-stats",
        42,
      ])
    ).toEqual({
      total: 28,
      expired: 1,
      revoked: 2,
      // Deleting moves the certificate into the soft-deleted set.
      deleted: 1,
      expiring30: 3,
      expiring60: 5,
      expiring90: 8,
    });
  });

  it("decrements all cumulative expiry tiles for a certificate within 30 days", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData<CollectionCertStats>(
      ["certificates", "collection-stats", 42],
      {
        total: 10,
        expired: 0,
        revoked: 0,
        deleted: 0,
        expiring30: 2,
        expiring60: 4,
        expiring90: 6,
      }
    );

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteCertificate(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        id: 8,
        collectionId: 42,
        notAfter: new Date(Date.now() + 15 * 86_400_000).toISOString(),
        revoked: false,
      });
    });

    expect(
      queryClient.getQueryData<CollectionCertStats>([
        "certificates",
        "collection-stats",
        42,
      ])
    ).toEqual({
      total: 9,
      expired: 0,
      revoked: 0,
      deleted: 1,
      expiring30: 1,
      expiring60: 3,
      expiring90: 5,
    });
  });
});