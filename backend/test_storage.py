import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import storage
import server
import test_server

DATA = {'format': 'zero-seo-os-backup', 'version': 2, 'exportedAt': '2026-11-13',
        'keywordsBySite': {'A-1': ['한글'], 'A-2': ['separate']},
        'jobs': [{'id': '1', 'site': 'A-1', 'keyword': '한글', 'status': '취소', 'createdAt': '2026-11-13'}],
        'sites': {'A-1': {'name': '사이트', 'url': 'https://example.com'}, 'A-2': {'name': '', 'url': ''}}}


class StorageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(storage, 'DB', Path(tmp.name) / '.state/workspace.sqlite3')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_append_restart_and_read_preserve_unicode(self):
        first = storage.snapshot({'action': 'save', 'data': DATA})
        second = storage.snapshot({'action': 'save', 'data': {**DATA, 'jobs': []}})
        self.assertGreater(second['id'], first['id'])
        self.assertEqual(storage.snapshot({'action': 'read', 'id': first['id']})['data'], DATA)
        self.assertEqual(len(storage.snapshot({'action': 'list'})['snapshots']), 2)

    def test_invalid_payload_never_creates_database(self):
        for mutate in [lambda d: d.update(password='secret'),
                       lambda d: d['sites']['A-1'].update(token='secret'),
                       lambda d: d['jobs'].append(d['jobs'][0].copy()),
                       lambda d: d['keywordsBySite'].update({'A-2': 'bad'}),
                       lambda d: d['sites']['A-1'].update(url='https://user:pass@example.com')]:
            data = copy.deepcopy(DATA)
            mutate(data)
            with self.assertRaises((ValueError, server.VerificationError)):
                storage.snapshot({'action': 'save', 'data': data})
        self.assertFalse(storage.DB.exists())

    def test_read_id_not_sql(self):
        with self.assertRaises(ValueError):
            storage.snapshot({'action': 'read', 'id': '1 OR 1=1'})


class StorageHttpTests(test_server.HttpTests):
    def test_storage_origin_guard(self):
        with patch.object(storage, 'snapshot') as snapshot:
            self.assertEqual(self.send('https://attacker.example', path='/api/storage')[0], 403)
            snapshot.assert_not_called()

    def test_storage_route(self):
        with patch.object(storage, 'snapshot', return_value={'snapshots': []}) as snapshot:
            self.assertEqual(self.send(server.ORIGIN, path='/api/storage')[0], 200)
            snapshot.assert_called_once()

    def test_actual_save_list_read_over_http(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage, 'DB', Path(tmp) / 'data.sqlite3'):
            with patch.object(test_server, 'PAYLOAD', {'action': 'save', 'data': DATA}):
                status, _, body = self.send(server.ORIGIN, path='/api/storage')
                self.assertEqual(status, 200)
                saved = test_server.json.loads(body)
                self.assertTrue(saved['saved'])
            with patch.object(test_server, 'PAYLOAD', {'action': 'read', 'id': saved['id']}):
                status, _, body = self.send(server.ORIGIN, path='/api/storage')
                self.assertEqual(status, 200)
                self.assertEqual(test_server.json.loads(body)['data'], DATA)
