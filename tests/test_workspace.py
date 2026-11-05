import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Store


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'workspace.db')

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def save(self, **values):
        self.store.mutate('alex', 'save', dict(title='Citation source', body='Original amber evidence.', visibility='workspace', **values))
        return self.store.db.execute('SELECT max(id) FROM docs').fetchone()[0]

    def test_historical_citation_and_current_permission_revocation(self):
        doc = self.save()
        self.store.mutate('alex', 'save', {'id': doc, 'title': 'Changed', 'body': 'New evidence.', 'visibility': 'workspace'})
        self.assertEqual(self.store.source('sam', doc, 1)['body'], 'Original amber evidence.')
        self.assertEqual([v['version'] for v in self.store.history('alex', doc)], [2, 1])
        self.store.mutate('alex', 'save', {'id': doc, 'title': 'Private', 'body': 'New evidence.', 'visibility': 'private'})
        with self.assertRaises(ValueError):
            self.store.source('sam', doc, 1)
        self.assertEqual(self.store.source('alex', doc, 1)['title'], 'Citation source')

    def test_trash_hides_history_and_restore_preserves_version(self):
        doc = self.save()
        self.store.mutate('alex', 'delete', {'id': doc})
        with self.assertRaises(ValueError):
            self.store.source('alex', doc, 1)
        self.assertEqual(self.store.trash('sam'), [])
        with self.assertRaises(ValueError):
            self.store.restore('sam', doc)
        self.store.restore('alex', doc)
        self.assertEqual(self.store.source('alex', doc)['version'], 1)
        self.assertFalse(self.store.ask('sam', 'amber')['abstained'])

    def test_metadata_filters_and_invalid_payloads(self):
        doc = self.save(collection='Planning', tags=['Launch', 'launch', 'Review'])
        result = self.store.library('sam', {'filters': {'collection': 'Planning', 'tag': 'launch'}})
        self.assertEqual([d['id'] for d in result['docs']], [doc])
        self.assertEqual(json.loads(result['docs'][0]['tags']), ['launch', 'review'])
        for value in ({'tags': 'bad'}, {'tags': ['']}, {'collection': []}):
            with self.assertRaises(ValueError):
                self.store.set_metadata('alex', dict(id=doc, **value))
        with self.assertRaises(ValueError):
            self.store.library('sam', {'offset': True})

    def test_phrase_ranking_pagination_and_fallback_agree(self):
        self.save()
        first = self.store.search('alex', {'query': '"amber evidence"', 'limit': 1})
        self.assertEqual(first['total'], 1)
        self.assertEqual(self.store.search('sam', {'query': '"evidence amber"'})['total'], 0)
        self.store.fts = False
        self.assertEqual(self.store.search('alex', {'query': '"amber evidence"', 'limit': 1}), first)
        self.assertEqual(self.store.search('alex', {'query': 'amber', 'offset': 1})['sources'], [])
