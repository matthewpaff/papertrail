"""Read-only operator CLI; identity is an explicit selectable demo persona."""
import argparse
import json
import sqlite3
from pathlib import Path
from server import Store, PERSONAS, ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(ROOT / 'papertrail.sqlite3'))
    parser.add_argument('--actor', required=True, choices=sorted(PERSONAS))
    commands = parser.add_subparsers(dest='command', required=True)
    query = commands.add_parser('query')
    query.add_argument('text')
    query.add_argument('--limit', type=int, default=10)
    commands.add_parser('export')
    args = parser.parse_args(argv)
    store = Store.__new__(Store)
    store.db = sqlite3.connect(Path(args.db).resolve().as_uri() + '?mode=ro', uri=True)
    store.db.row_factory = sqlite3.Row
    store.fts = False  # read-only CLI uses the deterministic fallback ranker
    try:
        result = store.search(args.actor, {'query': args.text, 'limit': args.limit}) if args.command == 'query' else store.export_documents(args.actor)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        store.db.close()


if __name__ == '__main__':
    main()
