/**
 * NoSubscriptionAccess — shown in place of a module page when the user holds
 * no subscription grant yet.
 *
 * Not a denial: the user is entitled to the portal, they just have not been
 * given a project or app. Every module API would answer 403, so rather than
 * letting the page load and fail, point them at the Access page.
 */

import React from "react";
import { Link } from "react-router-dom";
import { useSession } from "../contexts/SessionContext";

interface NoSubscriptionAccessProps {
  /** Page the user tried to open, e.g. "AKS Operations". */
  resourceName?: string;
}

const NoSubscriptionAccess: React.FC<NoSubscriptionAccessProps> = ({ resourceName }) => {
  const { refreshSession } = useSession();
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="bg-white rounded-2xl shadow-md border border-att-100 p-10 max-w-lg w-full text-center">
        <div className="flex justify-center mb-5">
          <div className="h-16 w-16 rounded-full bg-att-50 ring-1 ring-att-100 flex items-center justify-center">
            <svg
              className="h-8 w-8 text-att-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.75}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="7.5" cy="15.5" r="4.5" />
              <path d="m10.7 12.3 9.8-9.8M17 6l3 3M14.5 8.5l2 2" />
            </svg>
          </div>
        </div>
        <h2 className="text-xl font-bold text-gray-900 mb-2">You don&apos;t have access to any subscription yet</h2>
        <p className="text-gray-500 text-sm mb-1">
          {resourceName ? (
            <>
              <span className="font-medium text-gray-700">{resourceName}</span> shows data for the subscriptions you
              have been granted.
            </>
          ) : (
            "Ops Portal pages show data for the subscriptions you have been granted."
          )}
        </p>
        <p className="text-gray-400 text-xs mb-6">
          Request access to a project or app — a Project Admin will review it and you will get an email when they
          decide.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            to="/access"
            className="inline-flex items-center gap-2 px-4 py-2 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 transition"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
            </svg>
            Request access
          </Link>
          <button
            type="button"
            onClick={refreshSession}
            className="inline-flex items-center gap-2 px-4 py-2 border border-att-200 bg-white text-att-700 rounded-lg text-sm font-semibold hover:bg-att-50 transition"
          >
            Check again
          </button>
        </div>
      </div>
    </div>
  );
};

export default NoSubscriptionAccess;
