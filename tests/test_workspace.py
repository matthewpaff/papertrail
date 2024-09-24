import json
import sys
import tempfile
import unittest
from unittest.mock import patch
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

    def test_private_history_never_inherits_new_workspace_sharing(self):
        self.store.mutate('alex', 'save', {'title': 'Private origin', 'body': 'Secret origin.', 'visibility': 'private'})
        doc = self.store.db.execute('SELECT max(id) FROM docs').fetchone()[0]
        self.store.mutate('alex', 'save', {'id': doc, 'title': 'Shared now', 'body': 'Public replacement.', 'visibility': 'workspace'})
        self.assertEqual([v['version'] for v in self.store.history('sam', doc)], [2])
        with self.assertRaises(ValueError):
            self.store.source('sam', doc, 1)
        with self.assertRaises(ValueError):
            self.store.restore_revision('sam', {'id': doc, 'version': 1})

    def test_revision_restore_creates_version_and_preserves_current_privacy(self):
        doc = self.save()
        self.store.mutate('alex', 'save', {'id': doc, 'title': 'Restricted now', 'body': 'Changed body.', 'visibility': 'private'})
        restored = self.store.restore_revision('alex', {'id': doc, 'version': 1})
        self.assertEqual(restored['version'], 3)
        self.assertEqual(self.store.source('alex', doc)['visibility'], 'private')
        self.assertEqual(self.store.source('alex', doc, 2)['body'], 'Changed body.')
        self.assertTrue(self.store.ask('sam', 'amber')['abstained'])
        self.assertEqual(self.store.ask('alex', 'amber')['sources'][0]['version'], 3)

    def test_archive_preview_is_read_only_and_import_deduplicates(self):
        self.save(collection='Exported', tags=['draft'])
        archive = self.store.export_documents('alex')
        self.assertNotIn('Research debrief', [d['title'] for d in archive['documents']])
        before = self.store.db.execute('SELECT count(*) FROM docs').fetchone()[0]
        preview = self.store.preview_import('alex', archive)
        self.assertEqual(preview['create_count'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM docs').fetchone()[0], before)
        imported = self.store.import_documents('alex', archive)
        self.assertEqual(imported['created'], [])
        self.assertEqual(imported['skipped'], len(archive['documents']))
        clone = self.store.import_documents('jules', archive)
        self.assertEqual(len(clone['created']), len(archive['documents']))
        for doc in clone['created']:
            self.assertEqual(self.store.source('jules', doc)['workspace'], 'field')
            self.assertEqual(self.store.source('jules', doc)['owner'], 'jules')

    def test_archive_validation_is_all_or_nothing_and_rejects_identity_fields(self):
        good = {'title': 'Atomic new', 'body': 'New body.', 'visibility': 'private', 'collection': '', 'tags': []}
        archive = {'format': 'papertrail.documents.v1', 'documents': [good, dict(good, owner='sam')]}
        before = self.store.db.execute('SELECT count(*) FROM docs').fetchone()[0]
        with self.assertRaises(ValueError):
            self.store.import_documents('alex', archive)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM docs').fetchone()[0], before)
        archive['documents'] = [good, good]
        result = self.store.import_documents('alex', archive)
        self.assertEqual(len(result['created']), 1)
        self.assertEqual(result['skipped'], 1)

    def test_ranker_parity_title_boost_ties_and_query_punctuation(self):
        for title, body in [('Orchid owner', 'A quiet planning note.'), ('Body match', 'Orchid owner is Alex.'), ('Another body', 'Orchid owner is Sam.')]:
            self.store.mutate('alex', 'save', {'title': title, 'body': body, 'visibility': 'workspace'})
        queries = ['orchid owner', '"orchid owner"', 'orchid OR owner:*', 'unknownword', 'the and is']
        expected = [self.store.search('sam', {'query': query, 'limit': 50}) for query in queries]
        self.assertEqual(expected[0]['sources'][0]['title'], 'Orchid owner')
        ids = [r['id'] for r in expected[0]['sources'][1:]]
        self.assertEqual(ids, sorted(ids))
        self.store.fts = False
        for query, result in zip(queries, expected):
            self.assertEqual(self.store.search('sam', {'query': query, 'limit': 50}), result)
        first = self.store.search('sam', {'query': 'orchid', 'limit': 1})
        second = self.store.search('sam', {'query': 'orchid', 'limit': 1, 'offset': 1})
        self.assertNotEqual(first['sources'][0]['id'], second['sources'][0]['id'])

    def test_saved_queries_are_personal_bounded_and_persistent(self):
        self.store.save_query('alex', {'name': 'Launch', 'query': 'accessibility', 'filters': {'bookmarked': True}})
        row = self.store.saved_queries('alex')[0]
        self.assertEqual(self.store.saved_queries('sam'), [])
        with self.assertRaises(ValueError):
            self.store.delete_query('sam', row['id'])
        self.store.save_query('alex', {'name': 'Launch', 'query': 'review'})
        self.assertEqual(self.store.saved_queries('alex')[0]['id'], row['id'])
        self.assertEqual(self.store.saved_queries('alex')[0]['query'], 'review')
        for i in range(19):
            self.store.save_query('alex', {'name': 'Saved ' + str(i), 'query': 'launch'})
        with self.assertRaises(ValueError):
            self.store.save_query('alex', {'name': 'Too many', 'query': 'launch'})
        with self.assertRaises(ValueError):
            self.store.save_query('sam', {'name': 'Invalid', 'query': 'launch', 'filters': None})
        path = self.store.db.execute('PRAGMA database_list').fetchone()[2]
        self.store.db.close()
        self.store = Store(path)
        self.assertEqual(len(self.store.saved_queries('alex')), 20)

    def test_due_dates_validate_leap_days_and_sort_without_timezones(self):
        for value in ('2025-02-29', '2026-13-01', '2026-1-01', '2026-11-05T12:00:00Z', None, 20261105):
            with self.assertRaises(ValueError):
                self.store.mutate('alex', 'propose', {'title': 'Invalid', 'due': value})
        for due in ('', '2028-02-29', '2027-01-01'):
            proposal = self.store.mutate('alex', 'propose', {'title': 'Dated task', 'due': due})
            self.store.mutate('alex', 'approve', proposal)
        tasks = self.store.task_list('alex', {})['tasks']
        self.assertEqual([t['due'] for t in tasks], ['2027-01-01', '2028-02-29', ''])
        self.assertEqual(self.store.task_list('alex', {'due_before': '2027-12-31'})['total'], 1)
        self.store.task_due('alex', {'id': tasks[0]['id'], 'due': ''})
        self.assertEqual(self.store.task_list('alex', {'due_before': '2027-12-31'})['total'], 0)

    def test_expiry_and_cancellation_are_terminal_approval_states(self):
        with patch('workspace.time.time', return_value=1000):
            proposal = self.store.mutate('alex', 'propose', {'title': 'Expires soon'})
        with patch('workspace.time.time', return_value=1600):
            with self.assertRaises(ValueError):
                self.store.mutate('alex', 'approve', proposal)
        self.assertEqual(self.store.db.execute('SELECT status FROM proposals WHERE id=?', (proposal['proposal'],)).fetchone()[0], 'expired')
        proposal = self.store.mutate('alex', 'propose', {'title': 'Cancel me'})
        with self.assertRaises(ValueError):
            self.store.cancel_proposal('sam', proposal['proposal'])
        self.store.cancel_proposal('alex', proposal['proposal'])
        for action in ('approve', 'cancel-proposal'):
            with self.assertRaises(ValueError):
                self.store.mutate('alex', action, proposal)
        self.assertEqual(self.store.task_list('alex', {})['total'], 0)
        self.assertEqual(self.store.pending_proposals('alex'), [])

    def test_task_status_and_due_changes_require_owner_even_in_same_workspace(self):
        proposal = self.store.mutate('alex', 'propose', {'title': 'Ownership boundary'})
        self.store.mutate('alex', 'approve', proposal)
        task = self.store.task_list('alex', {})['tasks'][0]
        for actor in ('sam', 'jules'):
            with self.assertRaises(ValueError):
                self.store.task_transition(actor, {'id': task['id'], 'status': 'complete'})
            with self.assertRaises(ValueError):
                self.store.task_due(actor, {'id': task['id'], 'due': '2028-02-29'})
            self.assertEqual(self.store.task_list(actor, {})['total'], 0)
        self.store.task_transition('alex', {'id': task['id'], 'status': 'complete'})
        self.assertEqual(self.store.task_list('alex', {'status': 'open'})['total'], 0)
        with self.assertRaises(ValueError):
            self.store.task_transition('alex', {'id': task['id'], 'status': 'complete'})
        self.store.task_transition('alex', {'id': task['id'], 'status': 'open'})
        self.assertEqual(self.store.task_list('alex', {'status': 'open'})['total'], 1)
