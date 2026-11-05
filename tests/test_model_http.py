from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from server import Store


class FakeModel(BaseHTTPRequestHandler):
    requests = []
    unsupported = False

    def do_POST(self):
        self.__class__.requests.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        evidence = json.loads(self.__class__.requests[-1][1]['messages'][1]['content'])['sources'][0]
        citations = [{'id': 999999, 'version': 1}] if self.__class__.unsupported else [{'id': evidence['id'], 'version': evidence['version']}]
        content = {'answer': 'The launch gate is an accessibility review.', 'citations': citations, 'abstained': False}
        body = json.dumps({'message': {'content': json.dumps(content)}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class LocalModelHTTPTests(unittest.TestCase):
    def test_transport_sends_only_visible_sources_and_rejects_foreign_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            server = HTTPServer(('127.0.0.1', 0), FakeModel)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            FakeModel.requests = []
            FakeModel.unsupported = False
            store = Store(Path(directory) / 'notes.sqlite3', model='test-model', endpoint=f'http://127.0.0.1:{server.server_port}')
            try:
                result = store.ask('sam', 'launch accessibility', use_model=True)
                self.assertEqual(result['model_status'], 'unverified')
                self.assertEqual(len(FakeModel.requests), 1)
                path, payload = FakeModel.requests[0]
                self.assertEqual(path, '/api/chat')
                self.assertEqual(payload['model'], 'test-model')
                self.assertFalse(payload['stream'])
                self.assertEqual(payload['format'], 'json')
                forwarded = json.loads(payload['messages'][1]['content'])['sources']
                self.assertFalse(any(source['title'] == 'Private reflection' for source in forwarded))
                FakeModel.unsupported = True
                rejected = store.ask('sam', 'launch accessibility', use_model=True)
                self.assertTrue(rejected['abstained'])
                self.assertEqual(rejected['model_status'], 'rejected')
            finally:
                store.db.close()
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == '__main__':
    unittest.main()
