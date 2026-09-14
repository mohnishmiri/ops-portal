"""Tests for the extended Helm operations: repos, search, status, history, template, lint.

Every value these methods accept is spliced into a subprocess argv. We never use
shell=True so shell metacharacters are inert, but a value starting with "-" would
still be parsed by Helm as a flag — the validation tests below cover that.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.aks_helm_service import AKSHelmService, HelmValidationError


@pytest.fixture
def helm():
    return AKSHelmService(SimpleNamespace())


def _capture_local(svc, result):
    """Replace _run_helm_local, recording the argv it was handed."""
    calls: list[list[str]] = []

    async def _run(args):
        calls.append(list(args))
        return result

    svc._run_helm_local = _run
    return calls


# ── Repositories ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_add_builds_expected_command(helm):
    calls = _capture_local(helm, {"success": True})

    await helm.repo_add("bitnami", "https://charts.bitnami.com/bitnami")

    assert calls == [["repo", "add", "bitnami", "https://charts.bitnami.com/bitnami", "--force-update"]]


@pytest.mark.asyncio
async def test_repo_add_passes_credentials(helm):
    calls = _capture_local(helm, {"success": True})

    await helm.repo_add("private", "https://charts.example.com", username="u", password="p")

    assert "--username" in calls[0] and "u" in calls[0]
    assert "--password" in calls[0] and "p" in calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",  # local file read
        "ftp://example.com/charts",  # unsupported scheme
        "not-a-url",  # no scheme at all
        "https://",  # no host
    ],
)
async def test_repo_add_rejects_non_http_urls(helm, url):
    """The server fetches this URL, so the scheme is restricted."""
    _capture_local(helm, {"success": True})

    with pytest.raises(HelmValidationError):
        await helm.repo_add("evil", url)


@pytest.mark.asyncio
async def test_repo_add_rejects_flag_like_name(helm):
    """A name starting with '-' would be consumed by Helm as a flag."""
    _capture_local(helm, {"success": True})

    with pytest.raises(HelmValidationError):
        await helm.repo_add("--kubeconfig", "https://charts.example.com")


@pytest.mark.asyncio
async def test_repo_update_all_and_single(helm):
    calls = _capture_local(helm, {"success": True})

    await helm.repo_update()
    await helm.repo_update("bitnami")

    assert calls[0] == ["repo", "update"]
    assert calls[1] == ["repo", "update", "bitnami"]


@pytest.mark.asyncio
async def test_repo_list_returns_empty_when_none_configured(helm):
    """`helm repo list` exits non-zero when no repos exist — that is not an error."""
    _capture_local(helm, {"success": False, "error": "no repositories to show"})

    assert await helm.repo_list() == []


@pytest.mark.asyncio
async def test_repo_list_returns_parsed_repos(helm):
    repos = [{"name": "bitnami", "url": "https://charts.bitnami.com/bitnami"}]
    _capture_local(helm, {"success": True, "data": repos})

    assert await helm.repo_list() == repos


# ── Search ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_repo_without_keyword_lists_everything(helm):
    calls = _capture_local(helm, {"success": True, "data": []})

    await helm.search_repo()

    assert calls[0] == ["search", "repo", "-o", "json"]


@pytest.mark.asyncio
async def test_search_repo_with_keyword_and_versions(helm):
    calls = _capture_local(helm, {"success": True, "data": [{"name": "bitnami/nginx"}]})

    charts = await helm.search_repo("nginx", versions=True)

    assert calls[0] == ["search", "repo", "nginx", "--versions", "-o", "json"]
    assert charts == [{"name": "bitnami/nginx"}]


@pytest.mark.asyncio
async def test_search_repo_rejects_flag_like_keyword(helm):
    _capture_local(helm, {"success": True, "data": []})

    with pytest.raises(HelmValidationError):
        await helm.search_repo("--set")


# ── Status and history ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_release_status_builds_expected_command(helm):
    helm._run_helm = AsyncMock(return_value={"success": True, "data": {"info": {"status": "deployed"}}})

    result = await helm.release_status("cluster-1", "akvtoaks", "com-att-attcc-prod")

    helm._run_helm.assert_awaited_once_with(
        "cluster-1", ["status", "akvtoaks", "-n", "com-att-attcc-prod", "-o", "json"]
    )
    assert result["data"]["info"]["status"] == "deployed"


@pytest.mark.asyncio
async def test_release_history_returns_revisions(helm):
    revisions = [{"revision": 1, "status": "superseded"}, {"revision": 2, "status": "deployed"}]
    helm._run_helm = AsyncMock(return_value={"success": True, "data": revisions})

    assert await helm.release_history("cluster-1", "ingress", "prod") == revisions


@pytest.mark.asyncio
async def test_release_history_returns_empty_on_failure(helm):
    helm._run_helm = AsyncMock(return_value={"success": False, "error": "release: not found"})

    assert await helm.release_history("cluster-1", "ghost", "prod") == []


@pytest.mark.asyncio
async def test_release_status_rejects_flag_like_release(helm):
    helm._run_helm = AsyncMock()

    with pytest.raises(HelmValidationError):
        await helm.release_status("cluster-1", "--all-namespaces", "prod")

    helm._run_helm.assert_not_awaited()


# ── Template and lint ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_chart_renders_without_cluster(helm):
    calls = _capture_local(helm, {"success": True, "output": "apiVersion: v1"})

    result = await helm.template_chart("bitnami/nginx", release_name="web", namespace="prod")

    assert calls[0] == ["template", "web", "bitnami/nginx", "-n", "prod"]
    assert result["output"] == "apiVersion: v1"


@pytest.mark.asyncio
async def test_template_chart_writes_values_file_and_cleans_up(helm, tmp_path):
    seen: dict[str, str] = {}

    async def _run(args):
        # The -f argument must point at a real file while helm is running.
        idx = args.index("-f")
        path = args[idx + 1]
        with open(path, encoding="utf-8") as fh:
            seen["path"] = path
            seen["contents"] = fh.read()
        return {"success": True, "output": "rendered"}

    helm._run_helm_local = _run

    await helm.template_chart("bitnami/nginx", values_yaml="replicaCount: 3\n")

    assert seen["contents"] == "replicaCount: 3\n"
    # Temp values files must not outlive the command.
    import os

    assert not os.path.exists(seen["path"])


@pytest.mark.asyncio
async def test_lint_chart_returns_failure_output_without_raising(helm):
    """A failing lint is a valid answer — the caller renders the output."""
    _capture_local(helm, {"success": False, "error": "[ERROR] Chart.yaml: name is required"})

    result = await helm.lint_chart("bitnami/broken-chart")

    assert result["success"] is False
    assert "name is required" in result["error"]


@pytest.mark.asyncio
async def test_lint_chart_rejects_flag_like_chart(helm):
    _capture_local(helm, {"success": True})

    with pytest.raises(HelmValidationError):
        await helm.lint_chart("--debug")


@pytest.mark.asyncio
@pytest.mark.parametrize("chart", ["./local-chart", "../../etc/passwd", "/abs/path/chart"])
async def test_chart_refs_must_not_be_filesystem_paths(helm, chart):
    """Charts are resolved from repositories or OCI registries, never from disk.

    Accepting a path would let a caller point Helm at arbitrary server files.
    """
    _capture_local(helm, {"success": True})

    with pytest.raises(HelmValidationError):
        await helm.lint_chart(chart)


@pytest.mark.asyncio
async def test_oci_chart_refs_are_accepted(helm):
    calls = _capture_local(helm, {"success": True, "output": "rendered"})

    await helm.template_chart("oci://myregistry.azurecr.io/charts/api")

    assert calls[0] == ["template", "release-name", "oci://myregistry.azurecr.io/charts/api"]


# ── Existing mutations now validate their inputs ──────────────────────


@pytest.mark.asyncio
async def test_install_rejects_flag_like_release_name(helm):
    helm._run_helm = AsyncMock()

    with pytest.raises(HelmValidationError):
        await helm.install_release("cluster-1", "-x", "bitnami/nginx", "prod")

    helm._run_helm.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollback_rejects_non_positive_revision(helm):
    helm._run_helm = AsyncMock()

    with pytest.raises(HelmValidationError):
        await helm.rollback_release("cluster-1", "nginx", "prod", 0)

    helm._run_helm.assert_not_awaited()


@pytest.mark.asyncio
async def test_uninstall_validates_namespace(helm):
    helm._run_helm = AsyncMock()

    with pytest.raises(HelmValidationError):
        await helm.uninstall_release("cluster-1", "nginx", "--all")

    helm._run_helm.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_helm_cli_reports_clearly(helm, monkeypatch):
    """Commands with no Kubernetes fallback must say why they cannot run."""

    def _raise(*args, **kwargs):
        raise FileNotFoundError("helm")

    monkeypatch.setattr("subprocess.run", _raise)

    with pytest.raises(HelmValidationError, match="Helm CLI is not available"):
        await helm.repo_list()
