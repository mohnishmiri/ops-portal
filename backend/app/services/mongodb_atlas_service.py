"""
MongoDB Atlas Administration API v2 — the portal's only door to Atlas.

Authenticates with a programmatic API key over HTTP Digest
(``MONGODB_ATLAS_PUBLIC_KEY`` / ``_PRIVATE_KEY``). Every request names the
resource version it was written against in the ``Accept`` header; Atlas keeps
an old version working for 12–24 months after it is deprecated and announces
the sunset in ``Deprecation`` / ``Sunset`` response headers, which are logged.

Versions used (checked against MongoDB's published OpenAPI spec, Oct 2026):

* clusters — GET ``2024-08-05``; PATCH ``2024-10-23`` (pause/resume, tier);
* restartPrimaries ``2023-02-01``; alert acknowledge ``2024-05-30``;
* everything else ``2023-01-01`` (its only version).

Facts the code relies on, from the Atlas docs:

* pause/resume is ``PATCH …/clusters/{name}`` with ``{"paused": bool}``;
  M10+ only, not NVMe, not Free/Flex/Serverless; a cluster resumed less than
  60 minutes ago cannot be paused; a paused cluster resumes by itself after
  30 days; while paused only storage is billed;
* ``stateName`` is IDLE | CREATING | UPDATING | DELETING | REPAIRING — there is
  no "paused" state, the ``paused`` flag says it;
* no metric gives memory as a percentage; it is computed here from
  SYSTEM_MEMORY_USED and SYSTEM_MEMORY_AVAILABLE;
* a process does not name its cluster. It is matched by host name against the
  cluster's connection string (``userAlias`` is the name that appears there).
  That matching is an inference, not a documented contract.

Data is read live with short per-worker caches; nothing from Atlas is stored
in PostgreSQL except what an operation records about its own clusters.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import re
import secrets
import ssl
import string
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import certifi
import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

API_PREFIX = "/api/atlas/v2"
V_DEFAULT = "2023-01-01"
V_CLUSTER_GET = "2024-08-05"
V_CLUSTER_PATCH = "2024-10-23"
V_RESTART_PRIMARIES = "2023-02-01"
V_ALERT_ACK = "2024-05-30"
PAGE_SIZE = 500

# Chart period → sample size. Atlas keeps 1- and 5-minute samples for 48 hours
# and hourly samples for 63 days.
METRIC_PERIODS: dict[str, str] = {
    "PT1H": "PT1M",
    "PT6H": "PT5M",
    "PT24H": "PT5M",
    "P7D": "PT1H",
    "P30D": "PT1H",
}
_NODE_METRICS = (
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_AVAILABLE",
    "CONNECTIONS",
)
_DISK_METRIC = "DISK_PARTITION_SPACE_PERCENT_USED"

_ACCESS_LIST_CODES = ("WHITELIST", "ACCESS_LIST")
_FRIENDLY: dict[str, str] = {
    "CANNOT_PAUSE_RECENTLY_RESUMED_CLUSTER": (
        "Atlas will not pause a cluster within 60 minutes of resuming it. Try again later."
    ),
    "CANNOT_UPDATE_PAUSED_CLUSTER": "The cluster is paused or being paused. Start it before changing it.",
    "CLUSTER_ALREADY_PAUSED": "The cluster is already paused.",
    "CANNOT_UPDATE_AND_PAUSE_CLUSTER": "Atlas cannot change and pause a cluster in one step.",
    "CANNOT_PAUSE_CLUSTER_WITH_PENDING_CHANGES": (
        "The cluster still has changes being applied. Pause it once Atlas shows it as IDLE."
    ),
    "CANNOT_PAUSE_NVME_CLUSTER": "Clusters on NVMe storage cannot be paused.",
    "TENANT_CLUSTER_UPDATE_UNSUPPORTED": "Free and Flex clusters cannot be changed through the Atlas API.",
    "CLUSTER_RESTART_IN_PROGRESS": "A restart is already in progress on this cluster.",
    "TENANT_CLUSTER_TEST_FAILOVER_NOT_SUPPORTED": "Free and Flex clusters do not support test failover.",
    "RATE_LIMITED": "Atlas is rate-limiting the portal's API key. Try again in a minute.",
    "RATE_LIMITED_TOKEN_BUCKET": "Atlas is rate-limiting the portal's API key. Try again in a minute.",
    "CLUSTER_NOT_FOUND": "Cluster not found in that Atlas project.",
    "GROUP_NOT_FOUND": "Atlas project not found.",
    "USER_NOT_FOUND": "Database user not found.",
}


class AtlasError(Exception):
    """Atlas answered with an error, or could not be reached."""

    def __init__(self, status_code: int, detail: str, error_code: str | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code

    @property
    def user_message(self) -> str:
        code = self.error_code or ""
        if code in _FRIENDLY:
            return _FRIENDLY[code]
        if self.status_code == 403 and any(part in code for part in _ACCESS_LIST_CODES):
            return (
                "The portal's outbound IP address is not on the API access list of its Atlas API key "
                "(Atlas → Organization → Access Manager → API Keys). The Connection panel shows the address."
            )
        if self.status_code == 401:
            return "Atlas rejected the API key. Check MONGODB_ATLAS_PUBLIC_KEY and MONGODB_ATLAS_PRIVATE_KEY."
        if self.status_code == 403:
            return f"The portal's Atlas API key lacks the role for this action. {self.detail}".strip()
        return self.detail or f"Atlas returned HTTP {self.status_code}"


class AtlasNotConfiguredError(AtlasError):
    def __init__(self) -> None:
        super().__init__(
            503,
            "MongoDB Atlas is not configured: set MONGODB_ATLAS_PUBLIC_KEY and MONGODB_ATLAS_PRIVATE_KEY.",
            "NOT_CONFIGURED",
        )


def _tls_verify() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    with contextlib.suppress(OSError, ssl.SSLError):
        ctx.load_verify_locations(cafile=certifi.where())
    bundle = settings.MONGODB_ATLAS_CA_BUNDLE.strip()
    if bundle:
        ctx.load_verify_locations(cafile=bundle)
    return ctx


def _seg(value: str) -> str:
    """One path segment, fully percent-encoded ("10.0.0.0/24" → "10.0.0.0%2F24")."""
    return quote(value, safe="")


class AtlasClient:
    """Thin async HTTP client: digest auth, versioned Accept, 429 back-off, paging."""

    def __init__(
        self,
        *,
        base_url: str,
        public_key: str,
        private_key: str,
        timeout: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = httpx.DigestAuth(public_key, private_key)
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._warned_sunset: set[str] = set()

    def _http(self) -> httpx.AsyncClient:
        # asyncio objects belong to the loop that made them; tests run a new loop each time.
        loop = asyncio.get_running_loop()
        if self._client is None or self._loop is not loop or self._client.is_closed:
            kwargs: dict[str, Any] = {"auth": self._auth, "timeout": self._timeout}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            else:
                kwargs["verify"] = _tls_verify()
            self._client = httpx.AsyncClient(**kwargs)
            self._loop = loop
        return self._client

    async def request(
        self,
        method: str,
        path: str,
        *,
        version: str = V_DEFAULT,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self.base_url}{API_PREFIX}{path}"
        headers = {"Accept": f"application/vnd.atlas.{version}+json"}
        if json is not None:
            headers["Content-Type"] = f"application/vnd.atlas.{version}+json"
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = await self._http().request(method, url, params=params, json=json, headers=headers)
            except httpx.TimeoutException as exc:
                raise AtlasError(504, f"Atlas did not answer within {self._timeout:.0f}s", "TIMEOUT") from exc
            except httpx.HTTPError as exc:
                if method == "GET" and attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                raise AtlasError(502, f"Could not reach Atlas: {str(exc)[:200]}", "UNREACHABLE") from exc
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(self._retry_after(response, attempt))
                continue
            break
        assert response is not None
        self._log_sunset(path, version, response)
        if response.status_code >= 400:
            raise self._error(response)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AtlasError(502, "Atlas returned a response that is not JSON", "BAD_RESPONSE") from exc

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        try:
            wait = float(response.headers.get("Retry-After", ""))
        except ValueError:
            wait = 2.0 * (2**attempt)
        return min(max(wait, 0.5), 10.0) + random.uniform(0, 0.5)  # noqa: S311 — jitter, not crypto

    def _log_sunset(self, path: str, version: str, response: httpx.Response) -> None:
        sunset = response.headers.get("Sunset")
        if sunset and version not in self._warned_sunset:
            self._warned_sunset.add(version)
            logger.warning("atlas_api_version_deprecated", version=version, sunset=sunset, path=path)

    @staticmethod
    def _error(response: httpx.Response) -> AtlasError:
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        detail = str(body.get("detail") or body.get("reason") or response.text or "")
        return AtlasError(response.status_code, detail.strip()[:500], body.get("errorCode"))

    async def paged(
        self,
        path: str,
        *,
        version: str = V_DEFAULT,
        params: dict[str, Any] | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            data = await self.request(
                "GET",
                path,
                version=version,
                params={**(params or {}), "pageNum": page, "itemsPerPage": PAGE_SIZE},
            )
            results = (data or {}).get("results") or []
            items.extend(results)
            total = (data or {}).get("totalCount")
            if len(results) < PAGE_SIZE or len(items) >= limit or (total is not None and len(items) >= total):
                return items[:limit]
            page += 1


# ── Normalisation ───────────────────────────────────────────────────────

_TIER_RE = re.compile(r"^[MR](\d+)")
_PROD_WORDS = {"prod", "prd", "production", "dr"}
_NONPROD_WORDS = {
    "nonprod",
    "nprd",
    "npe",
    "dev",
    "development",
    "test",
    "tst",
    "qa",
    "uat",
    "sit",
    "perf",
    "stage",
    "staging",
    "stg",
    "sandbox",
    "preprod",
    "poc",
    "demo",
}
_ENV_TAG_KEYS = {"environment", "env", "stage", "tier"}


def classify_environment(tags: dict[str, str], *names: str | None) -> str:
    """production | non_production | unclassified.

    An ``environment`` (or ``env``) tag on the cluster decides; otherwise the
    cluster and project names. Unclassified clusters are treated like
    production for confirmations — tag them to change that.
    """
    for key, value in tags.items():
        if key.lower() in _ENV_TAG_KEYS and value:
            words = set(re.split(r"[^a-z0-9]+", value.lower()))
            if words & _NONPROD_WORDS:
                return "non_production"
            if words & _PROD_WORDS:
                return "production"
    words: set[str] = set()
    for name in names:
        words |= set(re.split(r"[^a-z0-9]+", (name or "").lower()))
    if words & _NONPROD_WORDS:
        return "non_production"
    if words & _PROD_WORDS:
        return "production"
    return "unclassified"


def pause_rules(tier: str | None, provider: str | None) -> tuple[bool, str | None]:
    """(pausable, why not) from the Atlas rules: M10+, no NVMe, no Free/Flex/Serverless."""
    if (provider or "").upper() in ("TENANT", "FLEX", "SERVERLESS"):
        return False, "Free, Flex and Serverless clusters cannot be paused"
    if not tier:
        return False, "Atlas did not report the cluster tier"
    if tier.upper().endswith("_NVME"):
        return False, "Clusters on NVMe storage cannot be paused"
    match = _TIER_RE.match(tier.upper())
    if not match or int(match.group(1)) < 10:
        return False, "Only M10 and larger clusters can be paused"
    return True, None


def _hosts(connection_string: str | None) -> list[str]:
    """Host names (lower case, no port) from a mongodb:// connection string."""
    if not connection_string or not connection_string.startswith("mongodb://"):
        return []
    hosts = connection_string[len("mongodb://") :].split("/", 1)[0].split("@")[-1]
    return [h.rsplit(":", 1)[0].lower() for h in hosts.split(",") if h]


