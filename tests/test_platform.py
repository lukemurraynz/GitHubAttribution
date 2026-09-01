from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from copilot_cost.service.db import connect, ingest_event
from copilot_cost.service.reconcile import allocate_day, import_ai_credit_day, load_projects
from copilot_cost.service.github import GitHubClient
from copilot_cost.service.reporting import report_projects, reconciliation_report


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


if __name__ == '__main__':
    unittest.main()
