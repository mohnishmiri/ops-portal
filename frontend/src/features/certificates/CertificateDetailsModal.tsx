/**
 * Certificate Details modal — read-only full metadata for a single certificate.
 * Renders the certificate already loaded by the list (fetched with verbose
 * metadata), so no extra per-certificate request is made.
 */

import React from "react";
import { Certificate } from "../../services/certificatesApi";
import { CertificateModal, modalButton } from "./CertificateModal";
import { StatusBadge } from "./StatusBadge";

interface CertificateDetailsModalProps {
  certificate: Certificate;
  onClose: () => void;
}

const Row: React.FC<{ label: string; value: React.ReactNode; mono?: boolean }> = ({
  label,
  value,
  mono,
}) => (
  <div className="grid grid-cols-3 gap-2 py-1.5">
    <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</dt>
    <dd className={`col-span-2 text-sm text-gray-800 ${mono ? "font-mono text-xs break-all" : ""}`}>
      {value || "—"}
    </dd>
  </div>
);

export const CertificateDetailsModal: React.FC<CertificateDetailsModalProps> = ({
  certificate,
  onClose,
}) => {
  return (
    <CertificateModal
      title="Certificate Details"
      onClose={onClose}
      widthClassName="max-w-2xl"
      footer={
        <button type="button" className={modalButton.secondary} onClick={onClose}>
          Close
        </button>
      }
    >
      <dl className="divide-y divide-att-50">
        <Row label="Status" value={<StatusBadge status={certificate.status} />} />
        <Row label="Common Name" value={certificate.common_name} />
        <Row label="Subject" value={certificate.subject_dn} />
        <Row label="Issuer" value={certificate.issuer_dn} />
        <Row label="Serial" value={certificate.serial_number} mono />
        <Row label="Thumbprint" value={certificate.thumbprint} mono />
        <Row label="Template" value={certificate.template} />
        <Row label="Issuing CA" value={certificate.certificate_authority} />
        <Row label="Valid From" value={certificate.not_before} />
        <Row label="Valid To" value={certificate.not_after} />
        <Row label="SANs" value={certificate.sans?.join(", ")} />
        {certificate.revoked ? (
          <Row label="Revocation Reason" value={String(certificate.revocation_reason ?? "")} />
        ) : null}
        {certificate.metadata && Object.keys(certificate.metadata).length ? (
          <Row
            label="Metadata"
            value={
              <ul className="space-y-0.5">
                {Object.entries(certificate.metadata).map(([k, v]) => (
                  <li key={k}>
                    <span className="font-medium">{k}:</span> {String(v)}
                  </li>
                ))}
              </ul>
            }
          />
        ) : null}
      </dl>
    </CertificateModal>
  );
};
