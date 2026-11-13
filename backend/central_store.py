"""Versioned owner store. Production PostgreSQL; legacy development SQLite retained."""
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import (BigInteger, Column, Float, Index, Integer, MetaData, Table,
                        Text, and_, create_engine, delete, func, insert, or_, select)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

metadata = MetaData()
sessions = Table('sessions', metadata, Column('token_hash', Text, primary_key=True),
                 Column('csrf', Text, nullable=False), Column('expires', Float(53), nullable=False),
                 Column('auth_revision', Text, nullable=False))
attempts = Table('login_attempts', metadata, Column('client', Text, nullable=False),
                 Column('at', Float(53), nullable=False))
Index('login_time', attempts.c.at)
workspaces = Table('workspaces', metadata, Column('revision', BigInteger, primary_key=True, autoincrement=False),
                   Column('created_at', Text, nullable=False), Column('data', Text, nullable=False))
schema_version = Table('zero_schema_version', metadata,
                       Column('id', Integer, primary_key=True, autoincrement=False),
                       Column('version', Integer, nullable=False))


def postgres_url(value):
    try:
        url = make_url(value)
        if url.get_backend_name() not in ('postgres', 'postgresql') or not url.host or not url.database:
            raise ValueError()
        if url.query.get('sslmode', 'require') not in ('require', 'verify-ca', 'verify-full'):
            raise ValueError()
        return url.set(drivername='postgresql+psycopg').update_query_dict({'sslmode': url.query.get('sslmode', 'require')})
    except Exception:
        raise ValueError('DATABASE_URL must be PostgreSQL with TLS enabled; its value is not logged.') from None


class Store:
    def __init__(self, directory=None, database_url=None):
        self.path = None
        if database_url:
            self.kind = 'postgresql'
            self.engine = create_engine(postgres_url(database_url), pool_pre_ping=True, pool_size=3,
                                        max_overflow=0, pool_timeout=5, pool_recycle=300,
                                        connect_args={'connect_timeout': 5}, hide_parameters=True)
        else:
            self.kind = 'sqlite'
            if directory is None:
                raise ValueError('PostgreSQL URL or explicit private SQLite directory is required.')
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = directory / 'central.sqlite3'
            self.engine = create_engine(URL.create('sqlite', database=str(self.path)),
                                        connect_args={'timeout': 5, 'check_same_thread': False},
                                        poolclass=NullPool, hide_parameters=True)
        try:
            self.initialize()
        except Exception:
            self.engine.dispose()
            raise ValueError('Central database initialization failed. Check connection, TLS and schema version; no database URL is shown.') from None
        if self.path is not None:
            os.chmod(self.path, 0o600)

    def lock(self, db, key):
        if self.kind == 'postgresql':
            db.execute(select(func.pg_advisory_xact_lock(key)))
        else:
            db.exec_driver_sql('BEGIN IMMEDIATE')

    def initialize(self):
        with self.engine.begin() as db:
            self.lock(db, 901001)
            if self.kind == 'sqlite':
                version = db.exec_driver_sql('PRAGMA user_version').scalar_one()
                if version not in (0, 1):
                    raise ValueError('Unknown SQLite schema.')
            else:
                schema_version.create(db, checkfirst=True)
                version = db.execute(select(schema_version.c.version).where(schema_version.c.id == 1)).scalar_one_or_none()
                if version not in (None, 1):
                    raise ValueError('Unknown PostgreSQL schema.')
                if version is None:
                    db.execute(insert(schema_version).values(id=1, version=1))
            metadata.create_all(db, tables=[sessions, attempts, workspaces])
            if self.kind == 'sqlite':
                db.exec_driver_sql('PRAGMA user_version=1')

    def current(self):
        with self.engine.connect() as db:
            row = db.execute(select(workspaces).order_by(workspaces.c.revision.desc()).limit(1)).mappings().first()
        return {'revision': row['revision'], 'data': json.loads(row['data'])} if row else {'revision': 0, 'data': None}

    def save(self, base_revision, data):
        if type(base_revision) is not int or base_revision < 0:
            raise HTTPException(400, '저장 기준 버전이 올바르지 않습니다.')
        with self.engine.begin() as db:
            self.lock(db, 901002)
            current = db.execute(select(func.coalesce(func.max(workspaces.c.revision), 0))).scalar_one()
            if current != base_revision:
                raise HTTPException(409, '다른 창에서 먼저 저장했습니다. 현재 변경을 백업한 뒤 서버 데이터를 다시 불러오세요.')
            revision = current + 1
            db.execute(insert(workspaces).values(revision=revision,
                       created_at=datetime.now(timezone.utc).isoformat(), data=json.dumps(data, ensure_ascii=False)))
        return {'revision': revision, 'data': data}

    def login_allowed(self, client):
        now = time.time()
        with self.engine.begin() as db:
            self.lock(db, 901003)
            db.execute(delete(attempts).where(attempts.c.at < now - 60))
            count = db.execute(select(func.count()).select_from(attempts).where(attempts.c.client == client)).scalar_one()
            total = db.execute(select(func.count()).select_from(attempts)).scalar_one()
            if count >= 5 or total >= 20:
                raise HTTPException(429, '로그인 시도가 많습니다. 잠시 후 다시 시도하세요.')
            db.execute(insert(attempts).values(client=client, at=now))

    def find_session(self, token_hash, auth_revision):
        with self.engine.connect() as db:
            row = db.execute(select(sessions).where(and_(sessions.c.token_hash == token_hash,
                             sessions.c.expires > time.time(), sessions.c.auth_revision == auth_revision))).mappings().first()
        return dict(row) if row else None

    def issue_session(self, token_hash, csrf, expires, auth_revision, old_hash, client):
        with self.engine.begin() as db:
            db.execute(delete(sessions).where(or_(sessions.c.expires <= time.time(), sessions.c.auth_revision != auth_revision)))
            db.execute(delete(sessions).where(sessions.c.token_hash == old_hash))
            db.execute(insert(sessions).values(token_hash=token_hash, csrf=csrf, expires=expires, auth_revision=auth_revision))
            db.execute(delete(attempts).where(attempts.c.client == client))

    def revoke_session(self, token_hash):
        with self.engine.begin() as db:
            db.execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    def snapshots(self):
        with self.engine.connect() as db:
            rows = db.execute(select(workspaces.c.revision, workspaces.c.created_at).order_by(workspaces.c.revision.desc()).limit(100)).mappings().all()
        return [dict(row) for row in rows]

    def snapshot(self, revision):
        with self.engine.connect() as db:
            row = db.execute(select(workspaces).where(workspaces.c.revision == revision)).mappings().first()
        if row is None:
            raise HTTPException(404, '저장본을 찾지 못했습니다.')
        return {'revision': row['revision'], 'data': json.loads(row['data'])}
