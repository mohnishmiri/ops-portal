/**
 * Shared usage display: live usage against requests and limits, and "no
 * sample" shown as unknown rather than zero.
 */

import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import { ResourceUsage, WorkloadPodsGrid } from "./detailShared";

describe("ResourceUsage", () => {
  it("shows usage against the request", () => {
    render(<ResourceUsage kind="cpu" used={12} request={250} limit={1000} />);

    expect(screen.getByTitle("Using 12m · request 250m · limit 1 core").textContent).toBe("12m / 250m req");
  });

  it("falls back to the limit, and to unknown without a sample", () => {
    const { rerender } = render(<ResourceUsage kind="memory" used={300 * 2 ** 20} limit={512 * 2 ** 20} />);
    expect(screen.getByText("/ 512 MiB lim")).toBeTruthy();

    rerender(<ResourceUsage kind="memory" used={null} request={256 * 2 ** 20} />);
    expect(screen.getByTitle("No live usage: metrics-server has no sample for this pod.").textContent).toBe("— / 256 MiB req");
  });
});

describe("WorkloadPodsGrid", () => {
  it("lists each pod's CPU and memory use", () => {
    render(
      <WorkloadPodsGrid
        pods={[
          {
            pod_name: "web-1",
            namespace: "apps",
            phase: "Running",
            status: "Running",
            ready: true,
            node: "aks-np-1",
            pod_ip: "10.0.0.5",
            started_at: null,
            restarts: 0,
            containers: ["app"],
            revision: "1",
            cpu_request_m: 250,
            cpu_limit_m: 0,
            memory_request_bytes: 256 * 2 ** 20,
            memory_limit_bytes: 0,
            cpu_usage_m: 30,
            memory_usage_bytes: 128 * 2 ** 20,
          },
        ]}
        onViewPodLogs={() => {}}
        canDeletePod={false}
      />
    );

    expect(screen.getByText("30m")).toBeTruthy();
    expect(screen.getByText("128 MiB")).toBeTruthy();
  });
});

describe("PercentMeter", () => {
  it("shows a percentage, or unknown without data", async () => {
    const { PercentMeter } = await import("./aksGridShared");
    const { rerender } = render(<PercentMeter label="CPU" pct={7.5} title="cpu" />);
    expect(screen.getByTitle("cpu").textContent).toBe("CPU8%");
    rerender(<PercentMeter label="CPU" pct={null} title="cpu" />);
    expect(screen.getByTitle("cpu").textContent).toBe("CPU—");
  });
});
