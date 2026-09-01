from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class GitHubError(RuntimeError):
    """Raised when the GitHub API call fails. Carries the HTTP status code."""

    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status


def validate_ai_credit_usage_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise GitHubError(None, 'GitHub AI-credit usage response was not a JSON object')
    usage_items = payload.get('usageItems')
    if not isinstance(usage_items, list):
        raise GitHubError(None, "GitHub AI-credit usage response missing or malformed 'usageItems' list")
    time_period = payload.get('timePeriod')
    if time_period is not None and not isinstance(time_period, dict):
        raise GitHubError(None, "GitHub AI-credit usage response malformed 'timePeriod' object")
    return payload


@dataclass(frozen=True)
class GitHubClient:
    token: str
    api_url: str = 'https://api.github.com'
    api_version: str = '2026-03-10'

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = self.api_url.rstrip('/') + path + (('?' + query) if query else '')
        req = urllib.request.Request(
            url,
            headers={
                'Accept': 'application/vnd.github+json',
                'Authorization': f'Bearer {self.token}',
                'X-GitHub-Api-Version': self.api_version,
                'User-Agent': 'github-copilot-cost-attribution/2.0',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.load(response)
                if not isinstance(payload, dict):
                    raise GitHubError(None, 'GitHub returned a non-object JSON response')
                return payload
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise GitHubError(
                    exc.code,
                    "GitHub API request failed with HTTP 403: insufficient permission - org billing endpoints require Organization 'Administration read' (org owner/admin); Billing Manager role is not sufficient for the API",
                ) from exc
            if exc.code == 404:
                raise GitHubError(
                    exc.code,
                    'GitHub API request failed with HTTP 404: org not found or endpoint not available for this account',
                ) from exc
            # Surface a stable, non-leaky message; keep the status for callers
            # that need to distinguish retryable (429/5xx) from fatal errors.
            raise GitHubError(exc.code, f'GitHub API request failed with HTTP {exc.code}') from exc
        except urllib.error.URLError as exc:
            raise GitHubError(None, f'GitHub API connection failed: {exc.reason}') from exc

    def ai_credit_usage(self, org: str, year: int, month: int, day: int, user: str | None = None) -> dict[str, Any]:
        return validate_ai_credit_usage_envelope(
            self.get_json(
                f'/organizations/{urllib.parse.quote(org)}/settings/billing/ai_credit/usage',
                {'year': year, 'month': month, 'day': day, 'user': user},
            )
        )

    def usage_summary(self, org: str, year: int, month: int, day: int, repository: str | None = None, product: str | None = None) -> dict[str, Any]:
        return self.get_json(
            f'/organizations/{urllib.parse.quote(org)}/settings/billing/usage/summary',
            {'year': year, 'month': month, 'day': day, 'repository': repository, 'product': product},
        )
