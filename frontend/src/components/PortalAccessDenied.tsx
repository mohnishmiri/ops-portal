/**
 * PortalAccessDenied — full-screen denial for authenticated-but-unentitled users.
 *
 * Distinct from `AccessDenied`, which is a per-page denial rendered *inside*
 * the app shell and links back to home. This one replaces the entire
 * application: there is no shell, no navigation, and no home to go back to,
 * so it renders outside the router and offers only sign-out.
 *
 * Rendered by `PortalAccessGate` when the backend reports
 * `authenticated: true, authorized: false`.
 */

import React from "react";
import { useMsal } from "@azure/msal-react";

// Matches BRAND_LOGO_PATH in App.tsx. Inlined rather than imported because
// BrandMark is a local helper there, and this screen must render without
// pulling in the app shell.
const BRAND_LOGO_PATH = "/att-globe.svg?v=20260413c";

interface PortalAccessDeniedProps {
  /** Signed-in address, shown so the user can spot a wrong-account sign-in. */
  email?: string;
}

const PortalAccessDenied: React.FC<PortalAccessDeniedProps> = ({ email }) => {
  const { instance } = useMsal();

  return (
    <div className="min-h-screen bg-gradient-to-br from-att-50 to-att-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl border border-red-100 p-10 max-w-lg w-full text-center">
        <div className="flex justify-center mb-6">
          <div className="h-20 w-20 flex items-center justify-center shrink-0">
            <img src={BRAND_LOGO_PATH} alt="AT&amp;T logo" className="h-full w-full" />
          </div>
        </div>

        <div className="flex justify-center mb-5">
          <div className="h-16 w-16 rounded-full bg-red-50 flex items-center justify-center">
            <svg
              className="h-8 w-8 text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m0 3.75h.008v.008H12v-.008zm-9-6a9 9 0 1118 0 9 9 0 01-18 0z"
              />
            </svg>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-3">Access Denied</h1>

        <p className="text-gray-600 text-sm mb-2">
          Your account has been successfully authenticated, but you are not authorized to access
          the AT&amp;T Ops Portal.
        </p>

        {email && (
          <p className="text-gray-500 text-xs mb-2">
            Signed in as <span className="font-medium text-gray-700">{email}</span>
          </p>
        )}

        <p className="text-gray-400 text-xs mb-8">
          Please contact the Ops Portal administrator if you believe you should have access.
        </p>

        <button
          onClick={() => instance.logoutRedirect()}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 transition"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9"
            />
          </svg>
          Sign out
        </button>
      </div>
    </div>
  );
};

export default PortalAccessDenied;
