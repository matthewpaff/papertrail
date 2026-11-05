import json
from http.server import HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request

from server import Handler, Store


class ArchiveHTTPTests(unittest.TestCase):
    def test_large_valid_unicode_archive_can_be_previewed_and_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            server = HTTPServer(('127.0.0.1', 0), Handler)
            server.store = Store(Path(directory) / 'notes.sqlite3')
            server.sessions = {}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                documents = [
                    {'title': f'Note {index}', 'body': '📌' * 20000,
                     'visibility': 'private', 'collection': 'Research', 'tags': []}
                    for index in range(35)
                ]
                archive = {'format': 'papertrail.documents.v1', 'documents': documents}
                payload = json.dumps({'archive': archive}).encode('utf-8')
                self.assertGreater(len(payload), 8200000)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for path in ('preview-import', 'import-documents'):
                    request = urllib.request.Request(
                        f'http://127.0.0.1:{server.server_port}/api/{path}', data=payload,
                        headers={'Content-Type': 'application/json'})
                    with opener.open(request, timeout=20) as response:
                        result = json.load(response)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(len(result['created']) if path == 'import-documents' else result['create_count'], 35)
                self.assertEqual(server.store.db.execute('SELECT count(*) FROM docs WHERE owner=?', ('alex',)).fetchone()[0], 37)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
                server.store.db.close()


if __name__ == '__main__':
    unittest.main()
