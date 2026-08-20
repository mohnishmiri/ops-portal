/**
 * Update Metadata modal — WRITE-gated. Edits key/value metadata (custom fields)
 * on a certificate. Rows are edited inline; empty keys are ignored.
 */

import React, { useState } from "react";
import {
  Certificate,
  certificateErrorMessage,
  useUpdateCertificateMetadata,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";

interface UpdateMetadataModalProps {
  certificate: Certificate;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

interface Row {
  key: string;
  value: string;
}

export const UpdateMetadataModal: React.FC<UpdateMetadataModalProps> = ({
  certificate,
  onClose,
  onSuccess,
  onError,
}) => {
  const update = useUpdateCertificateMetadata();
  const initial: Row[] = Object.entries(certificate.metadata || {}).map(([key, value]) => ({
    key,
    value: value == null ? "" : String(value),
  }));
  const [rows, setRows] = useState<Row[]>(initial.length ? initial : [{ key: "", value: "" }]);
  const [error, setError] = useState("");

  const setRow = (idx: number, patch: Partial<Row>) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const addRow = () => setRows((prev) => [...prev, { key: "", value: "" }]);
  const removeRow = (idx: number) => setRows((prev) => prev.filter((_, i) => i !== idx));

  const handleSubmit = async () => {
    const metadata: Record<string, string> = {};
    for (const r of rows) {
      const k = r.key.trim();
      if (k) metadata[k] = r.value;
    }
    if (Object.keys(metadata).length === 0) {
      setError("Add at least one metadata field");
      return;
    }
    try {
      await update.mutateAsync({ id: certificate.id, data: { metadata } });
      onSuccess(`Metadata updated for certificate ${certificate.id}`);
      onClose();
    } catch (err) {
      onError(certificateErrorMessage(err, "Update failed"));
    }
  };

  return (
    <CertificateModal
      title="Update Metadata"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={modalButton.primary}
            disabled={update.isPending}
            onClick={handleSubmit}
          >
            {update.isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <label className={fieldLabel}>Custom fields</label>
        {rows.map((row, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <input
              aria-label={`Metadata key ${idx + 1}`}
              className={fieldInput}
              placeholder="key"
              value={row.key}
              onChange={(e) => setRow(idx, { key: e.target.value })}
            />
            <input
              aria-label={`Metadata value ${idx + 1}`}
              className={fieldInput}
              placeholder="value"
              value={row.value}
              onChange={(e) => setRow(idx, { value: e.target.value })}
            />
            <button
              type="button"
              aria-label={`Remove field ${idx + 1}`}
              className="rounded-md p-1 text-gray-400 hover:bg-att-100 hover:text-red-600"
              onClick={() => removeRow(idx)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        ))}
        <button type="button" className={modalButton.secondary} onClick={addRow}>
          + Add field
        </button>
        {error ? <p className="text-xs text-red-600">{error}</p> : null}
      </div>
    </CertificateModal>
  );
};
