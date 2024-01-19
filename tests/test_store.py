import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_isolation_before_search(self):
        self.assertTrue(self.store.ask('sam', 'private coaching Friday')['abstained'])
        self.assertTrue(self.store.ask('alex', 'field equipment inventory')['abstained'])
        self.assertFalse(self.store.ask('alex', 'private coaching Friday')['abstained'])
        self.assertFalse(self.store.ask('jules', 'field equipment inventory')['abstained'])

    def test_edit_delete_reindex_versions(self):
        self.store.mutate('alex', 'save', {'title': 'Unique', 'body': 'Zebraplan is Wednesday.', 'visibility': 'private'})
        src = self.store.ask('alex', 'Zebraplan')['sources'][0]
        self.store.mutate('alex', 'save', {'id': src['id'], 'title': 'Unique', 'body': 'Quokka is Tuesday.', 'visibility': 'private'})
        self.assertTrue(self.store.ask('alex', 'Zebraplan')['abstained'])
        self.assertEqual(self.store.ask('alex', 'Quokka')['sources'][0]['version'], 2)
        self.store.mutate('alex', 'delete', {'id': src['id']})
        self.assertTrue(self.store.ask('alex', 'Quokka')['abstained'])

    def test_approval_foreign_replay_and_cross_workspace(self):
        with self.assertRaises(ValueError):
            self.store.mutate('alex', 'propose', {'title': 'x', 'workspace': 'field'})
        proposal = self.store.mutate('alex', 'propose', {'title': 'Review notes'})
        with self.assertRaises(ValueError):
            self.store.mutate('sam', 'approve', proposal)
        self.assertEqual(self.store.state('alex')['tasks'], [])
        self.store.mutate('alex', 'approve', proposal)
        with self.assertRaises(ValueError):
            self.store.mutate('alex', 'approve', proposal)
        self.assertEqual(len(self.store.state('alex')['tasks']), 1)

    def test_persistence_and_seed_not_recreated(self):
        self.store.mutate('alex', 'delete', {'id': 1})
        self.store.db.close()
        self.store = Store(self.path)
        self.assertNotIn(1, [d['id'] for d in self.store.visible('alex')])

    def test_bad_types_and_foreign_edit(self):
        for bad in ([], {}, True, '1'):
            with self.assertRaises(ValueError):
                self.store.mutate('alex', 'delete', {'id': bad})
        with self.assertRaises(ValueError):
            self.store.mutate('sam', 'delete', {'id': 1})
        with self.assertRaises(ValueError):
            self.store.ask('alex', ['query'])

    def test_fallback_isolation(self):
        self.store.fts = False
        self.assertTrue(self.store.ask('sam', 'coaching')['abstained'])
        self.assertFalse(self.store.ask('alex', 'accessibility')['abstained'])

    def test_optional_model_citations_and_access(self):
        self.store.model = 'mock-model'
        def generate(query, sources):
            self.assertTrue(all(s['id'] in {1, 2} for s in sources))
            return {'answer': 'Alex owns the checklist.', 'citations': [{'id': 1, 'version': 1}], 'abstained': False}
        with patch.object(self.store, 'generate', side_effect=generate):
            self.assertEqual(self.store.ask('sam', 'accessibility', True)['mode'], 'model')
        for invalid in ({}, {'answer': 'leak', 'citations': [{'id': 4, 'version': 1}], 'abstained': False}, {'answer': 'stale', 'citations': [{'id': 1, 'version': 99}], 'abstained': False}):
            with patch.object(self.store, 'generate', return_value=invalid):
                self.assertTrue(self.store.ask('sam', 'accessibility', True)['abstained'])
        with patch.object(self.store, 'generate', side_effect=ValueError('malformed JSON')):
            self.assertTrue(self.store.ask('sam', 'accessibility', True)['abstained'])
        with patch.object(self.store, 'generate') as model:
            self.store.ask('sam', 'private coaching', True)
            model.assert_not_called()

    def test_external_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            Store(':memory:', endpoint='https://example.com')


if __name__ == '__main__':
    unittest.main()
