/**
 * Tools — credential checks.
 *
 * Secrets are sent once, over the portal's own API, and are never stored in
 * React Query state: the mutations below take the credential as an argument
 * and keep only the result. Do not add a query that caches a request body.
 *
 * There is no history endpoint — a check is not recorded anywhere.
 */

import { useMutation } from "@tanstack/react-query";
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

export interface DomainCheckInput {
  domain: DomainName;
  username: string;
  password: string;
}

export interface JFrogCheckInput {
  username: string;
  token: string;
}

export interface AafCheckInput {
  environment: AafEnvironment;
  account: string;
  password: string;
}

/** Shared by the three checks. Nothing is cached: the result is the answer. */
function useCheckMutation<TInput>(path: string) {
  return useMutation({
    mutationFn: async (input: TInput) => {
      const { data } = await apiClient.post<CredentialCheckResult>(`${BASE}/${path}`, input);
      return data;
    },
  });
}

export const useCheckDomainPassword = () => useCheckMutation<DomainCheckInput>("domain");
export const useCheckJFrogToken = () => useCheckMutation<JFrogCheckInput>("jfrog");
export const useCheckAafPassword = () => useCheckMutation<AafCheckInput>("aaf");
