/**
 * Tools — credential checks.
 *
 * Secrets are sent once, over the portal's own API, and are never stored in
 * React Query state: the mutations below take the credential as an argument
 * and keep only the result. Do not add a query that caches a request body.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

const BASE = "/tools/credential-checks";

export type CheckKind = "domain" | "jfrog" | "aaf";
export type DomainName = "ITSERVICES" | "TESTITSERVICES";
export type AafEnvironment = "prod" | "nonprod";

export interface CredentialCheckResult {
  kind: CheckKind;
  target: string;
  valid: boolean;
  /** valid | invalid | expired | locked | disabled | must_change | denied | error */
  status: string;
  message: string;
  checked_at: string;
  details: Record<string, unknown>;
}

export interface CredentialCheckHistoryEntry {
  id: number;
  checked_at: string | null;
  user_email: string | null;
  target: string | null;
  kind: string;
  status: string;
  message: string;
  valid: boolean;
}

export interface DomainCheckInput {
  domain: DomainName;
  username: string;
  password: string;
}

export interface JFrogCheckInput {
  token: string;
}

export interface AafCheckInput {
  environment: AafEnvironment;
  account: string;
  password: string;
}

export const credentialCheckKeys = {
  history: ["tools", "credential-checks", "history"] as const,
};

export function useCredentialCheckHistory(enabled = true) {
  return useQuery({
    queryKey: credentialCheckKeys.history,
    queryFn: async () => {
      const { data } = await apiClient.get<CredentialCheckHistoryEntry[]>(`${BASE}/history`);
      return data;
    },
    enabled,
    staleTime: 30_000,
  });
}

/** Shared by the three checks: run it, then refresh the history grid. */
function useCheckMutation<TInput>(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: TInput) => {
      const { data } = await apiClient.post<CredentialCheckResult>(`${BASE}/${path}`, input);
      return data;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: credentialCheckKeys.history });
    },
  });
}

export const useCheckDomainPassword = () => useCheckMutation<DomainCheckInput>("domain");
export const useCheckJFrogToken = () => useCheckMutation<JFrogCheckInput>("jfrog");
export const useCheckAafPassword = () => useCheckMutation<AafCheckInput>("aaf");
