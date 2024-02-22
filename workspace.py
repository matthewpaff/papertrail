"""Scoped workspace operations shared by the HTTP app and local CLI."""
import json
import re
import time


class Workspace:
    def upgrade(self):
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(docs)')}
        for name, definition in [('deleted', 'INTEGER NOT NULL DEFAULT 0'), ('collection', "TEXT NOT NULL DEFAULT ''"), ('tags', "TEXT NOT NULL DEFAULT '[]'")]:
            if name not in columns:
                self.db.execute('ALTER TABLE docs ADD COLUMN ' + name + ' ' + definition)
        self.db.execute('''CREATE TABLE IF NOT EXISTS versions(doc INTEGER,version INTEGER,title TEXT,body TEXT,owner TEXT,workspace TEXT,visibility TEXT,collection TEXT,tags TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(doc,version))''')
        self.db.execute('''INSERT OR IGNORE INTO versions(doc,version,title,body,owner,workspace,visibility,collection,tags) SELECT id,version,title,body,owner,workspace,visibility,collection,tags FROM docs''')
        self.db.commit()

    @staticmethod
    def positive(value, name='ID'):
        if type(value) is not int or value < 1:
            raise ValueError(name + ' must be a positive integer.')
        return value

    def owned(self, actor, doc_id):
        self.positive(doc_id)
        row = self.db.execute('SELECT * FROM docs WHERE id=? AND owner=? AND workspace=?', (doc_id, actor, self.persona(actor)['workspace'])).fetchone()
        if not row:
            raise ValueError('Source unavailable or not owned by this persona.')
        return row

    def snapshot(self, doc_id):
        self.db.execute('''INSERT OR IGNORE INTO versions(doc,version,title,body,owner,workspace,visibility,collection,tags) SELECT id,version,title,body,owner,workspace,visibility,collection,tags FROM docs WHERE id=?''', (doc_id,))
        self.db.commit()

    def source(self, actor, doc_id, version=None):
        self.positive(doc_id)
        # Current permissions gate every historical version. Revoking sharing
        # revokes historical access too; a version never resurrects permissions.
        current = next((d for d in self.visible(actor) if d['id'] == doc_id), None)
        if current is None:
            raise ValueError('Source unavailable.')
        if version is None:
            return dict(current)
        self.positive(version, 'Version')
        row = self.db.execute('SELECT * FROM versions WHERE doc=? AND version=?', (doc_id, version)).fetchone()
        if not row or (row['visibility'] == 'private' and row['owner'] != actor):
            raise ValueError('Source version unavailable.')
        return dict(row)

    def history(self, actor, doc_id):
        self.source(actor, doc_id)
        return [dict(r) for r in self.db.execute("SELECT version,title,created FROM versions WHERE doc=? AND (visibility='workspace' OR owner=?) ORDER BY version DESC", (doc_id, actor))]

    def trash(self, actor):
        return [dict(r) for r in self.db.execute('SELECT id,title,version FROM docs WHERE deleted=1 AND owner=? AND workspace=? ORDER BY id DESC', (actor, self.persona(actor)['workspace']))]

    def restore(self, actor, doc_id):
        row = self.owned(actor, doc_id)
        if not row['deleted']:
            raise ValueError('Source is not in trash.')
        self.db.execute('UPDATE docs SET deleted=0 WHERE id=?', (doc_id,))
        self.reindex()
        self.log(actor, 'restored', 'Document ' + str(doc_id))
        return {}

    @staticmethod
    def metadata(data):
        collection = data.get('collection', '')
        tags = data.get('tags', [])
        if not isinstance(collection, str) or len(collection) > 60:
            raise ValueError('Collection must be text up to 60 characters.')
        if not isinstance(tags, list) or len(tags) > 12 or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 30 for t in tags):
            raise ValueError('Use at most 12 text tags of 1–30 characters.')
        return collection.strip(), sorted(set(t.strip().lower() for t in tags))

    def set_metadata(self, actor, data):
        row = self.owned(actor, data.get('id'))
        if row['deleted']:
            raise ValueError('Restore the source before editing metadata.')
        collection, tags = self.metadata(data)
        self.db.execute('UPDATE docs SET collection=?,tags=?,version=version+1 WHERE id=?', (collection, json.dumps(tags), row['id']))
        self.snapshot(row['id'])
        self.log(actor, 'metadata', 'Document ' + str(row['id']))
        return {}

    def filtered(self, actor, filters=None):
        filters = {} if filters is None else filters
        if not isinstance(filters, dict) or set(filters) - {'owner', 'visibility', 'collection', 'tag', 'bookmarked'}:
            raise ValueError('Unknown search filter.')
        for key, value in filters.items():
            if key == 'bookmarked':
                if type(value) is not bool:
                    raise ValueError('Bookmark filter must be boolean.')
            elif not isinstance(value, str) or len(value) > 60:
                raise ValueError('Filter values must be bounded text.')
        rows = self.visible(actor)
        for key in ('owner', 'visibility', 'collection'):
            if filters.get(key):
                rows = [r for r in rows if r[key] == filters[key]]
        if filters.get('tag'):
            rows = [r for r in rows if filters['tag'].lower() in json.loads(r['tags'])]
        return rows

    @staticmethod
    def page_bounds(offset, limit):
        if type(offset) is not int or not 0 <= offset <= 100000 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Offset must be 0–100000 and limit 1–50.')

    def library(self, actor, data):
        offset, limit = data.get('offset', 0), data.get('limit', 12)
        self.page_bounds(offset, limit)
        rows = self.filtered(actor, data.get('filters'))
        return {'docs': [dict(r) for r in rows[offset:offset + limit]], 'total': len(rows), 'offset': offset, 'limit': limit}
