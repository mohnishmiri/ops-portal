/**
 * AccessDenied — shown when the user navigates to a page they cannot access.
 *
 * Provides a clear message and a link back to the home page.
 */

import React from "react";
import { Link } from "react-router-dom";

interface AccessDeniedProps {
  /** Which resource/page was denied (shown in the message). */
  resourceName?: string;
}

const AccessDenied: React.FC<AccessDeniedProps> = ({ resourceName }) => (
  <div className="flex items-center justify-center min-h-[60vh]">
    <div className="bg-white rounded-2xl shadow-md border border-red-100 p-10 max-w-md w-full text-center">
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
      <h2 className="text-xl font-bold text-gray-900 mb-2">Access Denied</h2>
      <p className="text-gray-500 text-sm mb-1">
        You don't have permission to view{" "}
        {resourceName ? (
          <span className="font-medium text-gray-700">{resourceName}</span>
        ) : (
          "this page"
        )}
        .
      </p>
      <p className="text-gray-400 text-xs mb-6">
        Contact your administrator to request access.
      </p>
      <Link
        to="/"
        className="inline-flex items-center gap-2 px-4 py-2 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 transition"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l9-9 9 9M5 10v9a1 1 0 001 1h4v-5h4v5h4a1 1 0 001-1v-9" />
        </svg>
        Back to Home
      </Link>
    </div>
  </div>
);

export default AccessDenied;
