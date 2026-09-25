"""Hash-aware legacy inventory and explicitly approved obsolete deletion."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
def inventory(root):
    root=Path(root).resolve(); rows=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink(): continue
        rows.append({'path': str(path.relative_to(root)), 'sha256': _hash(path), 'bytes': path.stat().st_size, 'classification': 'retained'})
    return {'root': str(root), 'created_at': datetime.now(timezone.utc).isoformat(), 'entries': rows}
def mark_obsolete(report, paths):
    wanted={str(Path(p)) for p in paths}
    for row in report.get('entries', []):
        if row['path'] in wanted: row['classification']='obsolete'
    return report
def delete_approved(report, root, confirm=False):
    if not confirm: raise ValueError('Deletion requires explicit confirmation')
    root=Path(root).resolve(); deleted=[]
    for row in report.get('entries', []):
        if row.get('classification') != 'obsolete': continue
        path=(root / row['path']).resolve()
        if root not in path.parents or path.is_symlink() or not path.is_file(): raise ValueError(f'Unsafe obsolete path: {row["path"]}')
        if _hash(path) != row.get('sha256'): raise ValueError(f'Hash changed since report: {row["path"]}')
        path.unlink(); deleted.append(row['path'])
    return {'deleted': deleted, 'count': len(deleted)}
