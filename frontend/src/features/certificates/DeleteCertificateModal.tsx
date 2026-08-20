/**
 * Delete Certificate modal — destructive action gated to ADMIN callers.
 * Requires a typed confirmation before the delete button is enabled.
 */

import React, { useState } from "react";
import {
  Certificate,
  certificateErrorMessage,
  useDeleteCertificate,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";

interface DeleteCertificateModalProps {
  certificate: Certificate;
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

export const DeleteCertificateModal: React.FC<DeleteCertificateModalProps> = ({
  certificate,
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const del = useDeleteCertificate();
  const [confirmText, setConfirmText] = useState("");
  const confirmed = confirmText.trim().toUpperCase() === "DELETE";

  const handleSubmit = async () => {
    if (!confirmed) return;
    try {
      await del.mutateAsync({
        id: certificate.id,
        collectionId,
        notAfter: certificate.not_after,
        revoked: certificate.revoked,
      });
      onSuccess(`Certificate ${certificate.id} deleted`);
      onClose();
    } catch (err) {
      onError(certificateErrorMessage(err, "Delete failed"));
    }
  };

  return (
    <CertificateModal
      title="Delete Certificate"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={modalButton.danger}
            disabled={!confirmed || del.isPending}
            onClick={handleSubmit}
          >
            {del.isPending ? "Deleting…" : "Delete"}
          </button>
        </>
      }
    >
      <div className="space-y-4 text-sm text-gray-700">
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          This permanently removes the certificate record for{" "}
          <span className="font-semibold">{certificate.common_name}</span> (ID {certificate.id}).
        </div>
        <div>
          <label className={fieldLabel} htmlFor="delete-confirm">
            Type DELETE to confirm
          </label>
          <input
            id="delete-confirm"
            className={fieldInput}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
          />
        </div>
      </div>
    </CertificateModal>
  );
};
