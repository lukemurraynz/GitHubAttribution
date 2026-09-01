from __future__ import annotations
import json, os, urllib.parse, urllib.request, urllib.error
from dataclasses import dataclass

@dataclass(frozen=True)
class GitHubClient:
    token: str
    api_url: str = 'https://api.github.com'
    api_version: str = '2026-03-10'

    def get_json(self, path: str, params: dict | None = None) -> dict | list:
        q = urllib.parse.urlencode({k:v for k,v in (params or {}).items() if v is not None})
        url = self.api_url.rstrip('/') + path + (('?' + q) if q else '')
        req = urllib.request.Request(url, headers={
            'Accept':'application/vnd.github+json', 'Authorization':f'Bearer {self.token}',
            'X-GitHub-Api-Version':self.api_version, 'User-Agent':'copilot-cost-attribution/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body=e.read().decode('utf-8','replace')
            raise RuntimeError(f'GitHub API {e.code}: {body}') from e

    def ai_credit_usage(self, org: str, year: int, month: int, day: int | None = None) -> dict:
        return self.get_json(f'/organizations/{urllib.parse.quote(org)}/settings/billing/ai_credit/usage', {'year':year,'month':month,'day':day})

    def usage_summary(self, org: str, year: int, month: int, day: int | None = None, repository: str | None = None, product: str | None = None) -> dict:
        return self.get_json(f'/organizations/{urllib.parse.quote(org)}/settings/billing/usage/summary', {'year':year,'month':month,'day':day,'repository':repository,'product':product})
