/**
 * Top navigation building blocks: the nav item model, the dropdown used for
 * grouped pages (Compliance, Admin), and the role-gated admin menu.
 */

import React, { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

/**
 * Nav item definition.
 *
 * module/page strings map directly to resource_name values in the backend
 * resource registry.  The access and admin entries are role-gated (session
 * isSuperAdmin / adminProjectIds), not permission-record gated: My Access is
 * rendered on its own, and the admin menu (ADMIN_NAV) marks each entry with
 * `requires`.
 */
export interface NavItem {
  to: string;
  label: string;
  module?: string;
  page?: string;
  /**
   * Role-gated entries (the admin menu) say who may see them instead of
   * naming a module/page: Super Admins, or anyone who manages access
   * (Super Admins and Project Admins).
   */
  requires?: "superAdmin" | "accessAdmin";
  /**
   * Rendered as a dropdown under this item. The parent stays a link to its
   * own page; the children are separate pages grouped beneath it. Used to
   * keep the nav bar from overflowing as pages are added.
   */
  children?: NavItem[];
}

/**
 * The admin menu. Role-gated rather than permission-record gated, so it is
 * rendered apart from ALL_NAV_ITEMS; the dropdown hides itself when the user
 * may see none of its entries.
 */
export const ADMIN_NAV: NavItem = {
  to: "/admin",
  label: "Admin",
  children: [
    { to: "/admin", label: "Admin Dashboard", requires: "superAdmin" },
    { to: "/admin/permissions", label: "Permissions", requires: "superAdmin" },
    { to: "/access/manage", label: "Manage Access", requires: "accessAdmin" },
  ],
};

/** Who may see an admin-menu entry: its `requires`, checked against the session. */
export function adminEntryVisible(item: NavItem, session: { isSuperAdmin: boolean; canManageAccess: boolean }): boolean {
  if (item.requires === "superAdmin") return session.isSuperAdmin;
  if (item.requires === "accessAdmin") return session.canManageAccess;
  return false;
}

export const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-2 rounded-md text-sm font-medium transition ${
    isActive ? "bg-att-50 text-att-600" : "text-gray-600 hover:text-att-500 hover:bg-att-50"
  }`;

/**
 * A nav entry with children: the label opens a dropdown of its pages rather
 * than navigating. Highlighted whenever any of its children is the active
 * route, so the group still reads as "where you are".
 */
export const NavDropdown: React.FC<{ item: NavItem; isVisible: (child: NavItem) => boolean }> = ({ item, isVisible }) => {
  const [open, setOpen] = useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const location = useLocation();
  const children = (item.children ?? []).filter(isVisible);
  const active = children.some((child) => location.pathname === child.to);

  // Close on an outside click or Escape, the way a menu is expected to behave.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (children.length === 0) return null;

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={`${navLinkClass({ isActive: active })} inline-flex items-center gap-1`}
      >
        {item.label}
        <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="currentColor" aria-hidden="true">
          <path d="M6 9 1.5 4h9L6 9Z" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 z-20 mt-1 min-w-[13rem] overflow-hidden rounded-lg border border-att-100 bg-white py-1 shadow-lg"
        >
          {children.map((child) => (
            <NavLink
              key={child.to}
              to={child.to}
              end
              role="menuitem"
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm transition ${
                  isActive ? "bg-att-50 text-att-600 font-medium" : "text-gray-700 hover:bg-att-50 hover:text-att-600"
                }`
              }
            >
              {child.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
};
