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
