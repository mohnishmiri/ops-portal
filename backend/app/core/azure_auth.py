"""Azure credential management using Managed Identity / DefaultAzureCredential."""

from functools import lru_cache

from azure.identity import (
    ClientSecretCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)

from app.core.config import settings


@lru_cache(maxsize=1)
def get_azure_credential() -> DefaultAzureCredential | ClientSecretCredential:
    """
    Get Azure credential.

    In production (AKS with Workload Identity): uses ManagedIdentityCredential
    via DefaultAzureCredential chain.

    In development: falls back to ClientSecretCredential if AZURE_CLIENT_SECRET is set,
    otherwise uses Azure CLI / VS Code credential via DefaultAzureCredential.
    """
    if settings.AZURE_CLIENT_SECRET:
        return ClientSecretCredential(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
    return DefaultAzureCredential(
        managed_identity_client_id=(settings.AZURE_CLIENT_ID if settings.ENVIRONMENT == "production" else None),
    )


@lru_cache(maxsize=1)
def get_managed_identity_credential() -> ManagedIdentityCredential:
    """Get Managed Identity credential (AKS Workload Identity)."""
    return ManagedIdentityCredential(client_id=settings.AZURE_CLIENT_ID)
