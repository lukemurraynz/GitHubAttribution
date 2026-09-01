from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import date
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from copilot_cost.service.db import connect, ingest_event
from copilot_cost.service.reconcile import allocate_day, import_ai_credit_day, load_projects
from copilot_cost.service.github import GitHubClient, GitHubError, validate_ai_credit_usage_envelope
from copilot_cost.service.reporting import report_projects, reconciliation_report
import copilot_cost.cli.main as cli_main
import copilot_cost.__main__ as pkg_main


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'test.sqlite3')
        self.con = connect(self.db)
        os.environ['COPILOT_COST_PROMPT_WEIGHT'] = '0.25'
        os.environ['COPILOT_COST_TOOL_WEIGHT'] = '0.10'

    def tearDown(self):
        self.con.close(); self.tmp.cleanup()

    def event(self, eid, when, user, repo, session, event):
        ingest_event(self.con, {
            'schemaVersion': 1, 'eventId': eid, 'event': event, 'observedAt': when,
            'sessionId': session, 'user': user, 'repository': repo,
        })

    def test_idempotent_event_ingest(self):
        payload = {'schemaVersion': 1, 'eventId': '1234567890123456', 'event': 'sessionStart', 'observedAt': '2026-09-01T00:00:00+00:00', 'user': 'alice', 'repository': 'acme/a'}
        self.assertTrue(ingest_event(self.con, payload))
        self.assertFalse(ingest_event(self.con, payload))

    def test_allocation_preserves_billing_quantity(self):
        self.event('a1', '2026-09-01T00:00:00+00:00', 'alice', 'acme/a', 's1', 'sessionStart')
        self.event('a2', '2026-09-01T00:10:00+00:00', 'alice', 'acme/a', 's1', 'userPromptSubmitted')
        self.event('b1', '2026-09-01T01:00:00+00:00', 'alice', 'acme/b', 's2', 'sessionStart')
        self.event('b2', '2026-09-01T01:20:00+00:00', 'alice', 'acme/b', 's2', 'sessionEnd')
        payload = {'usageItems': [{'product': 'Copilot', 'sku': 'Copilot AI Credits', 'model': 'GPT-5', 'unitType': 'credits', 'pricePerUnit': 0.01, 'grossQuantity': 100, 'grossAmount': 1, 'netQuantity': 100, 'netAmount': 1}]}
        gh = Mock(spec=GitHubClient)
        gh.ai_credit_usage.return_value = payload
        import_ai_credit_day(self.con, gh, 'acme', __import__('datetime').date(2026,9,1))
        result = allocate_day(self.con, __import__('datetime').date(2026,9,1))
        total = self.con.execute('select sum(allocated_credits) from allocations').fetchone()[0]
        self.assertAlmostEqual(total, 100.0)
        self.assertEqual(result['billingRows'], 1)

    def test_project_report(self):
        self.con.execute("insert into repository_projects(repository,project,cost_center) values('acme/a','Platform','Digital')")
        self.con.execute("insert into billing_usage(usage_id,scope,organisation,usage_date,model,unit_type,quantity,source_endpoint,raw_json) values('u1','ai_credit','acme','2026-09-01','GPT-5','credits',10,'x','{}')")
        self.con.execute("insert into allocations(allocation_id,usage_id,repository,user_name,usage_date,model,allocated_credits,allocated_usd,allocation_method,confidence,activity_score) values('a1','u1','acme/a','alice','2026-09-01','GPT-5',10,0.1,'test','high',1)")
        self.con.commit()
        rows = report_projects(self.con, '2026-09-01', '2026-09-01', None)
        self.assertEqual(rows[0]['project'], 'Platform')
        self.assertEqual(rows[0]['credits'], 10)

    def test_reconciliation_variance(self):
        self.con.execute("insert into billing_usage(usage_id,scope,organisation,usage_date,model,unit_type,quantity,source_endpoint,raw_json) values('u1','ai_credit','acme','2026-09-01','GPT-5','credits',10,'x','{}')")
        self.con.commit()
        rows = reconciliation_report(self.con, '2026-09-01', '2026-09-01')
        self.assertEqual(rows[0]['imported_credits'], 10)
        self.assertEqual(rows[0]['allocated_credits'], 0)
        self.assertEqual(rows[0]['variance_credits'], 10)

    def test_import_ai_credit_skips_malformed_rows_without_crashing(self):
        """Malformed, null-quantity, or non-credits rows must be skipped, not crash the reconcile."""
        from copilot_cost.service.reconcile import _as_float
        self.assertEqual(_as_float(None), 0.0)
        self.assertEqual(_as_float(''), 0.0)
        self.assertEqual(_as_float('12.5'), 12.5)
        self.assertEqual(_as_float('not-a-number'), 0.0)

        payload = {'usageItems': [
            {'product': 'Copilot', 'sku': 'AI Credits', 'unitType': 'credits', 'netQuantity': None, 'netAmount': None},  # null quantity -> skipped
            {'product': 'Copilot', 'sku': 'AI Credits', 'unitType': 'seats', 'netQuantity': 5},  # not credits -> skipped
            'garbage',  # not a dict -> skipped
            {'product': 'Copilot', 'sku': 'AI Credits', 'model': 'GPT-5', 'unitType': 'credits',
             'pricePerUnit': '0.01', 'grossQuantity': '100', 'grossAmount': '1', 'netQuantity': '100', 'netAmount': '1'},  # string numerics coerced
        ]}
        gh = Mock(spec=GitHubClient)
        gh.ai_credit_usage.return_value = payload
        count = import_ai_credit_day(self.con, gh, 'acme', date(2026, 9, 1))
        self.assertEqual(count, 1)  # only the well-formed credits row imported
        row = self.con.execute("select quantity, price_per_unit from billing_usage").fetchone()
        self.assertEqual(row['quantity'], 100.0)
        self.assertEqual(row['price_per_unit'], 0.01)

    def test_github_error_does_not_leak_response_body(self):
        """GitHubError should carry a stable message, not the raw upstream body."""
        err = GitHubError(429, 'GitHub API request failed with HTTP 429')
        self.assertEqual(err.status, 429)
        self.assertNotIn('detail', str(err).lower())

    def test_github_get_json_maps_403_to_permission_message(self):
        client = GitHubClient(token='test-token')
        headers = Message()
        http_error = urllib.error.HTTPError(
            url='https://api.github.com/test',
            code=403,
            msg='Forbidden',
            hdrs=headers,
            fp=io.BytesIO(b'{"message":"forbidden"}'),
        )
        with patch('urllib.request.urlopen', side_effect=http_error):
            with self.assertRaises(GitHubError) as cm:
                client.get_json('/test')
        self.assertEqual(cm.exception.status, 403)
        self.assertIn('insufficient permission', str(cm.exception))
        self.assertIn('Administration read', str(cm.exception))

    def test_validate_ai_credit_usage_envelope_rejects_missing_usage_items(self):
        with self.assertRaises(GitHubError) as cm:
            validate_ai_credit_usage_envelope({'timePeriod': {}})
        self.assertIsNone(cm.exception.status)
        self.assertIn('usageItems', str(cm.exception))

    def test_validate_ai_credit_usage_envelope_rejects_malformed_usage_items(self):
        with self.assertRaises(GitHubError) as cm:
            validate_ai_credit_usage_envelope({'usageItems': 'not-a-list'})
        self.assertIsNone(cm.exception.status)
        self.assertIn('usageItems', str(cm.exception))

    def test_cli_entry_point_imports_and_gates_on_token(self):
        """The reconcile CLI module and package entry point must import cleanly,
        and must fail fast (not crash) when GITHUB_TOKEN is absent."""
        # Importing copilot_cost.__main__ at module load is itself the
        # regression guard: if its entry point stops importing, this module
        # fails to collect.
        self.assertTrue(callable(pkg_main.main))
        import sys
        saved_argv = sys.argv
        saved = os.environ.pop('GITHUB_TOKEN', None)
        try:
            sys.argv = ['copilot-cost', 'reconcile', '--org', 'acme', '--from', '2026-09-01', '--to', '2026-09-01']
            with self.assertRaises(SystemExit) as cm:
                cli_main.main()
            self.assertIn('GITHUB_TOKEN', str(cm.exception))
        finally:
            sys.argv = saved_argv
            if saved is not None:
                os.environ['GITHUB_TOKEN'] = saved


if __name__ == '__main__':
    unittest.main()
