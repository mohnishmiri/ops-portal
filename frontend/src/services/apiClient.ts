/**
 * API client with MSAL token injection.
 *
 * In dev mode (no Azure AD credentials) the client skips token acquisition.
 *
 * MSAL v3 requires explicit initialize() + handleRedirectPromise() before
 * any other API calls.  We expose an initializeMsal() function that main.tsx
 * awaits before the first React render.
 */

import axios, { AxiosInstance } from "axios";
import {
  EventType,
  InteractionRequiredAuthError,
  PublicClientApplication,
} from "@azure/msal-browser";
import { apiConfig, isDevMode, loginRequest, msalConfig, silentRequest } from "../config/authConfig";

// Create the MSAL instance (lightweight — no network calls yet).
const msalInstance = new PublicClientApplication(msalConfig);

/**
 * Call once before ReactDOM.createRoot().  Initialises the MSAL internal
 * state and processes the Azure AD redirect response (auth code in the URL
 * hash) so that MsalProvider / AuthenticatedTemplate see the user as
 * signed-in on the very first render.
 */
export async function initializeMsal(): Promise<void> {
  if (isDevMode) return;               // nothing to init in dev mode

  await msalInstance.initialize();      // REQUIRED by msal-browser v3

  // Process the redirect response (auth code → tokens).
  // Returns null when the page load is NOT an Azure AD redirect.
  const response = await msalInstance.handleRedirectPromise();

  if (response) {
    // Redirect login succeeded — set the active account so
    // AuthenticatedTemplate picks it up immediately.
    msalInstance.setActiveAccount(response.account);
  } else {
    // Normal page load — pick the first cached account (if any).
    const accounts = msalInstance.getAllAccounts();
    if (accounts.length > 0) {
      msalInstance.setActiveAccount(accounts[0]);
    }
  }

  // Keep the active account in sync when the user signs in/out in
  // another tab or via a redirect.
  msalInstance.addEventCallback((event) => {
    if (
      event.eventType === EventType.LOGIN_SUCCESS &&
      event.payload &&
      "account" in event.payload
    ) {
      msalInstance.setActiveAccount(
        (event.payload as { account: any }).account
      );
    }
  });
}

const apiClient: AxiosInstance = axios.create({
  baseURL: apiConfig.baseUrl,
  headers: { "Content-Type": "application/json" },
});

// Intercept requests to add Bearer token (skip in dev mode).
// We send the **ID token** (not the access token) because the backend
// validates audience = our App Registration client ID.  The access token
// returned by MSAL for openid/profile/email scopes targets Microsoft
// Graph (aud = https://graph.microsoft.com), which won't pass the
// backend's audience check.  The ID token always has aud = clientId.
apiClient.interceptors.request.use(async (config) => {
  if (isDevMode) return config;

  const account = msalInstance.getActiveAccount();
  if (account) {
    try {
      const response = await msalInstance.acquireTokenSilent({
        ...silentRequest,
        account,
      });
      config.headers.Authorization = `Bearer ${response.idToken}`;
    } catch (error) {
      if (error instanceof InteractionRequiredAuthError) {
        await msalInstance.acquireTokenRedirect(loginRequest);
      } else {
        console.error("Token acquisition failed:", error);
        // Request will proceed without auth header — backend returns 401
      }
    }
  }
  return config;
});

// Response error handling – attempt silent re-auth on 401 once, then
// redirect to Azure AD login if the token is truly expired/invalid.
let isRedirecting = false;

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (!isDevMode && error.response?.status === 401 && !isRedirecting) {
      const account = msalInstance.getActiveAccount();
      if (account) {
        try {
          await msalInstance.acquireTokenSilent({
            ...silentRequest,
            account,
            forceRefresh: true,
          });
          // Token refreshed — retry the original request once
          const original = error.config;
          if (original && !original._retry) {
            original._retry = true;
            const freshResponse = await msalInstance.acquireTokenSilent({
              ...silentRequest,
              account,
            });
            original.headers.Authorization = `Bearer ${freshResponse.idToken}`;
            return apiClient(original);
          }
        } catch {
          // Silent refresh failed — redirect to interactive login
          isRedirecting = true;
          await msalInstance.acquireTokenRedirect(loginRequest);
        }
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
export { msalInstance };
