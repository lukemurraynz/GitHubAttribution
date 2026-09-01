from __future__ import annotations

"""GitHub-token source for the collector's reconcile path.

The collector's reconcile to GitHub needs a token, but we deliberately keep
secrets out of the hook and out of plaintext env vars. This module resolves a
GitHub token from one of, in order:

  1. the `GITHUB_TOKEN` environment variable (for local dev / simple setups), or
  2. an Azure Key Vault secret via the environment-variable-based token path or
     the Azure Instance Metadata Service (IMDS) managed identity (for the
     deployed collector in Azure), using stdlib `urllib` only.

When running in Azure with a managed identity, set:
    COPILOT_COST_KEYVAULT_URL=https://<vault>.vault.azure.net
    COPILOT_COST_KEYVAULT_SECRET=<secret-name-that-holds-the-github-token>
The managed identity must have "Key Vault Secrets User" on that vault.
No token is ever stored by the hook and none is emitted to logs here.
"""

import json
import os
from urllib.parse import quote as urlquote
from urllib.request import Request, urlopen

_MDS_ENDPOINT = 'http://169.254.169.254/metadata/identity/oauth2/token'
_MDS_API_VERSION = '2018-02-01'
_SECRET_API_VERSION = '7.4'


class KeyVaultError(RuntimeError):
    """Raised when a Key Vault secret cannot be retrieved."""


def _manager_identity_token(resource: str) -> str:
    """Get an access token for `resource` from the Azure Instance Metadata Service.

    Uses the managed identity assigned to the running environment (Azure App
    Service, Container Apps, Functions, or VM). Returns a bearer token string.
    """
    url = (
        f'{_MDS_ENDPOINT}?api-version={_MDS_API_VERSION}'
        f'&resource={urlquote(resource)}'
    )
    req = Request(url, headers={'Metadata': 'true'})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.load(resp)
    except Exception as exc:  # network unreachable, not on Azure, etc.
        raise KeyVaultError(f'Managed identity token request failed: {exc}') from exc
    return data.get('access_token', '')


def _get_keyvault_secret(vault_url: str, secret_name: str) -> str:
    """Fetch a secret value from Azure Key Vault using a managed identity token."""
    resource = 'https://vault.azure.net'
    token = _manager_identity_token(resource)
    if not token:
        raise KeyVaultError('No managed identity access token was returned. Is a managed identity configured on the collector?')
    url = f'{vault_url.rstrip("/")}/secrets/{urlquote(secret_name)}?api-version={_SECRET_API_VERSION}'
    req = Request(
        url,
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
    )
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as exc:
        raise KeyVaultError(f'Key Vault secret request failed: {exc}') from exc
    value = data.get('value')
    if not value:
        raise KeyVaultError(f'Key Vault secret "{secret_name}" returned no value.')
    return value


def resolve_github_token() -> str:
    """Return the GitHub token from env, or from Key Vault via managed identity.

    Raises SystemExit with a clear message if no token source is configured.
    """
    env_token = os.getenv('GITHUB_TOKEN')
    if env_token:
        return env_token

    vault_url = os.getenv('COPILOT_COST_KEYVAULT_URL')
    secret_name = os.getenv('COPILOT_COST_KEYVAULT_SECRET')
    if vault_url and secret_name:
        try:
            return _get_keyvault_secret(vault_url, secret_name).strip()
        except KeyVaultError as exc:
            raise SystemExit(f'Could not read GitHub token from Key Vault: {exc}') from exc

    raise SystemExit(
        'GITHUB_TOKEN is not set and no Key Vault source is configured. '
        'Set GITHUB_TOKEN locally, or set COPILOT_COST_KEYVAULT_URL and '
        'COPILOT_COST_KEYVAULT_SECRET (with a managed identity granted '
        '"Key Vault Secrets User") for the deployed collector.'
    )
