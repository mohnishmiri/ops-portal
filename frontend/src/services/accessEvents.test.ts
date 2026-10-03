/**
 * Tests for the "no subscription access" 403 detection that lets the session
 * gate refresh when a grant disappears mid-session.
 */

import { describe, it, expect, vi } from "vitest";
import { NO_SUBSCRIPTION_ACCESS_EVENT, isNoSubscriptionAccessError, notifyNoSubscriptionAccess } from "./accessEvents";

const forbidden = (detail: unknown) => ({ response: { status: 403, data: { detail } } });

describe("isNoSubscriptionAccessError", () => {
  it("recognises the backend's no-subscription 403", () => {
    expect(
      isNoSubscriptionAccessError(
        forbidden("You do not have access to any subscription yet. Request access from the Access page."),
      ),
    ).toBe(true);
  });

  it("ignores other 403s, including the no-role portal denial", () => {
    expect(isNoSubscriptionAccessError(forbidden("Subscription access denied for the requested scope."))).toBe(false);
    expect(
      isNoSubscriptionAccessError(forbidden("No app role assigned. Contact your administrator to request access.")),
    ).toBe(false);
    expect(isNoSubscriptionAccessError(forbidden([{ msg: "Request access" }]))).toBe(false);
  });

  it("ignores non-403 responses and plain errors", () => {
    expect(isNoSubscriptionAccessError({ response: { status: 400, data: { detail: "Request access" } } })).toBe(false);
    expect(isNoSubscriptionAccessError(new Error("Request access"))).toBe(false);
    expect(isNoSubscriptionAccessError(null)).toBe(false);
  });
});

describe("notifyNoSubscriptionAccess", () => {
  it("dispatches the window event the session gate listens for", () => {
    const listener = vi.fn();
    window.addEventListener(NO_SUBSCRIPTION_ACCESS_EVENT, listener);
    notifyNoSubscriptionAccess();
    window.removeEventListener(NO_SUBSCRIPTION_ACCESS_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
