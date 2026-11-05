# Papertrail walkthrough

Run `python server.py` from this repository. No packages are required.

1. Start as Alex and ask about the launch accessibility review. Inspect the exact excerpts and source versions.
2. Switch to Sam. Alex's private reflection is unavailable. Switch to Jules: the workspace corpus changes.
3. Add a private note, search for its distinctive words, edit it, and repeat the search. Delete it and verify future retrieval excludes it.
4. Propose a task. Inspect the proposal and approve it. A local task appears once; replaying the approval is rejected.
5. Inspect the activity log. These are real local demo actions with current UTC timestamps.
6. Optionally enable an already-running local model. Generated answers are unverified: allowed citation IDs do not prove that statements are supported.

## Review evidence

Run `python -m unittest discover -s tests -v`. Tests include a real loopback HTTP server with an isolated temporary database, malformed request handling, cross-site write denial, and the main application path. The GitHub workflow checks Python 3.11 and 3.13 on Linux and Windows; a configured workflow is not evidence that a run has passed.

The interface has been reviewed from source and HTTP responses. An automated visual browser check was unavailable in the development session. These local servers are development demonstrations. See README.md for limits.