def normalize_cluster(raw: dict, project: dict) -> dict:
    specs = raw.get("replicationSpecs") or []
    region_configs = [rc for spec in specs for rc in (spec.get("regionConfigs") or [])]
    first = region_configs[0] if region_configs else {}
    electable = first.get("electableSpecs") or {}
    provider = first.get("providerName")
    if provider == "TENANT":
        provider_label = f"{first.get('backingProviderName') or ''} (shared)".strip()
    else:
        provider_label = provider
    tier = electable.get("instanceSize")
    pausable, blocker = pause_rules(tier, provider)

    def _nodes(rc: dict) -> int:
        return sum(
            int((rc.get(k) or {}).get("nodeCount") or 0) for k in ("electableSpecs", "readOnlySpecs", "analyticsSpecs")
        )

    compute = ((first.get("autoScaling") or {}).get("compute")) or {}
    disk_auto = ((first.get("autoScaling") or {}).get("diskGB")) or {}
    tags = {t.get("key"): t.get("value") for t in raw.get("tags") or [] if t.get("key")}
    environment = classify_environment(tags, raw.get("name"), project.get("name"))
    connection = raw.get("connectionStrings") or {}
    paused = bool(raw.get("paused"))
    state = raw.get("stateName")
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "project_id": raw.get("groupId") or project.get("id"),
        "project_name": project.get("name"),
        "state": state,
        "paused": paused,
        "status": "paused" if paused else ("running" if state == "IDLE" else (state or "unknown").lower()),
        "tier": tier,
        "provider": provider_label,
        "regions": sorted({rc.get("regionName") for rc in region_configs if rc.get("regionName")}),
        "cluster_type": raw.get("clusterType"),
        "mongo_version": raw.get("mongoDBVersion"),
        "mongo_major_version": raw.get("mongoDBMajorVersion"),
        "disk_size_gb": electable.get("diskSizeGB"),
        "node_count": sum(_nodes(rc) for rc in region_configs),
        "shard_count": len(specs),
        "backup_enabled": bool(raw.get("backupEnabled")),
        "pit_enabled": bool(raw.get("pitEnabled")),
        "termination_protection": bool(raw.get("terminationProtectionEnabled")),
        "tags": [{"key": k, "value": v} for k, v in tags.items()],
        "connection_string": connection.get("standardSrv") or connection.get("standard"),
        "hosts": _hosts(connection.get("standard")),
        "created_at": raw.get("createDate"),
        "autoscaling": {
            "compute_enabled": bool(compute.get("enabled")),
            "scale_down_enabled": bool(compute.get("scaleDownEnabled")),
            "min_tier": compute.get("minInstanceSize"),
            "max_tier": compute.get("maxInstanceSize"),
            "disk_enabled": bool(disk_auto.get("enabled")),
        },
        "pausable": pausable,
        "pause_blocker": blocker,
        "environment": environment,
        # Unclassified counts as production: a typed name is a small price
        # against stopping the wrong cluster.
        "is_production": environment != "non_production",
    }


