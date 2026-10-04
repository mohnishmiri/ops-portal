"""AKS API-server tokens are renewed per request, not fixed when a client is built.

A cached client used to keep the token it was built with for 50 minutes, but
the shared credential hands out its cached token, which can have only minutes
left — so every Kubernetes call on that client failed with 401 Unauthorized
until the cache evicted it (seen on the AKV Sync tab's background refresh).
"""

import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from azure.core.credentials import AccessToken
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services import aks_operations_service as aks_module
from app.services.aks_helm_service import AKSHelmService
from app.services.aks_operations_service import AKSOperationsService, _refresh_k8s_bearer
from app.services.sync_worker import _describe_job_error

CLUSTER_ID = "/subscriptions/sub-1/resourceGroups/rg-aks/providers/Microsoft.ContainerService/managedClusters/aks-perf"


class _FakeCredential:
    """Issues token-1, token-2, … each valid for `lifetime` seconds from now."""

    def __init__(self, lifetime: float = 3600):
        self.lifetime = lifetime
        self.calls: list[str] = []

    def get_token(self, scope: str) -> AccessToken:
        self.calls.append(scope)
        return AccessToken(f"token-{len(self.calls)}", int(time.time() + self.lifetime))


@pytest.fixture
def credential(monkeypatch) -> _FakeCredential:
    cred = _FakeCredential()
    monkeypatch.setattr(aks_module, "get_azure_credential", lambda: cred)
    monkeypatch.setattr(AKSOperationsService, "_k8s_token", None)
    return cred


def test_token_is_reused_while_it_has_time_left(credential: _FakeCredential) -> None:
    assert AKSOperationsService._get_k8s_token() == "token-1"
    assert AKSOperationsService._get_k8s_token() == "token-1"
    assert credential.calls == [AKSOperationsService._K8S_TOKEN_SCOPE]


def test_token_is_renewed_before_it_expires(credential: _FakeCredential) -> None:
    credential.lifetime = 60  # inside the 5-minute renewal margin
    assert AKSOperationsService._get_k8s_token() == "token-1"
    credential.lifetime = 3600
    assert AKSOperationsService._get_k8s_token() == "token-2"


def test_refresh_hook_puts_a_current_token_on_every_request(credential: _FakeCredential) -> None:
    configuration = k8s_client.Configuration()
    configuration.api_key = {"authorization": "Bearer expired-at-build-time"}
    configuration.refresh_api_key_hook = _refresh_k8s_bearer

    # What the Kubernetes client calls when it adds auth headers to a request.
    assert configuration.get_api_key_with_prefix("authorization") == "Bearer token-1"
    assert configuration.auth_settings()["BearerToken"]["value"] == "Bearer token-1"


class _FakeManagedClusters:
    def list_cluster_user_credentials(self, resource_group: str, name: str) -> Any:
        kubeconfig = yaml.safe_dump(
            {"clusters": [{"cluster": {"server": "https://aks-perf.hcp.eastus2.azmk8s.io:443"}}]}
        ).encode()
        return SimpleNamespace(kubeconfigs=[SimpleNamespace(value=kubeconfig)])


@pytest.mark.anyio
async def test_built_clients_renew_the_token_themselves(credential: _FakeCredential, monkeypatch) -> None:
    monkeypatch.setattr(
        aks_module,
        "ContainerServiceClient",
        lambda cred, sub: SimpleNamespace(managed_clusters=_FakeManagedClusters()),
    )
    svc = AKSOperationsService.__new__(AKSOperationsService)
    svc.credential = credential

    credential.lifetime = 60  # the shared credential handed out a nearly expired token
    _, core_v1, _ = await svc._build_k8s_clients(CLUSTER_ID)
    configuration = core_v1.api_client.configuration
    assert configuration.api_key["authorization"] == "Bearer token-1"

    # Later requests on the cached client carry a renewed token, not the build-time one.
    credential.lifetime = 3600
    assert configuration.get_api_key_with_prefix("authorization") == "Bearer token-2"


@pytest.mark.anyio
async def test_helm_kubeconfig_gets_a_renewed_token(credential: _FakeCredential, tmp_path) -> None:
    configuration = k8s_client.Configuration()
    configuration.host = "https://aks-perf.hcp.eastus2.azmk8s.io:443"
    configuration.api_key = {"authorization": "Bearer expired-at-build-time"}
    configuration.refresh_api_key_hook = _refresh_k8s_bearer
    core_v1 = k8s_client.CoreV1Api(k8s_client.ApiClient(configuration))

    async def get_clients(cluster_id: str):
        return None, core_v1, None

    helm = AKSHelmService(SimpleNamespace(_get_k8s_clients=get_clients))
    path = await helm._kubeconfig_path(CLUSTER_ID)
    with open(path) as fh:
        kubeconfig = yaml.safe_load(fh)
    assert kubeconfig["users"][0]["user"]["token"] == "token-1"


def test_job_error_keeps_the_kubernetes_message_not_the_headers() -> None:
    exc = ApiException(status=401, reason="Unauthorized")
    exc.headers = {"Audit-Id": "82c6c1d4", "Cache-Control": "no-cache, private"}
    exc.body = json.dumps({"kind": "Status", "status": "Failure", "message": "Unauthorized", "code": 401})

    text = _describe_job_error(exc)

    assert text == "Kubernetes API 401 Unauthorized — the cluster's API server rejected the portal's Azure AD token"
    assert "Audit-Id" not in text


def test_job_error_includes_the_api_server_message_when_it_adds_something() -> None:
    exc = ApiException(status=403, reason="Forbidden")
    exc.body = json.dumps({"message": 'secrets is forbidden: User "x" cannot list resource "secrets"'})

    assert _describe_job_error(exc).startswith('Kubernetes API 403 Forbidden: secrets is forbidden: User "x"')
    assert _describe_job_error(RuntimeError("boom")) == "RuntimeError: boom"
