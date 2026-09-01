from __future__ import annotations
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import date
from .db import connect, insert_event

class Handler(BaseHTTPRequestHandler):
    server_version='CopilotCostAttribution/1.0'
    def _auth(self):
        expected=os.getenv('COPILOT_COST_INGEST_KEY')
        if not expected: return True
        got=self.headers.get('Authorization','')
        return got == 'Bearer ' + expected
    def _json(self, code, obj):
        body=json.dumps(obj,separators=(',',':')).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p=urlparse(self.path)
        if p.path=='/healthz': return self._json(200,{'status':'ok'})
        if p.path=='/v1/report':
            qs=parse_qs(p.query); start=qs.get('from',[None])[0]; end=qs.get('to',[None])[0]; repo=qs.get('repository',[None])[0]; user=qs.get('user',[None])[0]
            con=connect(); where=[]; args=[]
            if start: where.append('usage_date>=?'); args.append(start)
            if end: where.append('usage_date<=?'); args.append(end)
            if repo: where.append('repository=?'); args.append(repo)
            if user: where.append('user_name=?'); args.append(user)
            w=(' WHERE '+' AND '.join(where)) if where else ''
            rows=con.execute(f"SELECT a.repository,a.user_name,a.usage_date,COALESCE(p.project,'unmapped') project,SUM(a.allocated_credits) credits,SUM(a.allocated_usd) usd,GROUP_CONCAT(DISTINCT a.confidence) confidence FROM allocations a LEFT JOIN repository_projects p ON p.repository=a.repository{w.replace('repository=','a.repository=').replace('user_name=','a.user_name=')} GROUP BY a.repository,a.user_name,a.usage_date,p.project ORDER BY a.usage_date,a.repository,a.user_name",args).fetchall()
            return self._json(200,[dict(r) for r in rows])
        return self._json(404,{'error':'not_found'})
    def do_POST(self):
        if not self._auth(): return self._json(401,{'error':'unauthorized'})
        p=urlparse(self.path)
        if p.path!='/v1/copilot/events': return self._json(404,{'error':'not_found'})
        try:
            length=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(length) or b'{}')
            if data.get('schemaVersion') != 1 or not data.get('eventId') or not data.get('event') or not data.get('observedAt'):
                return self._json(400,{'error':'invalid_event'})
            con=connect(); created=insert_event(con,data)
            return self._json(202,{'accepted':True,'duplicate':not created})
        except Exception as e:
            return self._json(500,{'error':'ingest_failed','detail':str(e)})

def main():
    host=os.getenv('COPILOT_COST_HOST','0.0.0.0'); port=int(os.getenv('COPILOT_COST_PORT','8080'))
    ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=='__main__': main()