def _tier_number(tier: str | None) -> int | None:
    match = _TIER_RE.match((tier or "").upper())
    return int(match.group(1)) if match else None


def _role_label(type_name: str | None) -> str:
    return {
        "REPLICA_PRIMARY": "Primary",
        "REPLICA_SECONDARY": "Secondary",
        "SHARD_PRIMARY": "Primary",
        "SHARD_SECONDARY": "Secondary",
        "SHARD_CONFIG": "Config server",
        "SHARD_MONGOS": "mongos",
        "RECOVERING": "Recovering",
    }.get(type_name or "", (type_name or "Node").replace("_", " ").title())


def match_cluster_processes(cluster: dict, processes: list[dict]) -> list[dict]:
    """The cluster's nodes among the project's processes, one per host.

    Matched on the hosts in the cluster's connection string, falling back to
    the "<cluster-name>-" host prefix Atlas uses. A host running both mongod
    and mongos (sharded clusters) is listed once, as its mongod.
    """
    hosts = set(cluster.get("hosts") or [])
    prefix = f"{(cluster.get('name') or '').lower()}-"

    def _alias(p: dict) -> str:
        return (p.get("userAlias") or p.get("hostname") or "").lower()

    matched = [p for p in processes if _alias(p) in hosts or (p.get("hostname") or "").lower() in hosts]
    if not matched and prefix != "-":
        matched = [p for p in processes if _alias(p).startswith(prefix)]

    by_host: dict[str, dict] = {}
    for process in matched:
        host = _alias(process)
        current = by_host.get(host)
        if current is None or (current.get("typeName") == "SHARD_MONGOS" and process.get("typeName") != "SHARD_MONGOS"):
            by_host[host] = process
    nodes = sorted(by_host.values(), key=lambda p: (_role_label(p.get("typeName")) != "Primary", _alias(p)))
    return nodes


def _short_host(host: str) -> str:
    """ "cluster0-shard-00-01.abc12.mongodb.net" → "shard-00-01"."""
    label = host.split(".", 1)[0]
    match = re.search(r"(shard-\d+-\d+|config-\d+-\d+)$", label)
    return match.group(1) if match else label


def _ts(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("+00:00", "Z")


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 24) -> str:
    """Letters and digits only — safe to paste into a connection string unescaped."""
    while True:
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


# ── Service ─────────────────────────────────────────────────────────────


