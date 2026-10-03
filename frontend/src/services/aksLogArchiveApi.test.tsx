/**
 * Tests for the complete-log archive download.
 *
 *  • the request is a streamed blob with no timeout — a 100-pod archive takes minutes
 *  • the filename comes from the server's Content-Disposition
 *  • error bodies arrive as a Blob, and the API's detail message must still reach the user
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("./apiClient", () => ({
  default: { get: vi.fn(), post, put: vi.fn(), delete: vi.fn() },
}));

import { downloadLogArchive } from "./aksApi";

const CLUSTER_ID =
  "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-01";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("downloadLogArchive", () => {
  it("posts the target and streams the archive without a timeout", async () => {
    const blob = new Blob(["zip"], { type: "application/zip" });
    post.mockResolvedValue({
      data: blob,
      headers: { "content-disposition": 'attachment; filename="aks-01_deployment_web_20261003T040000Z.zip"' },
    });
    const onProgress = vi.fn();

    const result = await downloadLogArchive(
      { clusterId: CLUSTER_ID, kind: "deployment", namespace: "apps", name: "web" },
      { onProgress }
    );

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/aks/logs/archive");
    expect(body).toEqual({
      cluster_id: CLUSTER_ID,
      kind: "deployment",
      namespace: "apps",
      name: "web",
      pods: [],
      include_previous: true,
    });
    expect(config.responseType).toBe("blob");
    expect(config.timeout).toBe(0);
    config.onDownloadProgress({ loaded: 2048 });
    expect(onProgress).toHaveBeenCalledWith(2048);
    expect(result).toEqual({ blob, filename: "aks-01_deployment_web_20261003T040000Z.zip" });
  });

  it("sends an explicit pod list", async () => {
    post.mockResolvedValue({ data: new Blob([]), headers: {} });

    const result = await downloadLogArchive({
      clusterId: CLUSTER_ID,
      kind: "pods",
      pods: [{ namespace: "apps", name: "web-1" }],
      includePrevious: false,
    });

    expect(post.mock.calls[0][1]).toMatchObject({ kind: "pods", pods: [{ namespace: "apps", name: "web-1" }], include_previous: false });
    expect(result.filename).toBe("pods-logs.zip");
  });

  it("surfaces the API detail from a Blob error body", async () => {
    post.mockRejectedValue({
      response: {
        status: 400,
        data: new Blob([JSON.stringify({ detail: "Deployment apps/web has no pods, so there are no logs to download." })]),
      },
    });

    await expect(
      downloadLogArchive({ clusterId: CLUSTER_ID, kind: "deployment", namespace: "apps", name: "web" })
    ).rejects.toThrow("Deployment apps/web has no pods, so there are no logs to download.");
  });

  it("falls back to the HTTP status when the error body is not JSON", async () => {
    post.mockRejectedValue({ response: { status: 502, data: new Blob(["<html>bad gateway</html>"]) } });

    await expect(
      downloadLogArchive({ clusterId: CLUSTER_ID, kind: "pods", pods: [{ namespace: "apps", name: "web-1" }] })
    ).rejects.toThrow("Log download failed (HTTP 502).");
  });
});
