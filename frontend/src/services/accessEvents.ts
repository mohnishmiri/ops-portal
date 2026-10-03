/**
 * accessEvents — signal that the backend refused a call because the user has
 * no subscription access.
 *
 * Every module API answers 403 "You do not have access to any subscription
 * yet. Request access from the Access page." when the caller holds no grant.
 * That can start mid-session (a grant is revoked, or the transition grant is
 * removed), long after the cached `/auth/session` said otherwise. apiClient
 * fires this window event on such a 403 so the session gate can re-read
 * `/auth/session` and module pages switch to the "request access" panel
 * instead of each showing its own load error.
 *
 * Kept dependency-free so it can be imported by apiClient and by contexts
 * (whose tests mock apiClient) without pulling either into the other.
 */

export const NO_SUBSCRIPTION_ACCESS_EVENT = "opsportal:no-subscription-access";

/** True for the backend's "no subscription yet — Request access" 403. */
export function isNoSubscriptionAccessError(error: unknown): boolean {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response;
  if (response?.status !== 403) return false;
  const detail = response.data?.detail;
  return typeof detail === "string" && detail.includes("Request access");
}

export function notifyNoSubscriptionAccess(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(NO_SUBSCRIPTION_ACCESS_EVENT));
}