class AtlasService:
    PROJECT_TTL = 300.0
    CLUSTER_TTL = 30.0
    PROCESS_TTL = 60.0
    METRICS_TTL = 60.0
    UTILIZATION_TTL = 120.0

    def __init__(self, client: AtlasClient | None = None) -> None:
        self._client = client
        self._cache: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ── plumbing ────────────────────────────────────────────────────────

    @property
    def client(self) -> AtlasClient:
        if self._client is None:
            if not settings.mongodb_atlas_configured:
                raise AtlasNotConfiguredError()
            self._client = AtlasClient(
                base_url=settings.MONGODB_ATLAS_BASE_URL,
                public_key=settings.MONGODB_ATLAS_PUBLIC_KEY.strip(),
                private_key=settings.MONGODB_ATLAS_PRIVATE_KEY.strip(),
                timeout=settings.MONGODB_ATLAS_TIMEOUT_SECONDS,
            )
        return self._client

    async def _cached(self, key: str, ttl: float, fresh: bool, loader: Callable[[], Awaitable[Any]]) -> Any:
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and not fresh and hit[0] > now:
            return hit[1]
        value = await loader()
        self._cache[key] = (time.monotonic() + ttl, value)
        return value

    def invalidate(self, project_id: str | None = None) -> None:
        if project_id is None:
            self._cache.clear()
            return
        for key in [k for k in self._cache if project_id in k]:
            self._cache.pop(key, None)

    # ── connection ──────────────────────────────────────────────────────

    async def status(self) -> dict:
        public_key = settings.MONGODB_ATLAS_PUBLIC_KEY.strip()
        base: dict[str, Any] = {
            "configured": settings.mongodb_atlas_configured,
            "base_url": settings.MONGODB_ATLAS_BASE_URL,
            "public_key": f"{public_key[:4]}{'•' * 4}" if public_key else None,
            "org_filter": settings.MONGODB_ATLAS_ORG_ID.strip() or None,
            "project_allowlist": sorted(settings.mongodb_atlas_project_allowlist),
            "operation_timeout_minutes": settings.MONGODB_ATLAS_OPERATION_TIMEOUT_MINUTES,
            "reachable": False,
            "error": None,
            "portal_ip": None,
            "api_key_roles": [],
            "project_count": 0,
            "checked_at": _iso_z(datetime.now(UTC)),
        }
        if not settings.mongodb_atlas_configured:
            base["error"] = AtlasNotConfiguredError().detail
            return base
        try:
            me = await self.client.request("GET", "")
        except AtlasError as exc:
            me = None
            base["error"] = exc.user_message
            base["error_code"] = exc.error_code
        if me:
            base["portal_ip"] = me.get("ipAddress")
            key = me.get("apiKey") or {}
            base["api_key_roles"] = [
                {
                    "scope": "organization" if role.get("orgId") else "project",
                    "id": role.get("orgId") or role.get("groupId"),
                    "role": role.get("roleName"),
                }
                for role in key.get("roles") or []
            ]
        try:
            projects = await self.list_projects(fresh=True)
            base["reachable"] = True
            base["project_count"] = len(projects)
            base["error"] = None if me else base["error"]
        except AtlasError as exc:
            base["error"] = exc.user_message
            base["error_code"] = exc.error_code
        return base

    # ── projects & clusters ─────────────────────────────────────────────

    async def list_projects(self, fresh: bool = False) -> list[dict]:
        async def _load() -> list[dict]:
            raw = await self.client.paged("/groups")
            org = settings.MONGODB_ATLAS_ORG_ID.strip()
            allow = {p.lower() for p in settings.mongodb_atlas_project_allowlist}
            projects = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "org_id": p.get("orgId"),
                    "cluster_count": p.get("clusterCount"),
                    "created_at": p.get("created"),
                }
                for p in raw
                if (not org or p.get("orgId") == org) and (not allow or (p.get("id") or "").lower() in allow)
            ]
            return sorted(projects, key=lambda p: (p["name"] or "").lower())

        return await self._cached("projects", self.PROJECT_TTL, fresh, _load)

    async def ensure_project(self, project_id: str) -> dict:
        """The project, if the portal may act on it; else 404 (also outside the allow-list)."""
        for fresh in (False, True):
            for project in await self.list_projects(fresh=fresh):
                if (project["id"] or "").lower() == project_id.lower():
                    return project
        raise AtlasError(
            404, "Atlas project not found, or not one the portal is configured to manage.", "GROUP_NOT_FOUND"
        )

    async def _project_clusters(self, project: dict, fresh: bool) -> list[dict]:
        async def _load() -> list[dict]:
            raw = await self.client.paged(f"/groups/{_seg(project['id'])}/clusters", version=V_CLUSTER_GET)
            return [normalize_cluster(c, project) for c in raw]

        return await self._cached(f"clusters:{project['id']}", self.CLUSTER_TTL, fresh, _load)

    async def list_clusters(self, project_id: str | None = None, fresh: bool = False) -> dict:
        projects = [await self.ensure_project(project_id)] if project_id else await self.list_projects(fresh=fresh)
        semaphore = asyncio.Semaphore(4)

        async def _one(project: dict) -> list[dict]:
            async with semaphore:
                return await self._project_clusters(project, fresh)

        results = await asyncio.gather(*(_one(p) for p in projects), return_exceptions=True)
        clusters: list[dict] = []
        errors: list[dict] = []
        for project, result in zip(projects, results, strict=True):
            if isinstance(result, BaseException):
                message = result.user_message if isinstance(result, AtlasError) else str(result)[:200]
                errors.append({"project_id": project["id"], "project_name": project["name"], "error": message})
                logger.warning("atlas_project_clusters_failed", project=project["name"], error=message)
                continue
            clusters.extend(result)
        clusters.sort(key=lambda c: ((c["project_name"] or "").lower(), (c["name"] or "").lower()))
        return {
            "clusters": clusters,
            "errors": errors,
            "project_count": len(projects),
            "fetched_at": _iso_z(datetime.now(UTC)),
        }

    async def _raw_cluster(self, project_id: str, cluster_name: str) -> dict:
        return await self.client.request(
            "GET", f"/groups/{_seg(project_id)}/clusters/{_seg(cluster_name)}", version=V_CLUSTER_GET
        )

    async def get_cluster(self, project_id: str, cluster_name: str, *, fresh: bool = False) -> dict:
        project = await self.ensure_project(project_id)
        if not fresh:
            for cluster in await self._project_clusters(project, fresh=False):
                if cluster["name"] == cluster_name:
                    return cluster
        try:
            raw = await self._raw_cluster(project["id"], cluster_name)
        except AtlasError as exc:
            if exc.status_code == 404:
                raise AtlasError(
                    404, f"Cluster {cluster_name} not found in {project['name']}", "CLUSTER_NOT_FOUND"
                ) from exc
            raise
        return normalize_cluster(raw, project)

    # ── stop / start ────────────────────────────────────────────────────

    async def request_power(self, project_id: str, cluster_name: str, *, pause: bool) -> str:
        """Ask Atlas to pause or resume. Returns "requested" or "no_change"."""
        cluster = await self.get_cluster(project_id, cluster_name, fresh=True)
        if cluster["paused"] is pause and cluster["state"] == "IDLE":
            return "no_change"
        if pause and not cluster["pausable"]:
            raise AtlasError(400, cluster["pause_blocker"] or "This cluster cannot be paused", "NOT_PAUSABLE")
        if cluster["state"] != "IDLE":
            raise AtlasError(
                409,
                f"Atlas is busy with this cluster (state {cluster['state']}). Try again once it is IDLE.",
                "CLUSTER_BUSY",
            )
        await self.client.request(
            "PATCH",
            f"/groups/{_seg(cluster['project_id'])}/clusters/{_seg(cluster_name)}",
            version=V_CLUSTER_PATCH,
            json={"paused": pause},
        )
        self.invalidate(cluster["project_id"])
        logger.info("atlas_power_requested", project=cluster["project_name"], cluster=cluster_name, pause=pause)
        return "requested"

    # ── cluster administration ──────────────────────────────────────────

    async def change_tier(self, project_id: str, cluster_name: str, instance_size: str) -> dict:
        """Set every electable and read-only node to ``instance_size``.

        The PATCH carries each existing replication spec with its ``id`` —
        Atlas deletes any shard a PATCH leaves out — and drops the read-only
        ``effective*`` fields. Analytics nodes keep their own size.
        """
        project = await self.ensure_project(project_id)
        raw = await self._raw_cluster(project["id"], cluster_name)
        cluster = normalize_cluster(raw, project)
        size = instance_size.upper()
        if cluster["paused"]:
            raise AtlasError(409, _FRIENDLY["CANNOT_UPDATE_PAUSED_CLUSTER"], "CANNOT_UPDATE_PAUSED_CLUSTER")
        if cluster["state"] != "IDLE":
            raise AtlasError(409, f"Atlas is busy with this cluster (state {cluster['state']}).", "CLUSTER_BUSY")
        if (cluster["provider"] or "").endswith("(shared)") or not cluster["tier"]:
            raise AtlasError(400, _FRIENDLY["TENANT_CLUSTER_UPDATE_UNSUPPORTED"], "TENANT_CLUSTER_UPDATE_UNSUPPORTED")
        if size == (cluster["tier"] or "").upper():
            raise AtlasError(400, f"The cluster is already {size}.", "NO_CHANGE")
        auto = cluster["autoscaling"]
        if auto["compute_enabled"]:
            low, high, want = _tier_number(auto["min_tier"]), _tier_number(auto["max_tier"]), _tier_number(size)
            if want is not None and ((low and want < low) or (high and want > high)):
                raise AtlasError(
                    400,
                    f"Compute auto-scaling keeps this cluster between {auto['min_tier']} and {auto['max_tier']}. "
                    "Change those limits in Atlas first.",
                    "OUTSIDE_AUTOSCALING_RANGE",
                )

        specs: list[dict] = []
        for spec in raw.get("replicationSpecs") or []:
            region_configs = []
            for rc in spec.get("regionConfigs") or []:
                updated = {k: v for k, v in rc.items() if not k.startswith("effective")}
                for key in ("electableSpecs", "readOnlySpecs"):
                    hardware = updated.get(key)
                    if hardware and hardware.get("instanceSize"):
                        hardware = {**hardware, "instanceSize": size}
                        # Standard-volume IOPS follow the tier; let Atlas recompute them.
                        if (hardware.get("ebsVolumeType") or "STANDARD") == "STANDARD":
                            hardware.pop("diskIOPS", None)
                            hardware.pop("diskThroughput", None)
                        updated[key] = hardware
                region_configs.append(updated)
            entry = {"id": spec.get("id"), "zoneName": spec.get("zoneName"), "regionConfigs": region_configs}
            specs.append({k: v for k, v in entry.items() if v is not None})

        result = await self.client.request(
            "PATCH",
            f"/groups/{_seg(project['id'])}/clusters/{_seg(cluster_name)}",
            version=V_CLUSTER_PATCH,
            json={"replicationSpecs": specs},
        )
        self.invalidate(project["id"])
        return normalize_cluster(result or raw, project)

    async def test_failover(self, project_id: str, cluster_name: str) -> dict:
        project = await self.ensure_project(project_id)
        await self.client.request(
            "POST",
            f"/groups/{_seg(project['id'])}/clusters/{_seg(cluster_name)}/restartPrimaries",
            version=V_RESTART_PRIMARIES,
        )
        self.invalidate(project["id"])
        return {"requested": True, "cluster_name": cluster_name}

    async def list_snapshots(self, project_id: str, cluster_name: str) -> dict:
        project = await self.ensure_project(project_id)
        raw = await self.client.paged(
            f"/groups/{_seg(project['id'])}/clusters/{_seg(cluster_name)}/backup/snapshots", limit=1000
        )
        snapshots = sorted((_snapshot(s) for s in raw), key=lambda s: s["created_at"] or "", reverse=True)
        return {"snapshots": snapshots, "count": len(snapshots)}

    async def take_snapshot(self, project_id: str, cluster_name: str, description: str, retention_days: int) -> dict:
        project = await self.ensure_project(project_id)
        result = await self.client.request(
            "POST",
            f"/groups/{_seg(project['id'])}/clusters/{_seg(cluster_name)}/backup/snapshots",
            json={"description": description, "retentionInDays": retention_days},
        )
        return _snapshot(result or {})

    # ── alerts & events ─────────────────────────────────────────────────

    async def list_alerts(self, project_id: str, status: str | None) -> dict:
        project = await self.ensure_project(project_id)
        params = {"status": status} if status else None
        raw = await self.client.paged(f"/groups/{_seg(project['id'])}/alerts", params=params, limit=1000)
        alerts = sorted((_alert(a) for a in raw), key=lambda a: a["created_at"] or "", reverse=True)
        return {"alerts": alerts, "count": len(alerts)}

    async def acknowledge_alert(
        self,
        project_id: str,
        alert_id: str,
        *,
        until: datetime | None,
        comment: str,
        unacknowledge: bool,
    ) -> dict:
        project = await self.ensure_project(project_id)
        body: dict[str, Any] = {"acknowledgementComment": comment[:200]}
        if unacknowledge:
            body["unacknowledgeAlert"] = True
        else:
            # Atlas's convention for "until it closes" is a date far in the future.
            body["acknowledgedUntil"] = _iso_z(until or datetime.now(UTC) + timedelta(days=365 * 100))
        result = await self.client.request(
            "PATCH", f"/groups/{_seg(project['id'])}/alerts/{_seg(alert_id)}", version=V_ALERT_ACK, json=body
        )
        return _alert(result or {"id": alert_id})

    async def list_events(self, project_id: str, *, cluster_name: str | None, page: int, page_size: int) -> dict:
        project = await self.ensure_project(project_id)
        params: dict[str, Any] = {"pageNum": page, "itemsPerPage": page_size, "includeCount": "true"}
        if cluster_name:
            params["clusterNames"] = cluster_name
        data = await self.client.request("GET", f"/groups/{_seg(project['id'])}/events", params=params) or {}
        events = [_event(e) for e in data.get("results") or []]
        return {"events": events, "total": data.get("totalCount"), "page": page, "page_size": page_size}

    # ── database users ──────────────────────────────────────────────────

    async def list_database_users(self, project_id: str) -> dict:
        project = await self.ensure_project(project_id)
        raw = await self.client.paged(f"/groups/{_seg(project['id'])}/databaseUsers", limit=1000)
        users = sorted((_db_user(u) for u in raw), key=lambda u: u["username"].lower())
        return {"users": users, "count": len(users)}

    async def create_database_user(self, project_id: str, body: Any) -> dict:
        project = await self.ensure_project(project_id)
        generated = body.password is None
        password = body.password or generate_password()
        payload: dict[str, Any] = {
            "databaseName": "admin",
            "groupId": project["id"],
            "username": body.username,
            "password": password,
            "roles": [_role_payload(r) for r in body.roles],
        }
        if body.scopes:
            payload["scopes"] = [{"name": s.name, "type": s.type} for s in body.scopes]
        if body.description:
            payload["description"] = body.description
        if body.delete_after_date:
            payload["deleteAfterDate"] = _iso_z(body.delete_after_date)
        result = await self.client.request("POST", f"/groups/{_seg(project['id'])}/databaseUsers", json=payload)
        return {
            "user": _db_user(result or payload),
            # Shown once to whoever created it; never stored or logged.
            "password": password if generated else None,
            "password_generated": generated,
        }

    async def update_database_user(self, project_id: str, username: str, auth_database: str, body: Any) -> dict:
        project = await self.ensure_project(project_id)
        payload: dict[str, Any] = {}
        if body.roles is not None:
            payload["roles"] = [_role_payload(r) for r in body.roles]
        if body.scopes is not None:
            payload["scopes"] = [{"name": s.name, "type": s.type} for s in body.scopes]
        if body.description is not None:
            payload["description"] = body.description
        password = None
        if body.reset_password:
            if auth_database != "admin":
                raise AtlasError(400, "Only password (SCRAM) users have a password to reset.", "NOT_SCRAM")
            password = generate_password()
            payload["password"] = password
        if not payload:
            raise AtlasError(400, "Nothing to change.", "NO_CHANGE")
        result = await self.client.request(
            "PATCH",
            f"/groups/{_seg(project['id'])}/databaseUsers/{_seg(auth_database)}/{_seg(username)}",
            json=payload,
        )
        return {"user": _db_user(result or {"username": username, "databaseName": auth_database}), "password": password}

    async def delete_database_user(self, project_id: str, username: str, auth_database: str) -> None:
        project = await self.ensure_project(project_id)
        await self.client.request(
            "DELETE", f"/groups/{_seg(project['id'])}/databaseUsers/{_seg(auth_database)}/{_seg(username)}"
        )

    # ── IP access list ──────────────────────────────────────────────────

    async def list_access_list(self, project_id: str) -> dict:
        project = await self.ensure_project(project_id)
        raw = await self.client.paged(f"/groups/{_seg(project['id'])}/accessList", limit=2000)
        entries = sorted((_access_entry(e) for e in raw), key=lambda e: e["entry"])
        return {"entries": entries, "count": len(entries)}

    async def add_access_list_entry(
        self, project_id: str, entry: str, *, comment: str | None, delete_after: datetime | None
    ) -> dict:
        project = await self.ensure_project(project_id)
        item: dict[str, Any] = {"cidrBlock" if "/" in entry else "ipAddress": entry}
        if comment:
            item["comment"] = comment
        if delete_after:
            item["deleteAfterDate"] = _iso_z(delete_after)
        # Atlas does not support concurrent POSTs to one project's access list.
        lock = self._locks.setdefault(f"access:{project['id']}", asyncio.Lock())
        async with lock:
            await self.client.request("POST", f"/groups/{_seg(project['id'])}/accessList", json=[item])
        return {"added": _access_entry(item)}

    async def delete_access_list_entry(self, project_id: str, entry: str) -> None:
        project = await self.ensure_project(project_id)
        await self.client.request("DELETE", f"/groups/{_seg(project['id'])}/accessList/{_seg(entry)}")

    # ── utilization ─────────────────────────────────────────────────────

    async def _processes(self, project_id: str, fresh: bool = False) -> list[dict]:
        return await self._cached(
            f"processes:{project_id}",
            self.PROCESS_TTL,
            fresh,
            lambda: self.client.paged(f"/groups/{_seg(project_id)}/processes"),
        )

    async def _measurements(self, project_id: str, process_id: str, granularity: str, period: str) -> dict:
        return await self.client.request(
            "GET",
            f"/groups/{_seg(project_id)}/processes/{_seg(process_id)}/measurements",
            params={"granularity": granularity, "period": period, "m": list(_NODE_METRICS)},
        )

    async def _disk_series(self, project_id: str, process_id: str, granularity: str, period: str) -> list[dict]:
        disks = await self.client.paged(f"/groups/{_seg(project_id)}/processes/{_seg(process_id)}/disks", limit=20)
        names = [d.get("partitionName") for d in disks if d.get("partitionName")]
        if not names:
            return []
        partition = "data" if "data" in names else names[0]
        data = await self.client.request(
            "GET",
            f"/groups/{_seg(project_id)}/processes/{_seg(process_id)}/disks/{_seg(partition)}/measurements",
            params={"granularity": granularity, "period": period, "m": _DISK_METRIC},
        )
        for measurement in (data or {}).get("measurements") or []:
            if measurement.get("name") == _DISK_METRIC:
                return measurement.get("dataPoints") or []
        return []

    async def cluster_metrics(self, project_id: str, cluster_name: str, period: str) -> dict:
        granularity = METRIC_PERIODS[period]
        cluster = await self.get_cluster(project_id, cluster_name)
        project_id = cluster["project_id"]
        result: dict[str, Any] = {
            "cluster_name": cluster_name,
            "project_id": project_id,
            "period": period,
            "granularity": granularity,
            "paused": cluster["paused"],
            "nodes": [],
            "series": {"cpu": [], "memory": [], "connections": [], "disk": []},
            "latest": {},
            "notes": [],
        }
        if cluster["paused"]:
            result["notes"].append("The cluster is paused; Atlas records no metrics while it is stopped.")

        async def _load() -> dict:
            processes = await self._processes(project_id)
            nodes = match_cluster_processes(cluster, processes)
            if not nodes:
                result["notes"].append(
                    "No monitored processes matched this cluster's hosts — Atlas may still be starting it."
                )
                return result
            semaphore = asyncio.Semaphore(4)

            async def _node(process: dict) -> tuple[dict, list[dict]]:
                async with semaphore:
                    data = await self._measurements(project_id, process["id"], granularity, period)
                    try:
                        disk = await self._disk_series(project_id, process["id"], granularity, period)
                    except AtlasError as exc:
                        logger.info("atlas_disk_metrics_unavailable", process=process["id"], error=exc.user_message)
                        disk = []
                    return data or {}, disk

            fetched = await asyncio.gather(*(_node(p) for p in nodes))
            rows: dict[str, dict[str, dict]] = {"cpu": {}, "memory": {}, "connections": {}, "disk": {}}
            for index, (process, (data, disk)) in enumerate(zip(nodes, fetched, strict=True)):
                key = f"n{index}"
                host = (process.get("userAlias") or process.get("hostname") or "").lower()
                result["nodes"].append(
                    {
                        "key": key,
                        "id": process.get("id"),
                        "host": host,
                        "label": _short_host(host),
                        "role": _role_label(process.get("typeName")),
                        "type_name": process.get("typeName"),
                    }
                )
                points = {m.get("name"): m.get("dataPoints") or [] for m in data.get("measurements") or []}
                _merge_node_series(rows, key, points, disk)
            for metric, by_time in rows.items():
                result["series"][metric] = [by_time[t] for t in sorted(by_time)]
            result["latest"] = _latest(result["series"], [n["key"] for n in result["nodes"]])
            return result

        if cluster["paused"]:
            return result
        return await self._cached(f"metrics:{project_id}:{cluster_name}:{period}", self.METRICS_TTL, False, _load)

    async def fleet_utilization(self, fresh: bool = False) -> dict:
        """Latest CPU and memory of each running cluster (its busiest node)."""

        async def _load() -> dict:
            inventory = await self.list_clusters()
            running = [c for c in inventory["clusters"] if not c["paused"] and c["state"] != "CREATING"]
            semaphore = asyncio.Semaphore(6)
            out: dict[str, dict] = {}

            async def _one(cluster: dict) -> None:
                async with semaphore:
                    try:
                        nodes = match_cluster_processes(cluster, await self._processes(cluster["project_id"]))
                        cpu: list[float] = []
                        memory: list[float] = []
                        at: str | None = None
                        for process in nodes:
                            data = await self.client.request(
                                "GET",
                                f"/groups/{_seg(cluster['project_id'])}/processes/{_seg(process['id'])}/measurements",
                                params={"granularity": "PT5M", "period": "PT30M", "m": list(_NODE_METRICS[:4])},
                            )
                            points = {
                                m.get("name"): m.get("dataPoints") or [] for m in (data or {}).get("measurements") or []
                            }
                            node_cpu = _last_value(
                                _sum_series(points, "SYSTEM_NORMALIZED_CPU_USER", "SYSTEM_NORMALIZED_CPU_KERNEL")
                            )
                            node_memory = _last_value(_memory_series(points))
                            if node_cpu:
                                cpu.append(node_cpu[1])
                                at = max(at or node_cpu[0], node_cpu[0])
                            if node_memory:
                                memory.append(node_memory[1])
                        out[f"{cluster['project_id']}/{cluster['name']}"] = {
                            "cpu": round(max(cpu), 1) if cpu else None,
                            "memory": round(max(memory), 1) if memory else None,
                            "nodes": len(nodes),
                            "at": at,
                        }
                    except AtlasError as exc:
                        out[f"{cluster['project_id']}/{cluster['name']}"] = {
                            "cpu": None,
                            "memory": None,
                            "error": exc.user_message,
                        }

            await asyncio.gather(*(_one(c) for c in running))
            return {"clusters": out, "fetched_at": _iso_z(datetime.now(UTC))}

        return await self._cached("utilization", self.UTILIZATION_TTL, fresh, _load)


