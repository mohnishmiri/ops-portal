"""
Key Vault Service — Azure Key Vault management across subscriptions.

Lists vaults, secrets, keys, and certificates using Azure REST API
and Key Vault SDK. Supports multi-subscription discovery.
"""

import asyncio
import base64
import hashlib
import json as _json
import urllib.error
import urllib.request
from contextlib import suppress
from datetime import datetime

import structlog

from app.core.azure_auth import get_azure_credential
from app.core.db_cache import cache_manager
from app.core.subscription_scope import get_scoped_subscription_ids

logger = structlog.get_logger(__name__)

ARM_API = "https://management.azure.com"

# Cache TTLs (seconds)
_CACHE_TTL_VAULTS = 600  # 10 min — vault list rarely changes
_CACHE_TTL_DASHBOARD = 300  # 5 min — dashboard aggregation
_CACHE_TTL_LIST = 180  # 3 min — secrets/keys/certs list
_CACHE_TTL_DETAIL = 600  # 10 min — individual cert/key detail


class KeyVaultService:
    """Service for Azure Key Vault operations."""

    async def _get_arm_token(self) -> str:
        """Get ARM bearer token."""
        credential = get_azure_credential()
        token = await asyncio.to_thread(lambda: credential.get_token("https://management.azure.com/.default"))
        return token.token

    async def _get_vault_token(self) -> str:
        """Get Key Vault bearer token."""
        credential = get_azure_credential()
        token = await asyncio.to_thread(lambda: credential.get_token("https://vault.azure.net/.default"))
        return token.token

    async def _arm_get(self, url: str) -> dict:
        """Make ARM REST API GET request."""
        token = await self._get_arm_token()
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

        def _fetch():
            with urllib.request.urlopen(req, timeout=15) as resp:
                return _json.loads(resp.read())

        return await asyncio.to_thread(_fetch)

    async def _vault_get(self, url: str) -> dict:
        """Make Key Vault REST API GET request.

        Bypasses corporate proxy for vault.azure.net calls (vaults are
        reachable directly / via private endpoints, not through proxy).
        Captures response body on HTTP errors so Azure's actual
        error message (network rules, permissions, etc.) is logged.
        """
        token = await self._get_vault_token()
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

        def _fetch():
            # Build an opener that bypasses the proxy for vault calls
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            try:
                with opener.open(req, timeout=15) as resp:
                    return _json.loads(resp.read())
            except urllib.error.HTTPError as he:
                # Read the response body for Azure's detailed error
                body = ""
                with suppress(Exception):
                    body = he.read().decode("utf-8", errors="replace")
                detail = ""
                try:
                    err_json = _json.loads(body)
                    err_obj = err_json.get("error", {})
                    detail = err_obj.get("message", "") or err_obj.get("innererror", {}).get("message", "")
                except Exception:
                    detail = body[:500] if body else ""
                msg = f"HTTP Error {he.code}: {he.reason}"
                if detail:
                    msg += f" — {detail}"
                logger.error("vault_api_error", url=url, status=he.code, detail=detail[:300])
                raise RuntimeError(msg) from he

        return await asyncio.to_thread(_fetch)

    # ── Cache Helpers ──────────────────────────────────────────────────

    async def _get_cache(self, key: str):  # type: ignore[return]
        """Try to fetch from cache. Returns deserialized data or None."""
        raw = await cache_manager.get_cached(key)
        if raw:
            with suppress(Exception):
                return _json.loads(raw)
        return None

    async def _set_cache(self, key: str, data: list | dict, ttl: int) -> None:
        """Store data in cache."""
        with suppress(Exception):
            await cache_manager.set_cached(key, _json.dumps(data, default=str), ttl)

    async def _invalidate_cache(self, *patterns: str) -> None:
        """Invalidate cache keys matching the given glob patterns."""
        for p in patterns:
            await cache_manager.invalidate(p)

    # ── Vault Discovery ────────────────────────────────────────────────

    async def list_vaults(self, *, refresh: bool = False) -> list[dict]:
        """List all Key Vaults across monitored subscriptions. Handles pagination."""
        cache_key = "kv:vaults:all"
        if refresh:
            await self._invalidate_cache(cache_key)
        else:
            cached = await self._get_cache(cache_key)
            if cached is not None:
                return cached

        vaults = []
        for sub_id in await get_scoped_subscription_ids():
            try:
                url: str | None = (
                    f"{ARM_API}/subscriptions/{sub_id}"
                    f"/providers/Microsoft.KeyVault/vaults"
                    f"?api-version=2023-07-01&$top=100"
                )
                while url:
                    body = await self._arm_get(url)
                    page_vaults = body.get("value", [])
                    for v in page_vaults:
                        props = v.get("properties", {})
                        vaults.append(
                            {
                                "name": v.get("name", ""),
                                "id": v.get("id", ""),
                                "location": v.get("location", ""),
                                "subscription_id": sub_id,
                                "resource_group": _extract_rg(v.get("id", "")),
                                "vault_uri": props.get("vaultUri", ""),
                                "sku": props.get("sku", {}).get("name", ""),
                                "tenant_id": props.get("tenantId", ""),
                                "soft_delete_enabled": props.get("enableSoftDelete", False),
                                "purge_protection_enabled": props.get("enablePurgeProtection", False),
                                "rbac_enabled": props.get("enableRbacAuthorization", False),
                                "created_date": props.get("createMode", ""),
                                "provisioning_state": props.get("provisioningState", ""),
                                "tags": v.get("tags", {}),
                            }
                        )
                    url = body.get("nextLink")
            except Exception as e:
                logger.warning("list_vaults_failed", subscription_id=sub_id, error=str(e))

        await self._set_cache(cache_key, vaults, _CACHE_TTL_VAULTS)
        return vaults

    # ── Secrets ────────────────────────────────────────────────────────

    async def list_secrets(self, vault_uri: str, search: str | None = None, *, refresh: bool = False) -> list[dict]:
        """List secrets in a Key Vault (metadata only, never values).

        Handles pagination (Azure KV max 25 per page).
        """
        # Cache the full list; search filter applied after
        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        cache_key = f"kv:secrets:{vault_name}"

        if refresh:
            await self._invalidate_cache(cache_key)
        else:
            cached = await self._get_cache(cache_key)
            if cached is not None:
                if search:
                    return [s for s in cached if search.lower() in s["name"].lower()]
                return cached

        secrets = []
        try:
            url: str | None = f"{vault_uri}secrets?api-version=7.4&maxresults=25"
            while url:
                body = await self._vault_get(url)
                for s in body.get("value", []):
                    attrs = s.get("attributes", {})
                    name = s.get("id", "").rsplit("/", 1)[-1]
                    if search and search.lower() not in name.lower():
                        continue
                    secrets.append(
                        {
                            "name": name,
                            "id": s.get("id", ""),
                            "content_type": s.get("contentType", ""),
                            "enabled": attrs.get("enabled", True),
                            "created": _epoch_to_iso(attrs.get("created")),
                            "updated": _epoch_to_iso(attrs.get("updated")),
                            "expires": _epoch_to_iso(attrs.get("exp")),
                            "not_before": _epoch_to_iso(attrs.get("nbf")),
                            "tags": s.get("tags", {}),
                            "managed": s.get("managed", False),
                        }
                    )
                url = body.get("nextLink")
        except Exception as e:
            logger.warning("list_secrets_failed", vault_uri=vault_uri, error=str(e))
            raise

        await self._set_cache(cache_key, secrets, _CACHE_TTL_LIST)
        if search:
            return [s for s in secrets if search.lower() in s["name"].lower()]
        return secrets

    async def get_secret_value(self, vault_uri: str, name: str) -> dict:
        """Get a secret value (admin only)."""
        url = f"{vault_uri}secrets/{name}?api-version=7.4"
        body = await self._vault_get(url)
        value = body.get("value", "")
        attrs = body.get("attributes", {})

        # Try Base64 decode
        decoded = None
        is_b64 = False
        try:
            decoded = base64.b64decode(value).decode("utf-8")
            is_b64 = True
        except Exception:
            pass

        return {
            "name": name,
            "value": value,
            "content_type": body.get("contentType", ""),
            "is_base64": is_b64,
            "decoded_value": decoded,
            "enabled": attrs.get("enabled", True),
            "created": _epoch_to_iso(attrs.get("created")),
            "updated": _epoch_to_iso(attrs.get("updated")),
            "not_before": _epoch_to_iso(attrs.get("nbf")),
            "expires": _epoch_to_iso(attrs.get("exp")),
        }

    async def create_or_update_secret(
        self,
        vault_uri: str,
        name: str,
        value: str,
        content_type: str | None = None,
        tags: dict | None = None,
        encode_base64: bool = False,
        not_before: str | None = None,
        expires: str | None = None,
    ) -> dict:
        """Create or update a secret.

        If the secret was soft-deleted (409 Conflict), automatically
        recover it first, then update with the new value.

        ``not_before`` / ``expires`` are ISO-8601 date strings.
        When omitted the defaults are *now* and *now + 360 days*.
        """
        if encode_base64:
            value = base64.b64encode(value.encode("utf-8")).decode("utf-8")

        # Default validity: now → now + 360 days
        from datetime import timedelta

        now = datetime.utcnow()
        nbf_dt = datetime.fromisoformat(not_before) if not_before else now
        exp_dt = datetime.fromisoformat(expires) if expires else now + timedelta(days=360)

        url = f"{vault_uri}secrets/{name}?api-version=7.4"
        token = await self._get_vault_token()
        payload = _json.dumps(
            {
                "value": value,
                "contentType": content_type or "",
                "tags": tags or {},
                "attributes": {
                    "enabled": True,
                    "nbf": int(nbf_dt.timestamp()),
                    "exp": int(exp_dt.timestamp()),
                },
            }
        ).encode("utf-8")

        def _put(tok: str) -> dict:
            req = urllib.request.Request(
                url,
                data=payload,
                method="PUT",
                headers={
                    "Authorization": f"Bearer {tok}",
                    "Content-Type": "application/json",
                },
            )
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read())

        try:
            body = await asyncio.to_thread(_put, token)
        except urllib.error.HTTPError as he:
            if he.code == 409:
                # Secret is soft-deleted — recover it, then retry
                logger.info("secret_conflict_recovering", name=name, vault_uri=vault_uri)
                await self._recover_deleted_secret(vault_uri, name)
                # Refresh token and retry the PUT
                token = await self._get_vault_token()
                body = await asyncio.to_thread(_put, token)
            else:
                raise

        attrs = body.get("attributes", {})

        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        await self._invalidate_cache(f"kv:secrets:{vault_name}", "kv:dashboard")

        return {
            "name": name,
            "id": body.get("id", ""),
            "content_type": body.get("contentType", ""),
            "enabled": attrs.get("enabled", True),
            "created": _epoch_to_iso(attrs.get("created")),
            "updated": _epoch_to_iso(attrs.get("updated")),
        }

    async def _recover_deleted_secret(self, vault_uri: str, name: str) -> None:
        """Recover a soft-deleted secret and wait until it is available."""
        recover_url = f"{vault_uri}deletedsecrets/{name}/recover?api-version=7.4"
        token = await self._get_vault_token()
        req = urllib.request.Request(
            recover_url,
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )

        def _post():
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read())

        await asyncio.to_thread(_post)
        logger.info("secret_recovery_started", name=name)

        # Poll until the secret is recoverable (up to ~10 seconds)
        for _ in range(10):
            await asyncio.sleep(1)
            try:
                check_url = f"{vault_uri}secrets/{name}?api-version=7.4"
                await self._vault_get(check_url)
                logger.info("secret_recovered", name=name)
                return
            except Exception:
                continue

        logger.warning("secret_recovery_slow", name=name, msg="Recovery may still be in progress")

    async def delete_secret(self, vault_uri: str, name: str) -> dict:
        """Soft-delete a secret."""
        url = f"{vault_uri}secrets/{name}?api-version=7.4"
        token = await self._get_vault_token()
        req = urllib.request.Request(
            url,
            method="DELETE",
            headers={"Authorization": f"Bearer {token}"},
        )

        def _delete():
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read())

        body = await asyncio.to_thread(_delete)

        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        await self._invalidate_cache(f"kv:secrets:{vault_name}", "kv:dashboard")

        return {
            "name": name,
            "deleted": True,
            "recovery_id": body.get("recoveryId", ""),
        }

    # ── Keys ───────────────────────────────────────────────────────────

    async def list_keys(self, vault_uri: str, *, refresh: bool = False) -> list[dict]:
        """List keys in a Key Vault. Handles pagination."""
        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        cache_key = f"kv:keys:{vault_name}"

        if refresh:
            await self._invalidate_cache(cache_key)
        else:
            cached = await self._get_cache(cache_key)
            if cached is not None:
                return cached

        keys = []
        try:
            url: str | None = f"{vault_uri}keys?api-version=7.4&maxresults=25"
            while url:
                body = await self._vault_get(url)
                for k in body.get("value", []):
                    attrs = k.get("attributes", {})
                    name = k.get("kid", "").rsplit("/", 1)[-1]
                    keys.append(
                        {
                            "name": name,
                            "kid": k.get("kid", ""),
                            "enabled": attrs.get("enabled", True),
                            "created": _epoch_to_iso(attrs.get("created")),
                            "updated": _epoch_to_iso(attrs.get("updated")),
                            "expires": _epoch_to_iso(attrs.get("exp")),
                            "not_before": _epoch_to_iso(attrs.get("nbf")),
                            "managed": k.get("managed", False),
                            "tags": k.get("tags", {}),
                        }
                    )
                url = body.get("nextLink")
        except Exception as e:
            logger.warning("list_keys_failed", vault_uri=vault_uri, error=str(e))
            raise

        await self._set_cache(cache_key, keys, _CACHE_TTL_LIST)
        return keys

    async def get_key(self, vault_uri: str, name: str) -> dict:
        """Get key details (metadata + public key info, never private key)."""
        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        detail_cache_key = f"kv:key-detail:{vault_name}:{name}"
        cached = await self._get_cache(detail_cache_key)
        if cached is not None:
            return cached

        url = f"{vault_uri}keys/{name}?api-version=7.4"
        body = await self._vault_get(url)
        key_data = body.get("key", {})
        attrs = body.get("attributes", {})

        result = {
            "name": name,
            "kid": key_data.get("kid", ""),
            "kty": key_data.get("kty", ""),
            "key_ops": key_data.get("key_ops", []),
            "key_size": key_data.get("key_size"),
            "crv": key_data.get("crv"),
            "enabled": attrs.get("enabled", True),
            "created": _epoch_to_iso(attrs.get("created")),
            "updated": _epoch_to_iso(attrs.get("updated")),
            "expires": _epoch_to_iso(attrs.get("exp")),
            "not_before": _epoch_to_iso(attrs.get("nbf")),
            "recovery_level": attrs.get("recoveryLevel", ""),
            "tags": body.get("tags", {}),
        }
        await self._set_cache(detail_cache_key, result, _CACHE_TTL_DETAIL)
        return result

    async def create_or_update_key(
        self,
        vault_uri: str,
        name: str,
        kty: str = "RSA",
        key_size: int | None = None,
        key_ops: list[str] | None = None,
        not_before: str | None = None,
        expires: str | None = None,
    ) -> dict:
        """Create or update a key.

        ``kty``: RSA, EC, oct, RSA-HSM, EC-HSM, oct-HSM.
        ``not_before`` / ``expires`` are ISO-8601 date strings.
        When omitted the defaults are *now* and *now + 360 days*.
        """
        from datetime import timedelta

        now = datetime.utcnow()
        nbf_dt = datetime.fromisoformat(not_before) if not_before else now
        exp_dt = datetime.fromisoformat(expires) if expires else now + timedelta(days=360)

        url = f"{vault_uri}keys/{name}/create?api-version=7.4"
        token = await self._get_vault_token()
        body_payload: dict = {
            "kty": kty,
            "attributes": {
                "enabled": True,
                "nbf": int(nbf_dt.timestamp()),
                "exp": int(exp_dt.timestamp()),
            },
        }
        if key_size:
            body_payload["key_size"] = key_size
        if key_ops:
            body_payload["key_ops"] = key_ops

        payload = _json.dumps(body_payload).encode("utf-8")

        def _post(tok: str) -> dict:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {tok}",
                    "Content-Type": "application/json",
                },
            )
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read())

        try:
            body = await asyncio.to_thread(_post, token)
        except urllib.error.HTTPError as he:
            if he.code == 409:
                logger.info("key_conflict_recovering", name=name, vault_uri=vault_uri)
                await self._recover_deleted_item(vault_uri, "keys", name)
                token = await self._get_vault_token()
                body = await asyncio.to_thread(_post, token)
            else:
                raise

        key_data = body.get("key", {})
        attrs = body.get("attributes", {})

        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        await self._invalidate_cache(f"kv:keys:{vault_name}", f"kv:key-detail:{vault_name}:*", "kv:dashboard")

        return {
            "name": name,
            "kid": key_data.get("kid", ""),
            "kty": key_data.get("kty", ""),
            "key_ops": key_data.get("key_ops", []),
            "enabled": attrs.get("enabled", True),
            "created": _epoch_to_iso(attrs.get("created")),
            "updated": _epoch_to_iso(attrs.get("updated")),
        }

    async def delete_key(self, vault_uri: str, name: str) -> dict:
        """Soft-delete a key."""
        url = f"{vault_uri}keys/{name}?api-version=7.4"
        token = await self._get_vault_token()
        req = urllib.request.Request(
            url,
            method="DELETE",
            headers={"Authorization": f"Bearer {token}"},
        )

        def _delete():
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read())

        body = await asyncio.to_thread(_delete)

        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        await self._invalidate_cache(f"kv:keys:{vault_name}", f"kv:key-detail:{vault_name}:*", "kv:dashboard")

        return {
            "name": name,
            "deleted": True,
            "recovery_id": body.get("recoveryId", ""),
        }

    async def _recover_deleted_item(self, vault_uri: str, item_type: str, name: str) -> None:
        """Recover a soft-deleted key/secret/certificate and wait."""
        recover_url = f"{vault_uri}deleted{item_type}/{name}/recover?api-version=7.4"
        token = await self._get_vault_token()
        req = urllib.request.Request(
            recover_url,
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )

        def _post():
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=15) as resp:
                return _json.loads(resp.read())

        await asyncio.to_thread(_post)
        logger.info("item_recovery_started", item_type=item_type, name=name)

        for _ in range(10):
            await asyncio.sleep(1)
            try:
                check_url = f"{vault_uri}{item_type}/{name}?api-version=7.4"
                await self._vault_get(check_url)
                logger.info("item_recovered", item_type=item_type, name=name)
                return
            except Exception:
                continue

        logger.warning("item_recovery_slow", item_type=item_type, name=name)

    # ── Certificates ───────────────────────────────────────────────────

    @staticmethod
    def validate_certificate_content(
        cert_bytes: bytes,
        file_type: str,
        password: str | None = None,
    ) -> dict:
        """Validate certificate bytes before Azure import. Does not log content."""
        from cryptography import x509 as crypto_x509
        from cryptography.hazmat.primitives.serialization import pkcs12

        ext = file_type.lower().lstrip(".")
        if ext not in {"pfx", "pem", "cer", "crt"}:
            raise ValueError("Unsupported certificate format. Use .pfx, .pem, .cer, or .crt")

        if ext == "pfx":
            if not password:
                raise ValueError("Password is required for PFX certificates")
            try:
                _, cert, _ = pkcs12.load_key_and_certificates(cert_bytes, password.encode("utf-8"))
            except Exception as exc:
                raise ValueError("Invalid PFX certificate or incorrect password") from exc
            if cert is None:
                raise ValueError("PFX file does not contain a certificate")
            subject = cert.subject.rfc4514_string()
            not_after = cert.not_valid_after_utc.isoformat() if cert.not_valid_after_utc else None
            return {"format": "pfx", "subject": subject, "expires": not_after}

        if ext == "pem":
            try:
                if b"-----BEGIN" in cert_bytes:
                    cert = crypto_x509.load_pem_x509_certificate(cert_bytes)
                else:
                    cert = crypto_x509.load_der_x509_certificate(cert_bytes)
            except Exception as exc:
                raise ValueError("Invalid PEM certificate") from exc
            subject = cert.subject.rfc4514_string()
            not_after = cert.not_valid_after_utc.isoformat() if cert.not_valid_after_utc else None
            return {"format": "pem", "subject": subject, "expires": not_after}

        # .cer / .crt — DER or PEM encoded X.509
        try:
            if b"-----BEGIN" in cert_bytes:
                cert = crypto_x509.load_pem_x509_certificate(cert_bytes)
            else:
                cert = crypto_x509.load_der_x509_certificate(cert_bytes)
        except Exception as exc:
            raise ValueError(f"Invalid {ext.upper()} certificate") from exc
        subject = cert.subject.rfc4514_string()
        not_after = cert.not_valid_after_utc.isoformat() if cert.not_valid_after_utc else None
        return {"format": ext, "subject": subject, "expires": not_after}

    async def import_certificate(
        self,
        vault_uri: str,
        name: str,
        cert_bytes: bytes,
        *,
        password: str | None = None,
        tags: dict | None = None,
        not_before: str | None = None,
        expires: str | None = None,
    ) -> dict:
        """Import a certificate into Key Vault via REST import API."""
        from datetime import timedelta

        now = datetime.utcnow()
        nbf_dt = datetime.fromisoformat(not_before) if not_before else now
        exp_dt = datetime.fromisoformat(expires) if expires else now + timedelta(days=360)

        url = f"{vault_uri}certificates/{name}/import?api-version=7.4"
        token = await self._get_vault_token()
        payload_dict: dict = {
            "value": base64.b64encode(cert_bytes).decode("ascii"),
            "tags": tags or {},
            "attributes": {
                "enabled": True,
                "nbf": int(nbf_dt.timestamp()),
                "exp": int(exp_dt.timestamp()),
            },
        }
        if password:
            payload_dict["pwd"] = password

        payload = _json.dumps(payload_dict).encode("utf-8")

        def _post(tok: str) -> dict:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {tok}",
                    "Content-Type": "application/json",
                },
            )
            no_proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(no_proxy_handler)
            with opener.open(req, timeout=30) as resp:
                return _json.loads(resp.read())

        try:
            body = await asyncio.to_thread(_post, token)
        except urllib.error.HTTPError as he:
            if he.code == 409:
                logger.info("certificate_conflict_recovering", name=name, vault_uri=vault_uri)
                await self._recover_deleted_item(vault_uri, "certificates", name)
                token = await self._get_vault_token()
                body = await asyncio.to_thread(_post, token)
            else:
                raise

        attrs = body.get("attributes", {})
        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        await self._invalidate_cache(
            f"kv:certs:{vault_name}",
            f"kv:cert-detail:{vault_name}:{name}",
            "kv:dashboard",
        )

        return {
            "name": name,
            "id": body.get("id", ""),
            "enabled": attrs.get("enabled", True),
            "created": _epoch_to_iso(attrs.get("created")),
            "updated": _epoch_to_iso(attrs.get("updated")),
            "expires": _epoch_to_iso(attrs.get("exp")),
            "not_before": _epoch_to_iso(attrs.get("nbf")),
        }

    async def list_certificates(self, vault_uri: str, *, refresh: bool = False) -> list[dict]:
        """List certificates in a Key Vault with thumbprint and derived CN. Handles pagination."""
        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        cache_key = f"kv:certs:{vault_name}"

        if refresh:
            await self._invalidate_cache(cache_key)
        else:
            cached = await self._get_cache(cache_key)
            if cached is not None:
                return cached

        certs: list[dict] = []
        try:
            url: str | None = f"{vault_uri}certificates?api-version=7.4&maxresults=25"
            while url:
                body = await self._vault_get(url)
                for c in body.get("value", []):
                    attrs = c.get("attributes", {})
                    name = c.get("id", "").rsplit("/", 1)[-1]

                    # x5t is base64url-encoded SHA-1 thumbprint from list API
                    x5t = c.get("x5t", "")
                    thumbprint = ""
                    if x5t:
                        try:
                            # base64url → bytes → hex uppercase
                            padded = x5t + "=" * (-len(x5t) % 4)
                            raw = base64.urlsafe_b64decode(padded)
                            thumbprint = raw.hex().upper()
                        except Exception:
                            pass

                    # Derive CN from cert name convention (dashes → dots)
                    cn_name = name.replace("-", ".") if name else ""

                    certs.append(
                        {
                            "name": name,
                            "id": c.get("id", ""),
                            "enabled": attrs.get("enabled", True),
                            "created": _epoch_to_iso(attrs.get("created")),
                            "updated": _epoch_to_iso(attrs.get("updated")),
                            "expires": _epoch_to_iso(attrs.get("exp")),
                            "not_before": _epoch_to_iso(attrs.get("nbf")),
                            "tags": c.get("tags", {}),
                            "thumbprint": thumbprint,
                            "cn_name": cn_name,
                            "san": [],
                            "serial_number": None,
                        }
                    )
                url = body.get("nextLink")
        except Exception as e:
            logger.warning("list_certificates_failed", vault_uri=vault_uri, error=str(e))
            raise

        # Try to enrich with real CN/SAN/Serial from detail calls (best-effort, non-blocking)
        try:
            await asyncio.wait_for(self._enrich_certificates(vault_uri, certs), timeout=20)
        except TimeoutError:
            logger.warning("cert_enrichment_timeout", vault_uri=vault_uri, count=len(certs))
        except Exception as e:
            logger.warning("cert_enrichment_failed", vault_uri=vault_uri, error=str(e)[:200])

        await self._set_cache(cache_key, certs, _CACHE_TTL_LIST)
        return certs

    async def _enrich_certificates(self, vault_uri: str, certs: list[dict]) -> None:
        """Fetch individual cert details in parallel to add real CN, SAN, serial."""
        sem = asyncio.Semaphore(5)  # Limit concurrent detail requests

        async def _fetch_detail(cert: dict) -> None:
            async with sem:
                try:
                    detail = await asyncio.wait_for(
                        self.get_certificate(vault_uri, cert["name"]),
                        timeout=8,
                    )
                    cert["cn_name"] = detail.get("cn_name", "") or cert["cn_name"]
                    cert["san"] = detail.get("san", []) or cert["san"]
                    cert["serial_number"] = detail.get("serial_number") or cert["serial_number"]
                    cert["thumbprint"] = detail.get("thumbprint", "") or cert["thumbprint"]
                except Exception as exc:
                    logger.debug("cert_enrich_skip", name=cert["name"], error=str(exc)[:100])

        await asyncio.gather(*[_fetch_detail(c) for c in certs])

    async def get_certificate(self, vault_uri: str, name: str) -> dict:
        """Get certificate details, policy, thumbprint, CN, and SAN."""
        vault_name = vault_uri.rstrip("/").split("//")[1].split(".")[0]
        detail_cache_key = f"kv:cert-detail:{vault_name}:{name}"
        cached = await self._get_cache(detail_cache_key)
        if cached is not None:
            return cached

        url = f"{vault_uri}certificates/{name}?api-version=7.4"
        body = await self._vault_get(url)
        attrs = body.get("attributes", {})
        policy = body.get("policy", {})
        x509_props = policy.get("x509_props", {})
        issuer = policy.get("issuer", {})
        lifetime_actions = policy.get("lifetime_actions", [])
        key_props = policy.get("key_props", {})

        # Compute thumbprint from DER-encoded cert (cer) field
        cer_b64 = body.get("cer", "")
        thumbprint = ""
        cn_name = ""
        san_list: list[str] = []

        if cer_b64:
            try:
                cer_bytes = base64.b64decode(cer_b64)
                # SHA-1 thumbprint (standard for certificate identification)
                thumbprint = hashlib.sha1(cer_bytes).hexdigest().upper()
                # SHA-256 thumbprint (more secure)
                thumbprint_sha256 = hashlib.sha256(cer_bytes).hexdigest().upper()
            except Exception:
                thumbprint_sha256 = ""

            # Parse CN and SAN from x.509 using cryptography lib if available
            try:
                from cryptography import x509 as crypto_x509
                from cryptography.x509.oid import ExtensionOID, NameOID

                cert_obj = crypto_x509.load_der_x509_certificate(cer_bytes)
                # Extract CN
                cn_attrs = cert_obj.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
                cn_name = cn_attrs[0].value if cn_attrs else ""
                # Extract SAN
                try:
                    san_ext = cert_obj.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                    from cryptography.x509 import DNSName, IPAddress

                    san_list = [n.value for n in san_ext.value if isinstance(n, (DNSName, IPAddress))]
                    # Convert IP addresses to string
                    san_list = [str(s) for s in san_list]
                except crypto_x509.ExtensionNotFound:
                    pass
                # Also extract issuer CN
                issuer_cn_attrs = cert_obj.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
                issuer_cn = issuer_cn_attrs[0].value if issuer_cn_attrs else ""
                serial_number = format(cert_obj.serial_number, "X")
            except ImportError:
                # cryptography not installed — fall back to subject from policy
                cn_name = _extract_cn_from_subject(x509_props.get("subject", ""))
                issuer_cn = ""
                serial_number = ""
                thumbprint_sha256 = ""
            except Exception as e:
                logger.debug("cert_parse_fallback", name=name, error=str(e))
                cn_name = _extract_cn_from_subject(x509_props.get("subject", ""))
                issuer_cn = ""
                serial_number = ""
                thumbprint_sha256 = ""
        else:
            thumbprint_sha256 = ""
            issuer_cn = ""
            serial_number = ""

        # SAN from policy if not parsed from cert
        if not san_list:
            sans_obj = x509_props.get("sans", {})
            san_list = (
                sans_obj.get("dns_names", [])
                + [str(ip) for ip in sans_obj.get("ip_addresses", [])]
                + sans_obj.get("emails", [])
            )

        if not cn_name:
            cn_name = _extract_cn_from_subject(x509_props.get("subject", ""))

        result = {
            "name": name,
            "id": body.get("id", ""),
            "thumbprint": thumbprint,
            "thumbprint_sha256": thumbprint_sha256 if thumbprint_sha256 else None,
            "cn_name": cn_name,
            "san": san_list,
            "serial_number": serial_number if serial_number else None,
            "issuer_cn": issuer_cn if issuer_cn else issuer.get("name", ""),
            "subject": x509_props.get("subject", ""),
            "enabled": attrs.get("enabled", True),
            "created": _epoch_to_iso(attrs.get("created")),
            "updated": _epoch_to_iso(attrs.get("updated")),
            "expires": _epoch_to_iso(attrs.get("exp")),
            "not_before": _epoch_to_iso(attrs.get("nbf")),
            "validity_months": x509_props.get("validity_months"),
            "key_type": key_props.get("kty", ""),
            "key_size": key_props.get("key_size"),
            "key_usage": x509_props.get("key_usage", []),
            "issuer_name": issuer.get("name", ""),
            "auto_renew": any(a.get("action", {}).get("action_type") == "AutoRenew" for a in lifetime_actions),
            "tags": body.get("tags", {}),
        }
        await self._set_cache(detail_cache_key, result, _CACHE_TTL_DETAIL)
        return result

    # ── Dashboard Summary ──────────────────────────────────────────────

    async def get_dashboard_summary(self, *, refresh: bool = False) -> dict:
        """Get Key Vault dashboard summary across all vaults."""
        if refresh:
            await self._invalidate_cache("kv:dashboard", "kv:vaults:*", "kv:secrets:*", "kv:keys:*", "kv:certs:*")
        else:
            cached = await self._get_cache("kv:dashboard")
            if cached is not None:
                return cached

        vaults = await self.list_vaults()
        total_secrets = 0
        total_keys = 0
        total_certs = 0
        expiring_soon = []
        vault_summaries = []

        # Process all vaults with concurrency limit to avoid rate limiting
        sem = asyncio.Semaphore(5)

        async def _summarise_vault(vault: dict) -> dict:
            vault_uri = vault["vault_uri"]
            s_count = k_count = c_count = 0
            v_expiring: list[dict] = []
            if vault_uri:
                try:
                    async with sem:
                        secrets, keys, certs = await asyncio.gather(
                            self.list_secrets(vault_uri),
                            self.list_keys(vault_uri),
                            self.list_certificates(vault_uri),
                            return_exceptions=True,
                        )

                    if isinstance(secrets, list):
                        s_count = len(secrets)
                        for s in secrets:
                            if s.get("expires"):
                                _check_expiry(v_expiring, s, vault["name"], "secret")

                    if isinstance(keys, list):
                        k_count = len(keys)
                        for k in keys:
                            if k.get("expires"):
                                _check_expiry(v_expiring, k, vault["name"], "key")

                    if isinstance(certs, list):
                        c_count = len(certs)
                        for c in certs:
                            if c.get("expires"):
                                _check_expiry(v_expiring, c, vault["name"], "certificate")

                except Exception as e:
                    logger.warning("vault_summary_failed", vault=vault["name"], error=str(e))

            return {
                "name": vault["name"],
                "vault_uri": vault.get("vault_uri", ""),
                "location": vault["location"],
                "subscription_id": vault["subscription_id"],
                "secrets_count": s_count,
                "keys_count": k_count,
                "certificates_count": c_count,
                "soft_delete": vault["soft_delete_enabled"],
                "purge_protection": vault["purge_protection_enabled"],
                "rbac_enabled": vault["rbac_enabled"],
                "_expiring": v_expiring,
            }

        summaries = await asyncio.gather(
            *[_summarise_vault(v) for v in vaults],
            return_exceptions=True,
        )

        for s in summaries:
            if isinstance(s, Exception):
                logger.warning("vault_summary_task_failed", error=str(s))
                continue
            total_secrets += s["secrets_count"]
            total_keys += s["keys_count"]
            total_certs += s["certificates_count"]
            expiring_soon.extend(s.pop("_expiring", []))
            vault_summaries.append(s)

        # Sort expiring items by date
        expiring_soon.sort(key=lambda x: x.get("expires", ""))

        result = {
            "total_vaults": len(vaults),
            "total_secrets": total_secrets,
            "total_keys": total_keys,
            "total_certificates": total_certs,
            "expiring_within_30_days": len([e for e in expiring_soon if e.get("days_remaining", 999) <= 30]),
            "expiring_within_90_days": len([e for e in expiring_soon if e.get("days_remaining", 999) <= 90]),
            "expiring_within_360_days": len([e for e in expiring_soon if e.get("days_remaining", 999) <= 360]),
            "expiring_items": expiring_soon,
            "vault_summaries": vault_summaries,
            "generated_at": datetime.utcnow().isoformat(),
        }
        await self._set_cache("kv:dashboard", result, _CACHE_TTL_DASHBOARD)
        return result


