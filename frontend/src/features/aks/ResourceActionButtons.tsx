/**
 * Icon action toolbar for AKS extended resource grids — matches Deployments tab style.
 */

import React from "react";

const ActionIcons = {
  view: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ),
  edit: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  ),
  delete: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
};

export function ResourceActionButtons({
  onView,
  onEdit,
  onDelete,
  canWrite = true,
  showEdit = true,
  showView = true,
}: {
  onView?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  canWrite?: boolean;
  showEdit?: boolean;
  showView?: boolean;
}) {
  return (
    <div className="flex justify-center gap-1">
      {showView && onView && (
        <button
          type="button"
          onClick={onView}
          className="p-2 text-teal-600 hover:bg-teal-50 rounded-lg"
          title="View"
        >
          {ActionIcons.view}
        </button>
      )}
      {canWrite && showEdit && onEdit && (
        <button
          type="button"
          onClick={onEdit}
          className="p-2 text-purple-600 hover:bg-purple-50 rounded-lg"
          title="Edit"
        >
          {ActionIcons.edit}
        </button>
      )}
      {canWrite && onDelete && (
        <button
          type="button"
          onClick={onDelete}
          className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
          title="Delete"
        >
          {ActionIcons.delete}
        </button>
      )}
    </div>
  );
}
