import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from central import Settings
from central_store import Store, metadata, postgres_url, sessions, workspaces


class CentralStoreTests(unittest.TestCase):
    def test_postgres_configuration_requires_tls_and_hides_credentials(self):
        url = postgres_url('postgresql://owner:test-only-password@db.example/zero')
        self.assertEqual(url.drivername, 'postgresql+psycopg')
        self.assertEqual(url.query['sslmode'], 'require')
        self.assertNotIn('test-only-password', str(url))
        for value in ['sqlite:///tmp.db', 'postgresql://db.example', 'postgresql://u:secret@host/db?sslmode=disable']:
            with self.assertRaises(ValueError) as error:
                postgres_url(value)
            self.assertNotIn('secret', str(error.exception))

    def test_postgres_schema_and_parameters_compile_for_postgres(self):
        from sqlalchemy import select, insert, func
        dialect = postgresql.dialect()
        for table in metadata.tables.values():
            self.assertIn('CREATE TABLE', str(CreateTable(table).compile(dialect=dialect)))
        self.assertIn('FLOAT(53)', str(CreateTable(sessions).compile(dialect=dialect)))
        statement = insert(workspaces).values(revision=1, created_at='date', data='private-value')
        self.assertNotIn('private-value', str(statement.compile(dialect=dialect)))
        self.assertIn('pg_advisory_xact_lock', str(select(func.pg_advisory_xact_lock(901002)).compile(dialect=dialect)))

    def test_existing_sqlite_schema_and_history_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'central.sqlite3'
            with sqlite3.connect(path) as db:
                db.executescript('CREATE TABLE workspaces (revision INTEGER PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL); PRAGMA user_version=1;')
                db.execute('INSERT INTO workspaces VALUES (?,?,?)', (7, 'old-date', json.dumps({'preserve': '원본'})))
            store = Store(Path(directory))
            self.assertEqual(store.current(), {'revision': 7, 'data': {'preserve': '원본'}})
            self.assertEqual(store.snapshot(7)['data'], {'preserve': '원본'})
            store.engine.dispose()

    def test_database_url_is_not_exposed_in_settings_repr(self):
        value = 'scrypt$' + '0' * 32 + '$' + '0' * 64
        cfg = Settings('https://zero.example', None, value, database_url='postgresql://u:test-password@db.example/zero')
        self.assertNotIn('test-password', repr(cfg))
        self.assertNotIn(value, repr(cfg))

    def test_render_env_uses_managed_db_and_external_url_without_local_dir(self):
        env = {'DATABASE_URL': 'postgresql://u:test-password@db.example/zero',
               'RENDER_EXTERNAL_URL': 'https://zero.onrender.com', 'ZERO_OWNER_PASSWORD': 'test-only-long-owner-password'}
        with patch.dict('os.environ', env, clear=True), patch('central.hash_password', return_value='scrypt$' + '0' * 32 + '$' + '0' * 64):
            settings = Settings.from_env()
        self.assertIsNone(settings.data_dir)
        self.assertEqual(settings.origin, env['RENDER_EXTERNAL_URL'])
        self.assertEqual(settings.database_url, env['DATABASE_URL'])

    def test_render_blueprint_never_contains_a_default_secret_or_free_db(self):
        import yaml
        config = yaml.safe_load((Path(__file__).resolve().parent.parent / 'render.yaml').read_text())
        web, db = config['services'][0], config['databases'][0]
        self.assertEqual(web['autoDeployTrigger'], 'off')
        self.assertNotEqual(web['plan'], 'free'); self.assertNotEqual(db['plan'], 'free')
        self.assertEqual(web['region'], db['region'])
        self.assertEqual(db['ipAllowList'], [])
        self.assertEqual(db['diskSizeGB'], 1)
        secrets = [entry for entry in web['envVars'] if entry['key'] == 'ZERO_OWNER_PASSWORD']
        self.assertEqual(secrets, [{'key': 'ZERO_OWNER_PASSWORD', 'sync': False}])
        self.assertNotIn('disk', web)
