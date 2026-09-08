/**
 * accessDenial — hand-off between the portal denial screen and the login page.
 *
 * When an authenticated identity holds no Ops Portal app role,
 * `PortalAccessDenied` signs it out rather than leaving it parked on a shell
 * with no working pages. That sign-out is a full round trip through
 * Microsoft's end-session endpoint, so no component state survives it — and
 * without a hand-off the user lands back on the login page with no idea why.
 *
 * The reason cannot ride on the URL: `postLogoutRedirectUri` is the bare path
 * "/" registered in the App Registration, and Azure AD validates the
 * post-logout redirect against that list, so appending a query string risks
 * the redirect being rejected outright.
 *
 * So it is parked in sessionStorage, which survives the cross-origin round
 * trip within the same tab while still dying with the tab. The marker is
 * timestamped and TTL-checked on read, so a forgotten flag can never make a
 * healthy sign-in look like a denial.
 *
 * This is presentation only. Authorization itself is enforced by the backend
 * on every request; nothing here grants or withholds access.
 */

const DENIAL_KEY = "opsPortal.accessDenied";

/** How long a parked denial marker stays meaningful. */
const DENIAL_TTL_MS = 5 * 60 * 1000;

interface DenialMarker {
  email?: string;
  /** Epoch ms the denial was recorded, used to expire stale markers. */
  at: number;
}

/** Record that the sign-out now in flight was caused by an access denial. */
export function markAccessDenied(email?: string): void {
  try {
    const marker: DenialMarker = { email, at: Date.now() };
    sessionStorage.setItem(DENIAL_KEY, JSON.stringify(marker));
  } catch {
    // Private browsing or a full quota. The banner is a courtesy, not a
    // control, so failing to record it must never block the sign-out.
  }
}

/**
 * Read a fresh denial marker, if one is present.
 *
 * Deliberately non-mutating so it is safe to call during render and under
 * React StrictMode's double-mount. Clearing is an explicit, separate step —
 * see `clearAccessDenial`.
 */
export function peekAccessDenial(): { email?: string } | null {
  try {
    const raw = sessionStorage.getItem(DENIAL_KEY);
    if (!raw) return null;

    const marker = JSON.parse(raw) as DenialMarker;
    if (typeof marker?.at !== "number") return null;
    if (Date.now() - marker.at > DENIAL_TTL_MS) {
      sessionStorage.removeItem(DENIAL_KEY);
      return null;
    }
    return { email: marker.email };
  } catch {
    return null;
  }
}

/**
 * Drop the marker.
 *
 * Called when the user starts a fresh sign-in, so the previous denial notice
 * does not follow them into the next attempt.
 */
export function clearAccessDenial(): void {
  try {
    sessionStorage.removeItem(DENIAL_KEY);
  } catch {
    // Nothing to do — a marker we cannot clear will expire via the TTL.
  }
}