# ── metric helpers ──────────────────────────────────────────────────────


def _by_time(points: list[dict]) -> dict[str, float | None]:
    return {p.get("timestamp"): p.get("value") for p in points if p.get("timestamp")}


def _sum_series(points: dict[str, list[dict]], *names: str) -> list[tuple[str, float | None]]:
    columns = [_by_time(points.get(name) or []) for name in names]
    times = sorted(set().union(*columns)) if columns else []
    out: list[tuple[str, float | None]] = []
    for t in times:
        values = [c.get(t) for c in columns]
        out.append((t, None if any(v is None for v in values) else round(sum(values), 2)))  # type: ignore[arg-type]
    return out


def _memory_series(points: dict[str, list[dict]]) -> list[tuple[str, float | None]]:
    """Memory in use, %: used ÷ (used + available) — Atlas has no percentage metric."""
    used = _by_time(points.get("SYSTEM_MEMORY_USED") or [])
    available = _by_time(points.get("SYSTEM_MEMORY_AVAILABLE") or [])
    out: list[tuple[str, float | None]] = []
    for t in sorted(set(used) | set(available)):
        u, a = used.get(t), available.get(t)
        out.append((t, round(100 * u / (u + a), 1) if u is not None and a is not None and (u + a) > 0 else None))
    return out


