"""Monthly due checks entrypoint. Scheduling is configured only after deployment.
Run: python backend/recheck_keywords.py --limit 5
No WordPress writes; at most two search API calls per keyword. Do not log secrets.
"""
import argparse
import json
from central import Settings
from central_store import Store
from central_discovery import Discovery, SerpProvider
from central_keyword_bank import KeywordBank


def main():
    parser = argparse.ArgumentParser(description='Check due active keywords; preserve unknowns.')
    parser.add_argument('--limit', type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    cfg = Settings.from_env()
    if not cfg.search_key:
        print('Search provider is not configured; no checks executed.')
        return 2
    store = Store(cfg.data_dir, cfg.database_url)
    try:
        bank = KeywordBank(store, Discovery(store, SerpProvider(cfg.search_key)))
        rows = bank.due(args.limit)
        print(json.dumps({'processed': len(rows), 'needsReview': sum(r.get('record', {}).get('reviewRequired', True) for r in rows), 'incomplete': sum(r.get('status') == 'unverified' or r.get('record', {}).get('verification') != 'both_retrieved' for r in rows)}))
        return 0
    finally: store.engine.dispose()

if __name__ == '__main__': raise SystemExit(main())