# ── Helpers ────────────────────────────────────────────────────────────


def _extract_rg(resource_id: str) -> str:
    """Extract resource group name from ARM resource ID."""
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _extract_cn_from_subject(subject: str) -> str:
    """Extract CN= value from an X.509 subject string like 'CN=example.com, O=Org'."""
    if not subject:
        return ""
    for part in subject.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:]
    return subject


def _epoch_to_iso(epoch: int | None) -> str | None:
    """Convert Unix epoch to ISO 8601 string."""
    if epoch is None:
        return None
    try:
        return datetime.utcfromtimestamp(epoch).isoformat()
    except (ValueError, OSError):
        return None


def _check_expiry(expiring_list: list, item: dict, vault_name: str, item_type: str) -> None:
    """Check if an item is expiring within 360 days and add to list."""
    expires = item.get("expires")
    if not expires:
        return
    try:
        exp_date = datetime.fromisoformat(expires)
        days_remaining = (exp_date - datetime.utcnow()).days
        if 0 <= days_remaining <= 360:
            expiring_list.append(
                {
                    "name": item["name"],
                    "vault_name": vault_name,
                    "type": item_type,
                    "expires": expires,
                    "days_remaining": days_remaining,
                    "enabled": item.get("enabled", True),
                }
            )
    except (ValueError, TypeError):
        pass
