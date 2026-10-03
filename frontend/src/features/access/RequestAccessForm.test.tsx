/**
 * Tests for RequestAccessForm.
 *
 * The Entra role caps the level: a read-role user must not be offered Write
 * (the backend refuses it with a 400, which would read as a broken form).
 * Submitting must send one line per project/app × tier.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import apiClient from "../../services/apiClient";
import type { AccessLevel, CatalogProject } from "../../services/accessApi";
import RequestAccessForm, { WRITE_DISABLED_REASON } from "./RequestAccessForm";

const CATALOG: CatalogProject[] = [
  {
    id: 1,
    name: "Commissions",
    description: "Commissions apps",
    apps: [
      { id: 10, name: "ATTCC", app_code: "31599", tiers: ["prod", "nonprod"] },
      { id: 11, name: "DWS", app_code: "17805", tiers: ["nonprod"] },
    ],
  },
  { id: 2, name: "BDS", description: null, apps: [{ id: 20, name: "HZNREP", app_code: "40001", tiers: ["prod"] }] },
];

function renderForm(roleCeiling: AccessLevel, onSubmitted = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RequestAccessForm catalog={CATALOG} roleCeiling={roleCeiling} onSubmitted={onSubmitted} />
    </QueryClientProvider>,
  );
  return { onSubmitted };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("RequestAccessForm — level ceiling", () => {
  it("disables the Write option for a read-only Entra role and explains why", () => {
    renderForm("read");
    const write = screen.getByRole("option", { name: /write/i }) as HTMLOptionElement;
    expect(write.disabled).toBe(true);
    expect(write.title).toBe(WRITE_DISABLED_REASON);
    expect(screen.getByText(WRITE_DISABLED_REASON)).toBeInTheDocument();
    expect((screen.getByLabelText("Level") as HTMLSelectElement).value).toBe("read");
  });

  it("offers Write to a user whose role allows it", () => {
    renderForm("write");
    const write = screen.getByRole("option", { name: /write/i }) as HTMLOptionElement;
    expect(write.disabled).toBe(false);
    expect(screen.queryByText(WRITE_DISABLED_REASON)).not.toBeInTheDocument();
  });
});

describe("RequestAccessForm — submission", () => {
  it("keeps Submit disabled until a target, a tier and a justification are given", () => {
    renderForm("write");
    const submit = screen.getByRole("button", { name: /submit request/i });
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getByLabelText("App ATTCC"));
    fireEvent.click(screen.getByLabelText("Prod"));
    fireEvent.change(screen.getByLabelText(/justification/i), { target: { value: "too short" } });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/justification/i), { target: { value: "Release support for ATTCC" } });
    expect(submit).toBeEnabled();
  });

  it("sends one item per project/app × tier and locks apps covered by a whole project", async () => {
    (apiClient.post as any).mockResolvedValue({ data: { id: 42, items: [{}, {}, {}, {}] } });
    const { onSubmitted } = renderForm("write");

    fireEvent.click(screen.getByLabelText("Whole project Commissions"));
    // Commissions' apps are covered by the project line now.
    expect(screen.getByLabelText("App ATTCC")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("App HZNREP"));
    fireEvent.click(screen.getByLabelText("Prod"));
    fireEvent.click(screen.getByLabelText("Non-Prod"));
    fireEvent.change(screen.getByLabelText("Level"), { target: { value: "write" } });
    fireEvent.change(screen.getByLabelText(/justification/i), {
      target: { value: "  On-call for Commissions and HZNREP  " },
    });

    expect(screen.getByText("4 request lines")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    expect(apiClient.post).toHaveBeenCalledWith("/access/requests", {
      justification: "On-call for Commissions and HZNREP",
      items: [
        { scope_type: "project", project_id: 1, tier: "prod", level: "write" },
        { scope_type: "project", project_id: 1, tier: "nonprod", level: "write" },
        { scope_type: "app", app_id: 20, tier: "prod", level: "write" },
        { scope_type: "app", app_id: 20, tier: "nonprod", level: "write" },
      ],
    });
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith(expect.objectContaining({ id: 42 })));
  });

  it("shows the backend's reason when the request is refused", async () => {
    (apiClient.post as any).mockRejectedValue({
      response: { status: 400, data: { detail: "You already have a pending request for one of these items." } },
    });
    renderForm("read");
    fireEvent.click(screen.getByLabelText("App DWS"));
    fireEvent.click(screen.getByLabelText("Non-Prod"));
    fireEvent.change(screen.getByLabelText(/justification/i), { target: { value: "Testing DWS changes" } });
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    expect(await screen.findByText("You already have a pending request for one of these items.")).toBeInTheDocument();
  });
});
