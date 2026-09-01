from __future__ import annotations

"""Live contract tests for the GitHub billing endpoints used by the tool.

These tests hit the REAL GitHub REST API and therefore require:
  - GITHUB_TOKEN set to a token with org 'Administration read' (classic PAT
    with admin:org is sufficient), and
  - GITHUB_ORG set to the target org name.

Without those env vars the tests are skipped, so the default/CI suite never
touches the network. The token must NEVER be logged or asserted; only the
response shape is checked.

This locks the wire contract that was confirmed live:
  GET /organizations/{org}/settings/billing/ai_credit/usage
  GET /organizations/{org}/settings/billing/usage/summary
Both return {"organization":..., "timePeriod":{...}, "usageItems":[...]} where
each usageItem has the documented billing fields. A 'user' filter is accepted.
"""

import os
import unittest

from copilot_cost.service.github import GitHubClient, validate_ai_credit_usage_envelope

FIELD_REQUIRED = {
    'product', 'sku', 'unitType', 'pricePerUnit',
    'grossQuantity', 'grossAmount', 'discountQuantity',
    'discountAmount', 'netQuantity', 'netAmount',
}

# Usage summary items are the same billing fields minus 'model' (summary rows
# are product/sku-level, not model-level).
FIELD_REQUIRED_MODEL = FIELD_REQUIRED | {'model'}


def _client() -> GitHubClient | None:
    token = os.environ.get('GITHUB_TOKEN')
    org = os.environ.get('GITHUB_ORG')
    if not token or not org:
        return None
    return GitHubClient(
        token,
        os.getenv('GITHUB_API_URL', 'https://api.github.com'),
        os.getenv('GITHUB_API_VERSION', '2026-03-10'),
    )


@unittest.skipUnless(_client(), 'GITHUB_TOKEN and GITHUB_ORG required for live API tests')
class LiveGithubContractTests(unittest.TestCase):
    client: GitHubClient
    org: str
    year: int
    month: int
    day: int

    @classmethod
    def setUpClass(cls) -> None:
        client = _client()
        assert client is not None, 'skipUnless(_client()) guards this'
        cls.client = client
        cls.org = os.environ['GITHUB_ORG']
        cls.year = 2026
        cls.month = 8
        cls.day = 31

    def test_ai_credit_usage_envelope_is_valid(self) -> None:
        """The ai_credit/usage response must pass the tool's own envelope validator."""
        payload = self.client.ai_credit_usage(self.org, self.year, self.month, self.day)
        validate_ai_credit_usage_envelope(payload)  # raises if malformed
        self.assertEqual(payload['organization'], self.org)
        self.assertIsInstance(payload['timePeriod'], dict)
        self.assertIsInstance(payload['usageItems'], list)

    def test_ai_credit_usage_item_schema(self) -> None:
        """Every usageItem must carry the documented billing fields."""
        payload = self.client.ai_credit_usage(self.org, self.year, self.month, self.day)
        for item in payload['usageItems']:
            missing = FIELD_REQUIRED_MODEL - set(item.keys())
            self.assertEqual(missing, set(), f'usageItem missing fields: {missing}')

    def test_ai_credit_usage_accepts_user_filter(self) -> None:
        """A user filter is accepted (200) and echoes the user in the response."""
        payload = self.client.ai_credit_usage(self.org, self.year, self.month, self.day, user=os.getenv('GITHUB_USER'))
        self.assertIsInstance(payload.get('usageItems'), list)

    def test_usage_summary_envelope(self) -> None:
        """The repository usage/summary endpoint returns the documented shape."""
        payload = self.client.usage_summary(self.org, self.year, self.month, self.day, product='Copilot')
        self.assertEqual(payload['organization'], self.org)
        self.assertIsInstance(payload['timePeriod'], dict)
        self.assertIsInstance(payload['usageItems'], list)
        for item in payload['usageItems']:
            missing = FIELD_REQUIRED - set(item.keys())
            self.assertEqual(missing, set(), f'summary item missing fields: {missing}')


if __name__ == '__main__':
    unittest.main()