def _last_value(series: list[tuple[str, float | None]]) -> tuple[str, float] | None:
    for t, v in reversed(series):
        if v is not None:
            return t, v
    return None


def _merge_node_series(
    rows: dict[str, dict[str, dict]], key: str, points: dict[str, list[dict]], disk: list[dict]
) -> None:
    def _put(metric: str, series: list[tuple[str, float | None]]) -> None:
        for t, v in series:
            row = rows[metric].setdefault(t, {"time": _ts(t)})
            row[key] = v

    _put("cpu", _sum_series(points, "SYSTEM_NORMALIZED_CPU_USER", "SYSTEM_NORMALIZED_CPU_KERNEL"))
    _put("memory", _memory_series(points))
    _put("connections", [(t, v) for t, v in _by_time(points.get("CONNECTIONS") or []).items()])
    _put("disk", [(p.get("timestamp"), None if p.get("value") is None else round(p["value"], 1)) for p in disk])


def _latest(series: dict[str, list[dict]], keys: list[str]) -> dict:
    latest: dict[str, Any] = {}
    for metric, rows in series.items():
        values = []
        for key in keys:
            for row in reversed(rows):
                if row.get(key) is not None:
                    values.append(row[key])
                    break
        if not values:
            latest[metric] = None
        elif metric == "connections":
            latest[metric] = round(sum(values))
        else:
            latest[metric] = round(max(values), 1)
    return latest


