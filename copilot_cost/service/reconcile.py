from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta, timezone, date
from .db import connect
from .github import GitHubClient

def _usage_rows(payload, scope, org, default_date=None, user=None, repo=None):
    items=payload.get('usageItems',[]) if isinstance(payload,dict) else []
    result=[]
    for item in items:
        qty=item.get('netQuantity', item.get('grossQuantity', 0)) or 0
        product=item.get('product')
        unit=item.get('unitType')
        model=item.get('model')
        sku=item.get('sku')
        if qty is None: continue
        usage_id=hashlib.sha256(json.dumps([scope,org,user,repo,default_date,model,product,sku,qty],sort_keys=True).encode()).hexdigest()
        result.append((usage_id,scope,org,user,repo,default_date,model,product,sku,unit,float(qty),item.get('grossAmount'),item.get('netAmount')))
    return result

def import_ai_credit_day(con, gh, org, d: date):
    payload=gh.ai_credit_usage(org,d.year,d.month,d.day)
    rows=_usage_rows(payload,'ai_credit',org,d.isoformat())
    for r in rows:
        con.execute("""INSERT OR IGNORE INTO billing_usage
          (usage_id,scope,organisation,user_name,repository,usage_date,model,product,sku,unit_type,quantity,gross_amount,net_amount,source_endpoint)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*r,'/organizations/{org}/settings/billing/ai_credit/usage'))
    con.commit(); return len(rows)

def import_repo_summary_day(con, gh, org, d: date, repository: str):
    payload=gh.usage_summary(org,d.year,d.month,d.day,repository=repository,product='Copilot')
    rows=[]
    for row in _usage_rows(payload,'usage_summary_repo',org,d.isoformat(),repo=repository):
        product=row[7] or ''
        unit=(row[9] or '').lower()
        sku=(row[8] or '').lower()
        if 'credit' in product.lower() or 'credit' in unit or 'credit' in sku:
            rows.append(row)
    for r in rows:
        con.execute("""INSERT OR IGNORE INTO billing_usage
          (usage_id,scope,organisation,user_name,repository,usage_date,model,product,sku,unit_type,quantity,gross_amount,net_amount,source_endpoint)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*r,'/organizations/{org}/settings/billing/usage/summary'))
    con.commit(); return len(rows)

def allocate_day(con, d: date):
    day=d.isoformat()
    # Prefer exact repository billing rows imported from the usage summary.
    exact=con.execute("SELECT * FROM billing_usage WHERE usage_date=? AND scope='usage_summary_repo' AND repository IS NOT NULL",(day,)).fetchall()
    if exact:
        for u in exact:
            con.execute("DELETE FROM allocations WHERE usage_id=?",(u['usage_id'],))
            con.execute("INSERT INTO allocations(allocation_id,usage_id,repository,user_name,usage_date,allocated_credits,allocated_usd,allocation_method,confidence) VALUES(?,?,?,?,?,?,?,?,?)",
                        (hashlib.sha256((u['usage_id']+'exact').encode()).hexdigest(),u['usage_id'],u['repository'],u['user_name'],day,u['quantity'],u['quantity']*0.01,'github-usage-summary-repository','high'))
        con.commit()
    # Fallback for org AI-credit records: allocate by active session duration per user.
    org_rows=con.execute("SELECT * FROM billing_usage WHERE usage_date=? AND scope='ai_credit'",(day,)).fetchall()
    for u in org_rows:
        if u['unit_type'] and 'credit' not in u['unit_type'].lower(): continue
        user=u['user_name']
        # These rows are organisation-level, so user may be null. Use all observed users when null.
        users=[r[0] for r in con.execute("SELECT DISTINCT user_name FROM events WHERE substr(observed_at,1,10)=? AND user_name IS NOT NULL",(day,)).fetchall()] if not user else [user]
        if not users: continue
        total=con.execute("SELECT COUNT(*) FROM events WHERE substr(observed_at,1,10)=?",(day,)).fetchone()[0] or 1
        grouped=con.execute("SELECT repository, COUNT(*) AS c FROM events WHERE substr(observed_at,1,10)=? AND (? IS NULL OR user_name=?) AND repository IS NOT NULL GROUP BY repository",(day,user,user)).fetchall()
        if not grouped: continue
        denom=sum(r['c'] for r in grouped)
        con.execute("DELETE FROM allocations WHERE usage_id=?",(u['usage_id'],))
        for r in grouped:
            credits=u['quantity']*(r['c']/denom)
            conf='medium' if len(grouped)==1 else 'low'
            con.execute("INSERT INTO allocations(allocation_id,usage_id,repository,user_name,usage_date,allocated_credits,allocated_usd,allocation_method,confidence) VALUES(?,?,?,?,?,?,?,?,?)",
                        (hashlib.sha256((u['usage_id']+r['repository']).encode()).hexdigest(),u['usage_id'],r['repository'],user,day,credits,credits*0.01,'observed-event-share-fallback',conf))
    con.commit()
