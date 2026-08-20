/**
 * Certificate status badge — colour-coded indicator for
 * valid / expiring soon / expired / revoked / unknown states.
 */

import React from "react";
import { CertificateStatus, STATUS_LABEL } from "../../services/certificatesApi";

const STATUS_CLASS: Record<CertificateStatus, string> = {
  valid: "bg-green-100 text-green-800 ring-green-200",
  expiring_soon: "bg-amber-100 text-amber-800 ring-amber-200",
  expired: "bg-red-100 text-red-800 ring-red-200",
  revoked: "bg-slate-200 text-slate-700 ring-slate-300",
  unknown: "bg-gray-100 text-gray-600 ring-gray-200",
};

export const StatusBadge: React.FC<{ status: CertificateStatus }> = ({ status }) => (
  <span
    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_CLASS[status]}`}
    aria-label={`Status: ${STATUS_LABEL[status]}`}
  >
    {STATUS_LABEL[status]}
  </span>
);
