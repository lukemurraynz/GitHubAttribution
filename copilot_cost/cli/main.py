from __future__ import annotations
import argparse
import json
import os
from datetime import date

from ..db import connect
from ..github import GitHubClient
from ..reconcile import reconcile_range


def main() -> None:
    parser = argparse.ArgumentParser(prog='copilot-cost')
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('reconcile', help='Import GitHub AI-credit usage and allocate it to observed repositories')
    r.add_argument('--org', required=True)
    r.add_argument('--from', dest='start', required=True)
    r.add_argument('--to', dest='end', required=True)
    r.add_argument('--project-map', default='config/repo-projects.json')
    r.add_argument('--repo', action='append', default=[])
    r.add_argument('--repo-file')
    r.add_argument('--user', action='append', default=[])
    r.add_argument('--user-file')
    args = parser.parse_args()

    if not os.getenv('GITHUB_TOKEN'):
        raise SystemExit('GITHUB_TOKEN is required')
    users = list(args.user)
    if args.user_file and os.path.exists(args.user_file):
        with open(args.user_file, encoding='utf-8') as handle:
            users.extend(line.strip() for line in handle if line.strip() and not line.lstrip().startswith('#'))
    users = list(dict.fromkeys(users))

    repos = list(args.repo)
    if args.repo_file and os.path.exists(args.repo_file):
        with open(args.repo_file, encoding='utf-8') as handle:
            repos.extend(line.strip() for line in handle if line.strip() and not line.lstrip().startswith('#'))
    repos = list(dict.fromkeys(repos))
    con = connect()
    gh = GitHubClient(os.environ['GITHUB_TOKEN'], os.getenv('GITHUB_API_URL', 'https://api.github.com'), os.getenv('GITHUB_API_VERSION', '2026-03-10'))
    result = reconcile_range(con, gh, args.org, date.fromisoformat(args.start), date.fromisoformat(args.end), args.project_map if os.path.exists(args.project_map) else None, repos, users)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
