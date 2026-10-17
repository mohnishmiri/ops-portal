/**
 * The Admin menu: Super Admins see the console and access management;
 * Project Admins see only Manage Access; everyone else sees no menu.
 */

import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";
import { ADMIN_NAV, adminEntryVisible, NavDropdown } from "./NavDropdown";

function renderMenu(session: { isSuperAdmin: boolean; canManageAccess: boolean }, path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <NavDropdown item={ADMIN_NAV} isVisible={(item) => adminEntryVisible(item, session)} />
    </MemoryRouter>,
  );
}

const menuItems = () => screen.getAllByRole("menuitem").map((item) => item.textContent);

describe("Admin menu", () => {
  it("gives a Super Admin the console, permissions and access management", () => {
    renderMenu({ isSuperAdmin: true, canManageAccess: true });
    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    expect(menuItems()).toEqual(["Admin Dashboard", "Permissions", "Manage Access"]);
  });

  it("gives a Project Admin only Manage Access", () => {
    renderMenu({ isSuperAdmin: false, canManageAccess: true });
    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    expect(menuItems()).toEqual(["Manage Access"]);
  });

  it("is not shown to anyone else", () => {
    renderMenu({ isSuperAdmin: false, canManageAccess: false });
    expect(screen.queryByRole("button", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("marks only the exact page as current", () => {
    renderMenu({ isSuperAdmin: true, canManageAccess: true }, "/admin/permissions");
    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    expect(screen.getByRole("menuitem", { name: "Permissions" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("menuitem", { name: "Admin Dashboard" })).not.toHaveAttribute("aria-current");
  });
});
