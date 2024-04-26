"""Explicit request field contracts; authorization remains inside Store."""
FIELDS = {
    'identity': {'actor'}, 'ask': {'query', 'model'},
    'save': {'id', 'title', 'body', 'visibility', 'collection', 'tags'},
    'delete': {'id'}, 'restore': {'id'}, 'source': {'id', 'version'},
    'history': {'id'}, 'trash': set(), 'metadata': {'id', 'collection', 'tags'},
    'library': {'offset', 'limit', 'filters'},
    'search': {'query', 'offset', 'limit', 'filters'},
    'bookmark': {'id', 'enabled'}, 'bookmarks': set(),
    'propose': {'title', 'workspace'}, 'approve': {'proposal'},
    'cancel-proposal': {'proposal'}, 'pending-proposals': set(),
    'task-status': {'id', 'status'}, 'activity': {'action', 'offset', 'limit'},
    'export-activity': {'action'}, 'export-documents': set(),
    'import-documents': {'archive'},
}


def validate(action, data):
    if action not in FIELDS:
        raise ValueError('Unknown API action.')
    if not isinstance(data, dict) or set(data) - FIELDS[action]:
        raise ValueError('Unknown request fields.')