# ── record shapes ───────────────────────────────────────────────────────


def _snapshot(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "created_at": raw.get("createdAt"),
        "expires_at": raw.get("expiresAt"),
        "status": raw.get("status"),
        "type": raw.get("snapshotType"),
        "frequency": raw.get("frequencyType"),
        "size_bytes": raw.get("storageSizeBytes"),
        "description": raw.get("description"),
        "mongod_version": raw.get("mongodVersion"),
        "cloud_provider": raw.get("cloudProvider"),
    }


def _alert(raw: dict) -> dict:
    current = raw.get("currentValue") or {}
    value = current.get("number")
    return {
        "id": raw.get("id"),
        "event_type": raw.get("eventTypeName"),
        "status": raw.get("status"),
        "severity": raw.get("severity"),
        "created_at": raw.get("created"),
        "updated_at": raw.get("updated"),
        "resolved_at": raw.get("resolved"),
        "cluster_name": raw.get("clusterName"),
        "host": raw.get("hostnameAndPort"),
        "replica_set": raw.get("replicaSetName"),
        "metric_name": raw.get("metricName"),
        "current_value": None if value is None else f"{round(value, 2)} {current.get('units') or ''}".strip(),
        "acknowledged_until": raw.get("acknowledgedUntil"),
        "acknowledged_by": raw.get("acknowledgingUsername"),
        "acknowledgement_comment": raw.get("acknowledgementComment"),
    }


