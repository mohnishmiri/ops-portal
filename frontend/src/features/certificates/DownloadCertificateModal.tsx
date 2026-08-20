/**
 * Download Certificate modal — matches Keyfactor Command download dialog.
 *
 * Options: File Format (PEM, CER, CRT, DER, P7B), Include Chain toggle,
 * Chain Order (End Entity First / Root First), Include Subject Header toggle.
 */

import React, { useState } from "react";
import {
  Certificate,
  DOWNLOAD_FORMATS,
  DownloadFormat,
  ChainOrder,
  certificateErrorMessage,
  useDownloadCertificate,
} from "../../services/certificatesApi";
import { CertificateModal, fieldInput, fieldLabel, modalButton } from "./CertificateModal";

interface DownloadCertificateModalProps {
  certificate: Certificate;
  collectionId?: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

export const DownloadCertificateModal: React.FC<DownloadCertificateModalProps> = ({
  certificate,
  collectionId,
  onClose,
  onSuccess,
  onError,
}) => {
  const download = useDownloadCertificate();
  const [format, setFormat] = useState<DownloadFormat>("PEM");
  const [includeChain, setIncludeChain] = useState(true);
  const [chainOrder, setChainOrder] = useState<ChainOrder>("EndEntityFirst");
  const [includeSubjectHeader, setIncludeSubjectHeader] = useState(true);

  const handleDownload = async () => {
    try {
      const blob = await download.mutateAsync({
        id: certificate.id,
        data: {
          file_format: format,
          include_chain: includeChain,
          chain_order: chainOrder,
          include_subject_header: includeSubjectHeader,
          collection_id: collectionId,
        },
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${certificate.common_name || "certificate"}.${format.toLowerCase()}`;
      a.click();
      URL.revokeObjectURL(url);
      onSuccess("Certificate downloaded");
      onClose();
    } catch (err) {
      onError(certificateErrorMessage(err, "Download failed"));
    }
  };

  return (
    <CertificateModal
      title="Download"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={modalButton.secondary} onClick={onClose}>
            CANCEL
          </button>
          <button
            type="button"
            className={modalButton.primary}
            disabled={download.isPending}
            onClick={handleDownload}
          >
            {download.isPending ? "Downloading…" : "DOWNLOAD"}
          </button>
        </>
      }
    >
      <div className="space-y-5">
        <div>
          <label className={fieldLabel} htmlFor="dl-format">
            File Format
          </label>
          <select
            id="dl-format"
            className={fieldInput}
            value={format}
            onChange={(e) => setFormat(e.target.value as DownloadFormat)}
          >
            {DOWNLOAD_FORMATS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        <div className="border-t border-att-100 pt-4">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-600">
            Chain Options
          </h3>
          <label className="flex items-center gap-3 cursor-pointer">
            <div
              role="switch"
              aria-checked={includeChain}
              tabIndex={0}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                includeChain ? "bg-att-500" : "bg-gray-300"
              }`}
              onClick={() => setIncludeChain(!includeChain)}
              onKeyDown={(e) => e.key === "Enter" && setIncludeChain(!includeChain)}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  includeChain ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </div>
            <span className="text-sm text-gray-700">Include Chain</span>
          </label>
        </div>

        {includeChain && (
          <div className="pl-4">
            <span className={fieldLabel}>Chain Order</span>
            <div className="mt-1 flex gap-4">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="radio"
                  name="chain-order"
                  checked={chainOrder === "EndEntityFirst"}
                  onChange={() => setChainOrder("EndEntityFirst")}
                  className="accent-att-500"
                />
                End Entity First
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="radio"
                  name="chain-order"
                  checked={chainOrder === "RootFirst"}
                  onChange={() => setChainOrder("RootFirst")}
                  className="accent-att-500"
                />
                Root First
              </label>
            </div>
          </div>
        )}

        <div className="border-t border-att-100 pt-4">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-600">
            Additional Options
          </h3>
          <label className="flex items-center gap-3 cursor-pointer">
            <div
              role="switch"
              aria-checked={includeSubjectHeader}
              tabIndex={0}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                includeSubjectHeader ? "bg-att-500" : "bg-gray-300"
              }`}
              onClick={() => setIncludeSubjectHeader(!includeSubjectHeader)}
              onKeyDown={(e) => e.key === "Enter" && setIncludeSubjectHeader(!includeSubjectHeader)}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  includeSubjectHeader ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </div>
            <span className="text-sm text-gray-700">Include Subject Header</span>
          </label>
        </div>
      </div>
    </CertificateModal>
  );
};
