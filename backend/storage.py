"""Append-only local snapshots. No credentials, migrations, or automatic restore."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / '.state' / 'workspace.sqlite3'
SITES = ('A-1', 'A-2')
STATUSES = {'대기', '진행 중', '재시도 대기', '검토·보류', '발행 예약', '완료', '실패', '취소'}


def validate(data):
    if not isinstance(data, dict) or set(data) != {'format', 'version', 'exportedAt', 'keywordsBySite', 'jobs', 'sites'}:
        raise ValueError('전체 백업 형식이 올바르지 않습니다.')
    if data['format'] != 'zero-seo-os-backup' or data['version'] != 2 or not isinstance(data['exportedAt'], str):
        raise ValueError('v2 전체 백업이 필요합니다.')
    keywords, sites, jobs = data['keywordsBySite'], data['sites'], data['jobs']
    if not isinstance(keywords, dict) or set(keywords) != set(SITES) or not isinstance(sites, dict) or set(sites) != set(SITES):
        raise ValueError('사이트별 데이터 형식 오류입니다.')
    for site in SITES:
        if not isinstance(keywords[site], list) or not all(isinstance(x, str) for x in keywords[site]):
            raise ValueError('키워드 형식 오류입니다.')
        reg = sites[site]
        if not isinstance(reg, dict) or set(reg) != {'name', 'url'} or not all(isinstance(v, str) for v in reg.values()):
            raise ValueError('사이트에는 이름과 주소만 저장할 수 있습니다.')
        if reg['url']:
            from server import normalize_url
            normalize_url(reg['url'])
    if not isinstance(jobs, list):
        raise ValueError('작업 형식 오류입니다.')
    ids = set()
    for job in jobs:
        if (not isinstance(job, dict) or set(job) != {'id', 'site', 'keyword', 'status', 'createdAt'}
                or not all(isinstance(v, str) for v in job.values()) or job['site'] not in SITES
                or job['status'] not in STATUSES or not job['id'] or job['id'] in ids):
            raise ValueError('작업 형식 또는 중복 ID 오류입니다.')
        ids.add(job['id'])
    return data


def snapshot(payload):
    if not isinstance(payload, dict) or payload.get('action') not in ('save', 'list', 'read'):
        raise ValueError('저장 요청 형식 오류입니다.')
    action = payload['action']
    expected = {'action', 'data'} if action == 'save' else {'action', 'id'} if action == 'read' else {'action'}
    if set(payload) != expected:
        raise ValueError('허용되지 않은 저장 필드입니다.')
    data = validate(payload['data']) if action == 'save' else None
    if action == 'read' and (type(payload['id']) is not int or payload['id'] <= 0):
        raise ValueError('저장본 ID 오류입니다.')
    DB.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(sqlite3.connect(DB, timeout=5)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL)')
        if action == 'save':
            now = datetime.now(timezone.utc).isoformat()
            cursor = db.execute('INSERT INTO snapshots(created_at, data) VALUES (?, ?)', (now, json.dumps(data, ensure_ascii=False)))
            db.commit()
            return {'saved': True, 'id': cursor.lastrowid, 'createdAt': now}
        if action == 'list':
            return {'snapshots': [{'id': r[0], 'createdAt': r[1]} for r in db.execute('SELECT id, created_at FROM snapshots ORDER BY id DESC LIMIT 100')]}
        row = db.execute('SELECT data FROM snapshots WHERE id = ?', (payload['id'],)).fetchone()
        if row is None:
            raise ValueError('저장본을 찾지 못했습니다.')
        return {'data': validate(json.loads(row[0]))}
