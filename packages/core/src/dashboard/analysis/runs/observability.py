"""Run artifact indexing for the local dashboard."""
import json
from datetime import datetime, timezone

from ... import files


def artifacts(run_dir):
    """Return immutable run files, excluding transient lock/cache files."""
    # One parse per directory for the whole walk: every file under a directory reads the same
    # `analysis-metadata.json`, and re-parsing it once per file is what made the refresh linear in files.
    parsed = {}

    def metadata_for(path):
        for parent in (path.parent, *path.parents):
            if parent == run_dir.parent:
                break
            candidate = parent / 'analysis-metadata.json'
            if not candidate.is_file() or candidate == path:
                continue
            if parent not in parsed:
                try:
                    parsed[parent] = json.loads(candidate.read_text())
                except (OSError, ValueError):
                    parsed[parent] = None
            payload = parsed[parent]
            if isinstance(payload, dict):
                return payload
        return None

    entries = []
    if not run_dir.is_dir():
        return entries
    for path in files.safe_files(run_dir):
        if not path.is_file() or path.name.endswith(('.tmp', '.lock')):
            continue
        stat = path.stat()
        entry = {'path': str(path.relative_to(run_dir)), 'bytes': stat.st_size,
                 'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
        metadata = metadata_for(path)
        if metadata is not None:
            entry['metadata'] = metadata
        entries.append(entry)
    return entries



