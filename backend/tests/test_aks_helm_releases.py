"""Regression tests for Helm release listing and its Kubernetes API fallback."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.aks_helm_service import AKSHelmService


def _service_with_kubeconfig(tmp_path):
    """AKSHelmService whose ephemeral kubeconfig points at a real temp file."""
    svc = AKSHelmService(SimpleNamespace())
    kubeconfig = tmp_path / "kubeconfig.yaml"
    kubeconfig.write_text("apiVersion: v1\n")
    svc._kubeconfig_path = AsyncMock(return_value=str(kubeconfig))
    return svc


@pytest.mark.asyncio
async def test_cli_missing_falls_back_to_secrets(tmp_path, monkeypatch):
    """No helm binary in the image — releases still come from the K8s secrets."""
    svc = _service_with_kubeconfig(tmp_path)

    def _raise(*args, **kwargs):
        raise FileNotFoundError("helm")

    monkeypatch.setattr("subprocess.run", _raise)
    svc._list_releases_from_secrets = AsyncMock(return_value=[{"name": "from-secrets"}])

    assert await svc.list_releases("cluster-1") == [{"name": "from-secrets"}]
    svc._list_releases_from_secrets.assert_awaited_once_with("cluster-1", None)


@pytest.mark.asyncio
async def test_cli_nonzero_exit_falls_back_to_secrets(tmp_path, monkeypatch):
    """A present-but-failing helm CLI must not render the grid empty.

    Previously a non-zero exit returned [], which is indistinguishable from a
    cluster that genuinely has no releases.
    """
    svc = _service_with_kubeconfig(tmp_path)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Kubernetes cluster unreachable"),
    )
    svc._list_releases_from_secrets = AsyncMock(return_value=[{"name": "recovered"}])

    assert await svc.list_releases("cluster-1", "prod") == [{"name": "recovered"}]
    svc._list_releases_from_secrets.assert_awaited_once_with("cluster-1", "prod")


@pytest.mark.asyncio
async def test_cli_success_returns_parsed_releases(tmp_path, monkeypatch):
    """Happy path: a working CLI is used directly, no fallback."""
    svc = _service_with_kubeconfig(tmp_path)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout='[{"name": "nginx", "namespace": "web", "revision": "3"}]',
            stderr="",
        ),
    )
    svc._list_releases_from_secrets = AsyncMock()

    releases = await svc.list_releases("cluster-1")

    assert releases == [{"name": "nginx", "namespace": "web", "revision": "3"}]
    svc._list_releases_from_secrets.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_cli_output_falls_back(tmp_path, monkeypatch):
    """Malformed JSON from the CLI should fall back rather than raise."""
    svc = _service_with_kubeconfig(tmp_path)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )
    svc._list_releases_from_secrets = AsyncMock(return_value=[])

    assert await svc.list_releases("cluster-1") == []
    svc._list_releases_from_secrets.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_failure_reports_warning_instead_of_raising(tmp_path, monkeypatch):
    """A cluster-client failure must not 500 the endpoint.

    _get_k8s_clients performs auth and can raise. It used to sit outside the
    fallback's try block, so the exception escaped list_releases entirely.
    """
    svc = AKSHelmService(SimpleNamespace())
    svc._kubeconfig_path = AsyncMock(side_effect=RuntimeError("kubeconfig unavailable"))
    svc._aks = SimpleNamespace(_get_k8s_clients=AsyncMock(side_effect=RuntimeError("AADSTS700016: app not found")))

    result = await svc.list_releases_detailed("cluster-1")

    assert result["releases"] == []
    assert result["source"] == "unavailable"
    assert "AADSTS700016" in result["warning"]
    assert "all namespaces" in result["warning"]


@pytest.mark.asyncio
async def test_warning_names_the_namespace_scope(tmp_path):
    """The message should say which scope failed, so the user knows what to retry."""
    svc = AKSHelmService(SimpleNamespace())
    svc._kubeconfig_path = AsyncMock(side_effect=RuntimeError("no cli"))
    svc._aks = SimpleNamespace(_get_k8s_clients=AsyncMock(side_effect=RuntimeError("forbidden")))

    result = await svc.list_releases_detailed("cluster-1", "com-att-attcc-prod")

    assert "namespace 'com-att-attcc-prod'" in result["warning"]


@pytest.mark.asyncio
async def test_secrets_fallback_reports_source(tmp_path, monkeypatch):
    """A successful fallback is not a degraded answer — no warning."""
    svc = _service_with_kubeconfig(tmp_path)

    def _raise(*args, **kwargs):
        raise FileNotFoundError("helm")

    monkeypatch.setattr("subprocess.run", _raise)
    svc._list_releases_from_secrets = AsyncMock(return_value=[{"name": "akvtoaks"}])

    result = await svc.list_releases_detailed("cluster-1")

    assert result["source"] == "k8s-secrets"
    assert result["warning"] is None
    assert result["releases"] == [{"name": "akvtoaks"}]


@pytest.mark.asyncio
async def test_cli_success_reports_source(tmp_path, monkeypatch):
    svc = _service_with_kubeconfig(tmp_path)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout='[{"name": "ingress"}]', stderr=""),
    )

    result = await svc.list_releases_detailed("cluster-1")

    assert result["source"] == "helm-cli"
    assert result["warning"] is None
