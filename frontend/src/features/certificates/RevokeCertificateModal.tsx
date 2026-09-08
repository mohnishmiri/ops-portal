/**
 * Revoke Certificate modal — destructive action gated to ADMIN callers.
 *
 * Requires an explicit RFC 5280 reason and a typed confirmation before the
 * revoke button is enabled.
 */

import React, { useState } from "react";
import {
  Certificate,
  REVOCATION_REASONS,
  RevocationReason,
  certificateErrorMessage,
  useRevokeCertificate,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";

interface RevokeCertificateModalProps {
  certificate: Certificate;
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

export const RevokeCertificateModal: React.FC<RevokeCertificateModalProps> = ({
  certificate,
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const revoke = useRevokeCertificate();
  const [reason, setReason] = useState<RevocationReason>("unspecified");
  const [comment, setComment] = useState("");
  const [confirmText, setConfirmText] = useState("");

  const confirmed = confirmText.trim().toUpperCase() === "REVOKE";

  const handleSubmit = async () => {
    if (!confirmed) return;
    try {
      // Blank stays blank: the backend fills in who revoked it and why, because
      // Keyfactor rejects an empty revocation comment.
      await revoke.mutateAsync({
        id: certificate.id,
        data: { reason, comment: comment.trim(), collection_id: collectionId },
      });
      onSuccess(`Certificate ${certificate.id} revoked`);
      onClose();
    } catch (err) {
      onError(certificateErrorMessage(err, "Revocation failed"));
    }
  };

  return (
    <CertificateModal
      title="Revoke Certificate"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={modalButton.danger}
            disabled={!confirmed || revoke.isPending}
            onClick={handleSubmit}
          >
            {revoke.isPending ? "Revoking…" : "Revoke"}
          </button>
        </>
      }
    >
      <div className="space-y-4 text-sm text-gray-700">
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          Revoking is irreversible. <span className="font-semibold">{certificate.common_name}</span>{" "}
          (ID {certificate.id}) will no longer be trusted.
        </div>
        <div>
          <label className={fieldLabel} htmlFor="revoke-reason">
            Revocation Reason
          </label>
          <select
            id="revoke-reason"
            className={fieldInput}
            value={reason}
            onChange={(e) => setReason(e.target.value as RevocationReason)}
          >
            {REVOCATION_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="revoke-comment">
            Comment (optional)
          </label>
          <input
            id="revoke-comment"
            className={fieldInput}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            aria-describedby="revoke-comment-help"
          />
          <p id="revoke-comment-help" className="mt-1 text-xs text-gray-500">
            Leave blank and the revocation is recorded against your name and the reason above.
          </p>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="revoke-confirm">
            Type REVOKE to confirm
          </label>
          <input
            id="revoke-confirm"
            className={fieldInput}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            aria-describedby="revoke-confirm-help"
          />
          <p id="revoke-confirm-help" className="mt-1 text-xs text-gray-500">
            This guard prevents accidental revocation.
          </p>
        </div>
      </div>
    </CertificateModal>
  );
};