def _event(raw: dict) -> dict:
    who = raw.get("username") or (f"API key {raw['publicKey']}" if raw.get("publicKey") else None)
    return {
        "id": raw.get("id"),
        "created_at": raw.get("created"),
        "event_type": raw.get("eventTypeName"),
        "description": (raw.get("eventTypeName") or "").replace("_", " ").capitalize(),
        "cluster_name": raw.get("clusterName"),
        "replica_set": raw.get("replicaSetName"),
        "host": raw.get("hostname"),
        "actor": who or "Atlas",
        "remote_address": raw.get("remoteAddress"),
    }


def _db_user(raw: dict) -> dict:
    if raw.get("x509Type") not in (None, "NONE"):
        auth = "X.509"
    elif raw.get("awsIAMType") not in (None, "NONE"):
        auth = "AWS IAM"
    elif raw.get("ldapAuthType") not in (None, "NONE"):
        auth = "LDAP"
    elif raw.get("oidcAuthType") not in (None, "NONE"):
        auth = "OIDC"
    else:
        auth = "Password"
    return {
        "username": raw.get("username") or "",
        "auth_database": raw.get("databaseName"),
        "auth_type": auth,
        "roles": [
            {
                "role_name": r.get("roleName"),
                "database_name": r.get("databaseName"),
                "collection_name": r.get("collectionName"),
            }
            for r in raw.get("roles") or []
        ],
        "scopes": [{"name": s.get("name"), "type": s.get("type")} for s in raw.get("scopes") or []],
        "description": raw.get("description"),
        "delete_after": raw.get("deleteAfterDate"),
    }


def _role_payload(role: Any) -> dict:
    payload = {"roleName": role.role_name, "databaseName": role.database_name}
    if role.collection_name:
        payload["collectionName"] = role.collection_name
    return payload


def _access_entry(raw: dict) -> dict:
    entry = raw.get("cidrBlock") or raw.get("ipAddress") or raw.get("awsSecurityGroup") or ""
    kind = (
        "AWS security group"
        if raw.get("awsSecurityGroup")
        else ("CIDR block" if raw.get("cidrBlock") else "IP address")
    )
    return {
        "entry": entry,
        "type": kind,
        "comment": raw.get("comment"),
        "delete_after": raw.get("deleteAfterDate"),
    }


# ── Singleton ───────────────────────────────────────────────────────────

_service: AtlasService | None = None
_service_key: tuple[str, str, str] | None = None


def get_atlas_service() -> AtlasService:
    """One service (and HTTP client) per worker; rebuilt if the key settings change."""
    global _service, _service_key
    key = (
        settings.MONGODB_ATLAS_BASE_URL,
        settings.MONGODB_ATLAS_PUBLIC_KEY.strip(),
        settings.MONGODB_ATLAS_PRIVATE_KEY.strip(),
    )
    if _service is None or _service_key != key:
        _service = AtlasService()
        _service_key = key
    return _service


def set_atlas_service(service: AtlasService | None) -> None:
    """Tests: install a service with a mock transport (None restores the default)."""
    global _service, _service_key
    _service = service
    _service_key = (
        (
            settings.MONGODB_ATLAS_BASE_URL,
            settings.MONGODB_ATLAS_PUBLIC_KEY.strip(),
            settings.MONGODB_ATLAS_PRIVATE_KEY.strip(),
        )
        if service
        else None
    )
