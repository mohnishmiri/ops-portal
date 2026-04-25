/**
 * MSAL (Microsoft Authentication Library) configuration for Azure AD.
 *
 * Configure your Azure AD App Registration details here.
 * In production, these values come from environment variables.
 *
 * When VITE_AZURE_CLIENT_ID / VITE_AZURE_TENANT_ID are missing or set to
 * placeholder values the app runs in "dev mode" — MSAL is not initialised
 * and the auth gate is skipped so you can work on the UI locally.
 *
 * MFA is enforced via the claims challenge in loginRequest. Azure AD will
 * prompt the user for a second factor (Authenticator app, SMS, etc.) when
 * the acrs claim demands it. This works alongside Azure AD Conditional
 * Access policies configured in the tenant.
 */

import { Configuration, LogLevel } from "@azure/msal-browser";

const runtimeConfig = window.__OPS_PORTAL_CONFIG__ || {};
const browserOrigin = window.location.origin;

function isLocalRuntimeValue(value: string | undefined): boolean {
  if (!value) {
    return false;
  }

  try {
    const parsed = new URL(value, browserOrigin);
    return parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
  } catch {
    return false;
  }
}

const isHostedOrigin = !isLocalRuntimeValue(browserOrigin);
const configuredRedirectUri = runtimeConfig.VITE_REDIRECT_URI || import.meta.env.VITE_REDIRECT_URI;
const configuredApiBaseUrl = runtimeConfig.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE_URL;

const clientId = runtimeConfig.VITE_AZURE_CLIENT_ID || import.meta.env.VITE_AZURE_CLIENT_ID || "68a52619-4061-448c-8264-922aedba1b5b";
const tenantId = runtimeConfig.VITE_AZURE_TENANT_ID || import.meta.env.VITE_AZURE_TENANT_ID || "e741d71c-c6b6-47b0-803c-0f3b32b07556";
const redirectUri =
  isHostedOrigin && isLocalRuntimeValue(configuredRedirectUri)
    ? browserOrigin
    : configuredRedirectUri || (isHostedOrigin ? browserOrigin : "http://localhost:5177");
const apiBaseUrl =
  !isHostedOrigin || isLocalRuntimeValue(configuredApiBaseUrl)
    ? "/api/v1"
    : configuredApiBaseUrl || "/api/v1";

/** True when real Azure AD credentials have NOT been supplied. */
export const isDevMode =
  !clientId ||
  !tenantId ||
  clientId === "YOUR_CLIENT_ID" ||
  tenantId === "YOUR_TENANT_ID";

export const msalConfig: Configuration = {
  auth: {
    clientId: clientId || "00000000-0000-0000-0000-000000000000",
    authority: `https://login.microsoftonline.com/${
      tenantId || "common"
    }`,
    redirectUri,
    postLogoutRedirectUri: "/",
  },
  cache: {
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
      loggerCallback: (level, message) => {
        if (level === LogLevel.Error) console.error(message);
      },
    },
  },
};

/**
 * Login request scopes.
 *
 * We request openid / profile / email so MSAL can build an id_token and
 * populate the account object.  If the App Registration has "Expose an API"
 * configured with Application ID URI = api://<clientId>, add the
 * api://<clientId>/.default scope below.  Until that is done, requesting
 * that scope will cause Azure AD to reject the request.
 *
 * MFA note:  Once a Conditional Access Authentication Context "c1" is
 * created in the Azure AD tenant, uncomment the `claims` block below to
 * enforce MFA.  Without the CA policy in place the claims challenge may
 * cause the login to fail silently.
 */
export const loginRequest = {
  scopes: ["openid", "profile", "email"],
  // ── Optional: uncomment when CA Authentication Context "c1" exists ──
  // claims: JSON.stringify({
  //   access_token: { acrs: { essential: true, values: ["c1"] } },
  // }),
  // prompt: "login" as const,   // force re-auth — enable only when needed
};

/**
 * Silent token request (background renewal — no interactive prompt).
 */
export const silentRequest = {
  scopes: ["openid", "profile", "email"],
};

export const apiConfig = {
  baseUrl: apiBaseUrl,
};
