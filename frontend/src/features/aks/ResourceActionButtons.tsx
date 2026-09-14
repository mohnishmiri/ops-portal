/**
 * Icon action toolbar for AKS extended resource grids — matches Deployments tab style.
 */

import React from "react";

export const ActionIcons = {
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
  // Helm-specific actions. "Edit" would be a misleading label for an upgrade, so
  // these get their own glyphs rather than reusing the CRUD three above.
  status: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
  history: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <path d="M3 3v5h5" /><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" /><path d="M12 7v5l4 2" />
    </svg>
  ),
  upgrade: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <circle cx="12" cy="12" r="10" /><polyline points="16 12 12 8 8 12" /><line x1="12" y1="16" x2="12" y2="8" />
    </svg>
  ),
  rollback: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
    </svg>
  ),
  install: (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  ),
};

export type ActionIconName = keyof typeof ActionIcons;

const TONE_CLASSES: Record<string, string> = {
  teal: "text-teal-600 hover:bg-teal-50",
  purple: "text-purple-600 hover:bg-purple-50",
  red: "text-red-600 hover:bg-red-50",
  blue: "text-blue-600 hover:bg-blue-50",
  amber: "text-amber-600 hover:bg-amber-50",
  slate: "text-slate-600 hover:bg-slate-50",
};

/**
 * A single icon action, styled like the buttons in ResourceActionButtons.
 * Use when a grid needs actions beyond the view/edit/delete trio.
 */
export function IconActionButton({
  icon,
  title,
  onClick,
  tone = "slate",
  disabled,
}: {
  icon: ActionIconName;
  title: string;
  onClick: () => void;
  tone?: keyof typeof TONE_CLASSES;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`rounded-lg p-2 disabled:cursor-not-allowed disabled:opacity-40 ${TONE_CLASSES[tone] ?? TONE_CLASSES.slate}`}
    >
      {ActionIcons[icon]}
    </button>
  );
}

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
