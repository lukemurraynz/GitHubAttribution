from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


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
                    raise RuntimeError('GitHub returned a non-object JSON response')
                return payload
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', 'replace')
            raise RuntimeError(f'GitHub API {exc.code}: {body}') from exc

    def ai_credit_usage(self, org: str, year: int, month: int, day: int, user: str | None = None) -> dict[str, Any]:
        return self.get_json(
            f'/organizations/{urllib.parse.quote(org)}/settings/billing/ai_credit/usage',
            {'year': year, 'month': month, 'day': day, 'user': user},
        )

    def usage_summary(self, org: str, year: int, month: int, day: int, repository: str | None = None, product: str | None = None) -> dict[str, Any]:
        return self.get_json(
            f'/organizations/{urllib.parse.quote(org)}/settings/billing/usage/summary',
            {'year': year, 'month': month, 'day': day, 'repository': repository, 'product': product},
        )
