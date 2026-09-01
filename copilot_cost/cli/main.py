from __future__ import annotations
import argparse, os, json
from datetime import date, timedelta
from ..db import connect
from ..github import GitHubClient
from ..reconcile import import_ai_credit_day, import_repo_summary_day, allocate_day

def main():
    ap=argparse.ArgumentParser(prog='copilot-cost')
    sp=ap.add_subparsers(dest='cmd',required=True)
    r=sp.add_parser('reconcile'); r.add_argument('--org',required=True); r.add_argument('--from',dest='start',required=True); r.add_argument('--to',dest='end',required=True); r.add_argument('--repo',action='append',default=[]); r.add_argument('--repo-file',default=None); r.add_argument('--project-map',default='config/repo-projects.json')
    args=ap.parse_args(); con=connect(); gh=GitHubClient(os.environ['GITHUB_TOKEN'],os.getenv('GITHUB_API_URL','https://api.github.com'),os.getenv('GITHUB_API_VERSION','2026-03-10'))
    if args.cmd=='reconcile':
        repos=list(args.repo)
        if args.repo_file and os.path.exists(args.repo_file): repos += [x.strip() for x in open(args.repo_file,encoding='utf-8') if x.strip() and not x.lstrip().startswith('#')]
        repos=list(dict.fromkeys(repos))
        if args.project_map and os.path.exists(args.project_map):
            mapping=json.load(open(args.project_map,encoding='utf-8'))
            for repo,project in mapping.items(): con.execute('INSERT OR REPLACE INTO repository_projects(repository,project) VALUES(?,?)',(repo,project))
            con.commit()
        d=date.fromisoformat(args.start); end=date.fromisoformat(args.end)
        while d<=end:
            import_ai_credit_day(con,gh,args.org,d)
            for repo in repos: import_repo_summary_day(con,gh,args.org,d,repo)
            allocate_day(con,d); d += timedelta(days=1)
        print('reconciliation complete')
if __name__=='__main__': main()
