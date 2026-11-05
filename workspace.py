"""Scoped workspace operations shared by the HTTP app and local CLI."""
import json
import re
import time
from datetime import date


class Workspace:
    def upgrade(self):
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(docs)')}
        for name, definition in [('deleted', 'INTEGER NOT NULL DEFAULT 0'), ('collection', "TEXT NOT NULL DEFAULT ''"), ('tags', "TEXT NOT NULL DEFAULT '[]'")]:
            if name not in columns:
                self.db.execute('ALTER TABLE docs ADD COLUMN ' + name + ' ' + definition)
        self.db.execute('''CREATE TABLE IF NOT EXISTS versions(doc INTEGER,version INTEGER,title TEXT,body TEXT,owner TEXT,workspace TEXT,visibility TEXT,collection TEXT,tags TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(doc,version))''')
        self.db.execute('CREATE TABLE IF NOT EXISTS bookmarks(actor TEXT, doc INTEGER, PRIMARY KEY(actor,doc))')
        self.db.execute('CREATE TABLE IF NOT EXISTS saved_queries(id INTEGER PRIMARY KEY,actor TEXT,name TEXT,query TEXT,filters TEXT,UNIQUE(actor,name))')
        proposal_columns = {r[1] for r in self.db.execute('PRAGMA table_info(proposals)')}
        if 'expires' not in proposal_columns:
            self.db.execute('ALTER TABLE proposals ADD COLUMN expires INTEGER NOT NULL DEFAULT 0')
        if 'status' not in {r[1] for r in self.db.execute('PRAGMA table_info(tasks)')}:
            self.db.execute("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        for table in ('tasks', 'proposals'):
            if 'due' not in {r[1] for r in self.db.execute('PRAGMA table_info(' + table + ')')}:
                self.db.execute('ALTER TABLE ' + table + " ADD COLUMN due TEXT NOT NULL DEFAULT ''")
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
        if filters.get('bookmarked'):
            bookmarks = {r[0] for r in self.db.execute('SELECT doc FROM bookmarks WHERE actor=?', (actor,))}
            rows = [r for r in rows if r['id'] in bookmarks]
        return rows

    def bookmark(self, actor, data):
        doc = self.source(actor, data.get('id'))
        enabled = data.get('enabled')
        if type(enabled) is not bool:
            raise ValueError('Bookmark enabled must be boolean.')
        if enabled:
            self.db.execute('INSERT OR IGNORE INTO bookmarks VALUES(?,?)', (actor, doc['id']))
        else:
            self.db.execute('DELETE FROM bookmarks WHERE actor=? AND doc=?', (actor, doc['id']))
        self.db.commit()
        return {}

    def bookmarks(self, actor):
        return [d['id'] for d in self.filtered(actor, {'bookmarked': True})]

    def proposal(self, actor, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 100:
            raise ValueError('Invalid proposal token.')
        row = self.db.execute('SELECT * FROM proposals WHERE id=? AND actor=? AND workspace=?', (token, actor, self.persona(actor)['workspace'])).fetchone()
        if not row or row['status'] != 'pending':
            self.log(actor, 'denied', 'Unavailable proposal transition')
            raise ValueError('Proposal unavailable or already resolved.')
        if row['expires'] <= int(time.time()):
            self.db.execute("UPDATE proposals SET status='expired' WHERE id=?", (token,))
            self.log(actor, 'expired', 'Proposal expired')
            raise ValueError('Proposal expired; create a new proposal.')
        return row

    def cancel_proposal(self, actor, token):
        row = self.proposal(actor, token)
        self.db.execute("UPDATE proposals SET status='cancelled' WHERE id=?", (row['id'],))
        self.log(actor, 'cancelled', 'Proposal cancelled')
        return {}

    def task_transition(self, actor, data):
        task_id = self.positive(data.get('id'))
        status = data.get('status')
        if status not in ('open', 'complete'):
            raise ValueError('Task status must be open or complete.')
        row = self.db.execute('SELECT * FROM tasks WHERE id=? AND owner=? AND workspace=?', (task_id, actor, self.persona(actor)['workspace'])).fetchone()
        if not row:
            raise ValueError('Task unavailable.')
        if row['status'] == status:
            raise ValueError('Task already has this status.')
        self.db.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
        self.log(actor, 'task-' + status, 'Task ' + str(task_id))
        return {}

    @staticmethod
    def due_date(value):
        if value == '':
            return value
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Due date must be YYYY-MM-DD or empty.')
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError('Due date is not a valid calendar date.') from None
        return value

    def task_due(self, actor, data):
        task_id = self.positive(data.get('id'))
        due = self.due_date(data.get('due'))
        row = self.db.execute('SELECT id FROM tasks WHERE id=? AND owner=? AND workspace=?', (task_id, actor, self.persona(actor)['workspace'])).fetchone()
        if not row:
            raise ValueError('Task unavailable.')
        self.db.execute('UPDATE tasks SET due=? WHERE id=?', (due, task_id))
        self.log(actor, 'task-due', 'Task ' + str(task_id) + ' due date updated')
        return {}

    def task_list(self, actor, data):
        status = data.get('status', 'all')
        if status not in ('all', 'open', 'complete'):
            raise ValueError('Unknown task status filter.')
        before = self.due_date(data.get('due_before', ''))
        offset, limit = data.get('offset', 0), data.get('limit', 25)
        self.page_bounds(offset, limit)
        rows = self.db.execute('SELECT * FROM tasks WHERE owner=? AND workspace=? ORDER BY (due=""),due,id', (actor, self.persona(actor)['workspace'])).fetchall()
        rows = [r for r in rows if (status == 'all' or r['status'] == status) and (not before or r['due'] and r['due'] <= before)]
        return {'tasks': [dict(r) for r in rows[offset:offset + limit]], 'total': len(rows), 'offset': offset, 'limit': limit}

    def save_query(self, actor, data):
        self.persona(actor)
        name, query = data.get('name'), data.get('query')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            raise ValueError('Saved query needs a name up to 80 characters and text up to 2,000.')
        filters = data.get('filters', {})
        if not isinstance(filters, dict):
            raise ValueError('Saved query filters must be an object.')
        self.filtered(actor, filters)
        count = self.db.execute('SELECT count(*) FROM saved_queries WHERE actor=?', (actor,)).fetchone()[0]
        existing = self.db.execute('SELECT id FROM saved_queries WHERE actor=? AND name=?', (actor, name.strip())).fetchone()
        if count >= 20 and not existing:
            raise ValueError('Keep at most 20 saved queries per persona.')
        self.db.execute('INSERT INTO saved_queries(actor,name,query,filters) VALUES(?,?,?,?) ON CONFLICT(actor,name) DO UPDATE SET query=excluded.query,filters=excluded.filters', (actor, name.strip(), query.strip(), json.dumps(filters, sort_keys=True)))
        self.db.commit()
        return {}

    def saved_queries(self, actor):
        self.persona(actor)
        return [dict(r) for r in self.db.execute('SELECT id,name,query,filters FROM saved_queries WHERE actor=? ORDER BY name,id', (actor,))]

    def delete_query(self, actor, query_id):
        self.positive(query_id)
        cursor = self.db.execute('DELETE FROM saved_queries WHERE id=? AND actor=?', (query_id, actor))
        if not cursor.rowcount:
            raise ValueError('Saved query unavailable.')
        self.db.commit()
        return {}

    def pending_proposals(self, actor):
        now = int(time.time())
        return [dict(r) for r in self.db.execute("SELECT id AS proposal,title,workspace,expires FROM proposals WHERE actor=? AND workspace=? AND status='pending' AND expires>? ORDER BY expires DESC", (actor, self.persona(actor)['workspace'], now))]

    def activity(self, actor, data):
        self.persona(actor)
        action = data.get('action', '')
        if not isinstance(action, str) or len(action) > 40:
            raise ValueError('Activity action must be bounded text.')
        offset, limit = data.get('offset', 0), data.get('limit', 25)
        self.page_bounds(offset, limit)
        condition = 'actor=?'
        args = [actor]
        if action:
            condition += ' AND action=?'
            args.append(action)
        total = self.db.execute('SELECT count(*) FROM audit WHERE ' + condition, args).fetchone()[0]
        rows = self.db.execute('SELECT * FROM audit WHERE ' + condition + ' ORDER BY id DESC LIMIT ? OFFSET ?', args + [limit, offset])
        events = []
        for row in rows:
            event = dict(row)
            # Legacy records may contain a task title. Never export that content.
            if event['action'] in ('proposed', 'executed'):
                event['detail'] = 'Personal task event (content redacted)'
            events.append(event)
        return {'events': events, 'total': total, 'offset': offset, 'limit': limit}

    def export_activity(self, actor, data):
        events = []
        offset = 0
        while len(events) < 1000:
            page = self.activity(actor, {'action': data.get('action', ''), 'offset': offset, 'limit': 50})
            events.extend(page['events'])
            offset += 50
            if offset >= page['total']:
                break
        return {'format': 'papertrail.activity.v1', 'actor': actor, 'events': events, 'truncated': len(events) < page['total']}

    def export_documents(self, actor):
        documents = []
        for row in self.visible(actor):
            if row['owner'] != actor:
                continue
            documents.append({'title': row['title'], 'body': row['body'], 'visibility': row['visibility'], 'collection': row['collection'], 'tags': json.loads(row['tags'])})
        return {'format': 'papertrail.documents.v1', 'documents': documents}

    def validate_archive(self, archive):
        if not isinstance(archive, dict) or set(archive) != {'format', 'documents'} or archive['format'] != 'papertrail.documents.v1':
            raise ValueError('Expected a papertrail.documents.v1 archive.')
        rows = archive['documents']
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Import at most 100 documents at a time.')
        clean = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'title', 'body', 'visibility', 'collection', 'tags'}:
                raise ValueError('Unknown or missing document fields.')
            if not isinstance(row['title'], str) or not 1 <= len(row['title'].strip()) <= 120 or not isinstance(row['body'], str) or not 1 <= len(row['body'].strip()) <= 20000:
                raise ValueError('Imported title or body is invalid.')
            if row['visibility'] not in ('private', 'workspace'):
                raise ValueError('Imported visibility is invalid.')
            collection, tags = self.metadata(row)
            clean.append((row['title'].strip(), row['body'].strip(), row['visibility'], collection, json.dumps(tags)))
        return clean

    def import_documents(self, actor, archive):
        workspace = self.persona(actor)['workspace']
        clean = self.validate_archive(archive)
        existing = {(r['title'], r['body'], r['visibility'], r['collection'], r['tags']) for r in self.visible(actor) if r['owner'] == actor}
        created, skipped = [], 0
        with self.db:
            for row in clean:
                if row in existing:
                    skipped += 1
                    continue
                title, body, visibility, collection, tags = row
                cursor = self.db.execute('INSERT INTO docs(title,body,visibility,collection,tags,owner,workspace) VALUES(?,?,?,?,?,?,?)', (title, body, visibility, collection, tags, actor, workspace))
                doc_id = cursor.lastrowid
                self.db.execute('''INSERT INTO versions(doc,version,title,body,owner,workspace,visibility,collection,tags) SELECT id,version,title,body,owner,workspace,visibility,collection,tags FROM docs WHERE id=?''', (doc_id,))
                created.append(doc_id)
                existing.add(row)
        self.reindex()
        self.log(actor, 'imported', str(len(created)) + ' sources imported; ' + str(skipped) + ' duplicates skipped')
        return {'created': created, 'skipped': skipped}

    def preview_import(self, actor, archive):
        self.persona(actor)
        rows = self.validate_archive(archive)
        existing = {(r['title'], r['body'], r['visibility'], r['collection'], r['tags']) for r in self.visible(actor) if r['owner'] == actor}
        entries = []
        for row in rows:
            duplicate = row in existing
            entries.append({'title': row[0], 'visibility': row[2], 'duplicate': duplicate})
            existing.add(row)
        return {'entries': entries, 'create_count': sum(not e['duplicate'] for e in entries), 'skip_count': sum(e['duplicate'] for e in entries)}

    def collections(self, actor):
        counts = {}
        for row in self.visible(actor):
            if row['owner'] == actor and row['collection']:
                counts[row['collection']] = counts.get(row['collection'], 0) + 1
        return [{'name': key, 'count': counts[key]} for key in sorted(counts)]

    def rename_collection(self, actor, data):
        source, target = data.get('source'), data.get('target')
        if not isinstance(source, str) or not 1 <= len(source) <= 60 or not isinstance(target, str) or len(target) > 60 or source == target.strip():
            raise ValueError('Choose distinct collection names up to 60 characters.')
        if type(data.get('merge', False)) is not bool:
            raise ValueError('Merge option must be boolean.')
        target = target.strip()
        names = {c['name'] for c in self.collections(actor)}
        if source not in names or (target in names and not data.get('merge')):
            raise ValueError('Source unavailable or target already exists; explicitly allow a merge.')
        rows = [r for r in self.visible(actor) if r['owner'] == actor and r['collection'] == source]
        with self.db:
            for row in rows:
                self.db.execute('UPDATE docs SET collection=?,version=version+1 WHERE id=?', (target, row['id']))
                self.db.execute('''INSERT INTO versions(doc,version,title,body,owner,workspace,visibility,collection,tags) SELECT id,version,title,body,owner,workspace,visibility,collection,tags FROM docs WHERE id=?''', (row['id'],))
        self.log(actor, 'collection-renamed', str(len(rows)) + ' owned sources updated')
        return {'updated': len(rows)}

    def restore_revision(self, actor, data):
        current = self.owned(actor, data.get('id'))
        if current['deleted']:
            raise ValueError('Restore the source from trash first.')
        old = self.source(actor, current['id'], data.get('version'))
        if old['version'] == current['version']:
            raise ValueError('This revision is already current.')
        # Retain current sharing when restoring old content to avoid accidental
        # publication of a previously shared historical visibility setting.
        self.db.execute('UPDATE docs SET title=?,body=?,collection=?,tags=?,version=version+1 WHERE id=?', (old['title'], old['body'], old['collection'], old['tags'], current['id']))
        self.snapshot(current['id'])
        self.reindex()
        self.log(actor, 'revision-restored', 'Document ' + str(current['id']) + ' from version ' + str(old['version']))
        return {'version': current['version'] + 1}

    @staticmethod
    def page_bounds(offset, limit):
        if type(offset) is not int or not 0 <= offset <= 100000 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Offset must be 0–100000 and limit 1–50.')

    def library(self, actor, data):
        offset, limit = data.get('offset', 0), data.get('limit', 12)
        self.page_bounds(offset, limit)
        rows = self.filtered(actor, data.get('filters'))
        return {'docs': [dict(r) for r in rows[offset:offset + limit]], 'total': len(rows), 'offset': offset, 'limit': limit}

    def search(self, actor, data):
        query = data.get('query', '')
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('Question must be text up to 2,000 characters.')
        offset, limit = data.get('offset', 0), data.get('limit', 12)
        self.page_bounds(offset, limit)
        allowed = self.filtered(actor, data.get('filters'))
        terms = list(dict.fromkeys(re.findall(r'[a-zA-Z0-9]{2,}', query.lower())))[:24]
        stop = {'the', 'what', 'when', 'where', 'who', 'does', 'about', 'are', 'and', 'for', 'with', 'can', 'how', 'was', 'this', 'that', 'is', 'my'}
        terms = [t for t in terms if t not in stop]
        phrases = [p.lower().strip() for p in re.findall(r'"([^"\n]+)"', query) if p.strip()]
        candidates = {d['id'] for d in allowed}
        if self.fts and terms:
            self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS temp.allowed_search USING fts5(title,body)')
            self.db.execute('DELETE FROM temp.allowed_search')
            self.db.executemany('INSERT INTO temp.allowed_search(rowid,title,body) VALUES(?,?,?)', [(d['id'], d['title'], d['body']) for d in allowed])
            match = ' OR '.join('"' + t + '"' for t in terms)
            candidates = {r[0] for r in self.db.execute('SELECT rowid FROM temp.allowed_search WHERE allowed_search MATCH ?', (match,))}
        ranked = []
        for doc in allowed:
            full = (doc['title'] + ' ' + doc['body']).lower()
            if not terms or doc['id'] not in candidates or any(p not in full for p in phrases):
                continue
            title_score = 3 * len(set(re.findall(r'\w+', doc['title'].lower())).intersection(terms))
            sentences = re.split(r'(?<=[.!?])\s+|\n+', doc['body'])
            scored = [(len(set(re.findall(r'\w+', s.lower())).intersection(terms)), -i, s) for i, s in enumerate(sentences)]
            best = max(scored)
            score = title_score + best[0] + 5 * len(phrases)
            if score:
                ranked.append({'id': doc['id'], 'version': doc['version'], 'title': doc['title'], 'snippet': best[2], 'score': score, 'collection': doc['collection'], 'tags': json.loads(doc['tags'])})
        ranked.sort(key=lambda d: (-d['score'], d['id']))
        return {'sources': ranked[offset:offset + limit], 'total': len(ranked), 'offset': offset, 'limit': limit}
