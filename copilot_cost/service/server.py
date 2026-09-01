from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .db import connect, ingest_event
from .reporting import report_repositories, report_projects, report_users, reconciliation_report


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    expected = os.getenv('COPILOT_COST_INGEST_KEY')
    if not expected:
        return True
    return handler.headers.get('Authorization', '') == f'Bearer {expected}'


def _body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get('Content-Length', '0'))
    if length > 1024 * 1024:
        raise ValueError('request_too_large')
    raw = handler.rfile.read(length)
    payload = json.loads(raw or b'{}')
    if not isinstance(payload, dict):
        raise ValueError('object_required')
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = 'CopilotCostAttribution/2.0'

    def _json(self, status: int, payload: object, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, separators=(',', ':'), default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _server_error(self, code: str) -> None:
        # Do not echo internal exception strings to clients; return a stable
        # machine-readable code only. Retry-After signals the client the
        # failure is transient infra, not a permanent contract violation.
        self._json(503, {'error': code, 'errorCode': code}, {'Retry-After': '60'})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            con = connect()
            if parsed.path == '/healthz':
                return self._json(200, {'status': 'ok'})
            start = qs.get('from', [None])[0]
            end = qs.get('to', [None])[0]
            project = qs.get('project', [None])[0]
            repo = qs.get('repository', [None])[0]
            user = qs.get('user', [None])[0]
            if parsed.path == '/v1/report':
                return self._json(200, report_repositories(con, start, end, repo, user, project))
            if parsed.path == '/v1/report/repositories':
                return self._json(200, report_repositories(con, start, end, repo, user, project))
            if parsed.path == '/v1/report/projects':
                return self._json(200, report_projects(con, start, end, project))
            if parsed.path == '/v1/report/users':
                return self._json(200, report_users(con, start, end, user, repo))
            if parsed.path == '/v1/reconciliation':
                return self._json(200, reconciliation_report(con, start, end))
            return self._json(404, {'error': 'not_found'})
        except Exception:
            return self._server_error('query_failed')

    def do_POST(self) -> None:  # noqa: N802
        if not _auth_ok(self):
            return self._json(401, {'error': 'unauthorized', 'errorCode': 'unauthorized'})
        parsed = urlparse(self.path)
        if parsed.path != '/v1/copilot/events':
            return self._json(404, {'error': 'not_found'})
        try:
            payload = _body(self)
            required = ('schemaVersion', 'eventId', 'event', 'observedAt')
            if payload.get('schemaVersion') != 1 or any(not payload.get(k) for k in required):
                return self._json(400, {'error': 'invalid_event', 'errorCode': 'invalid_event'})
            created = ingest_event(connect(), payload)
            return self._json(202, {'accepted': True, 'duplicate': not created})
        except ValueError as exc:
            return self._json(400, {'error': str(exc), 'errorCode': str(exc)})
        except Exception:
            return self._server_error('ingest_failed')

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    host = os.getenv('COPILOT_COST_HOST', '0.0.0.0')
    port = int(os.getenv('COPILOT_COST_PORT', '8080'))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == '__main__':
    main()
