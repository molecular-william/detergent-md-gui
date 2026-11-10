"""Named stage-setting presets: one JSON store per workspace, keyed by run type.

A preset is a run type's stage settings saved under a name a reader recognises ("Lactose CG standard"),
plus at most one of them set as that run type's default. The scope is the workspace: this dashboard has
no user identity, so a preset is saved and read by everyone who opens it.

The queue keeps only the keys its adapter advertises (`web/routes/runs.py`), so a preset carrying any
other key would be a value the run silently drops. A preset refuses it instead: every supplied key is
checked against the run type's own `settings_specs()`/`choice_specs()`, and the stored settings are the
adapter's `normalize_settings` answer -- the same numbers the run itself would record.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import files
from ..execution import protocol

FILE = 'setting-presets.json'
"""The store's file name, under the workspace root (the same place the Modules setting lives)."""

MAX_NAME = 120

_log = logging.getLogger(__name__)


class DuplicatePreset(ValueError):
    """A run type already has a preset under that name."""


class UnknownPreset(ValueError):
    """No preset in this workspace carries that id."""


class UnknownRunType(ValueError):
    """The named run type is not one this installation can run."""


def _path(paths) -> Path:
    return Path(paths.workspace) / FILE


def _empty() -> dict:
    return {'presets': [], 'defaults': {}}


def _adapter(run_type):
    """The adapter a preset's run type names, or `UnknownRunType`.

    An unknown name is refused here rather than stored: a preset for a run type nothing can run is a
    preference that can never be applied.
    """
    if not isinstance(run_type, str) or not run_type:
        raise UnknownRunType('run_type is required')
    try:
        return protocol.adapter_for(run_type)
    except ValueError as error:
        raise UnknownRunType(str(error)) from error


def load(paths) -> dict:
    """The workspace's preset document; a missing or unreadable file is an empty one.

    Same rule as the Modules setting (`web.sections.enabled`): a broken preference file must not take the
    form down. The warning is why it is ignored rather than silently replaced; the next save rewrites it.
    """
    path = _path(paths)
    if not path.is_file():
        return _empty()
    try:
        payload = json.loads(path.read_text())
        presets, defaults = payload['presets'], payload['defaults']
        if not isinstance(presets, list) or not isinstance(defaults, dict):
            raise ValueError('"presets" must be a list and "defaults" an object')
    except (OSError, ValueError, KeyError, TypeError) as error:
        _log.warning('ignoring unreadable %s (%s); no preset is offered', path, error)
        return _empty()
    return {'presets': [item for item in presets if isinstance(item, dict)],
            'defaults': {key: value for key, value in defaults.items() if isinstance(value, str)}}


def save(paths, document) -> None:
    """Replace the workspace's preset file atomically, so a reader sees the old document or the new one."""
    files.atomic_json(_path(paths), document)


def normalize_settings(run_type, settings=None) -> dict:
    """One preset's settings, refused and completed by the adapter that owns them.

    Every supplied key must be advertised by the run type: `CG_FIELDS` posted for an `aa_only` run is the
    mistake this catches, because the queue would drop those values without a word and the run would use
    its defaults. The answer is `normalize_settings`, so a stored preset is exactly what a run would use.
    """
    adapter = _adapter(run_type)
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError('Preset settings must be an object')
    advertised = set(adapter.settings_specs()) | set(adapter.choice_specs())
    unknown = sorted(set(settings) - advertised)
    if unknown:
        raise ValueError(f'Unknown setting(s) for {run_type}: ' + ', '.join(unknown))
    return dict(adapter.normalize_settings(settings, protocol.profile_for_run_type(run_type)))


def for_run_type(paths, run_type) -> dict:
    """The presets of one run type, each marked `is_default`, and which id is that type's default.

    `default` is `None` when nothing is chosen *or* when the chosen id is no longer in the store (a
    hand-edited file, a preset deleted outside this module): a default that names nothing is no default.
    """
    _adapter(run_type)
    document = load(paths)
    chosen = document['defaults'].get(run_type)
    presets = [dict(preset, is_default=preset.get('id') == chosen)
               for preset in document['presets'] if preset.get('run_type') == run_type]
    default = chosen if any(preset['id'] == chosen for preset in presets) else None
    return {'presets': presets, 'default': default}


def _name(name) -> str:
    """A preset name, trimmed and single-spaced; a name is required."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError('A preset needs a name')
    return ' '.join(name.split())[:MAX_NAME]


def create(paths, *, name, run_type, settings=None) -> dict:
    """Store one preset; a duplicate name within the run type is refused, naming the preset that holds it."""
    _adapter(run_type)
    chosen = _name(name)
    values = normalize_settings(run_type, settings)
    document = load(paths)
    _refuse_duplicate(document, run_type, chosen)
    record = {'id': uuid.uuid4().hex[:12], 'name': chosen, 'run_type': run_type, 'settings': values,
              'created_at': datetime.now(timezone.utc).isoformat()}
    document['presets'].append(record)
    save(paths, document)
    return record


def update(paths, preset_id, *, name=None, is_default=None) -> tuple[dict, dict]:
    """Rename a preset and/or move its run type's default marker; returns the preset and every default.

    A rename is held to the same duplicate rule as a save, so two presets of one run type cannot end up
    with the same name by way of an update.
    """
    document = load(paths)
    record = _find(document, preset_id)
    run_type = record.get('run_type')
    _adapter(run_type)
    if name is not None:
        chosen = _name(name)
        _refuse_duplicate(document, run_type, chosen, ignore=record)
        record['name'] = chosen
    if is_default is not None:
        if is_default:
            document['defaults'][run_type] = record['id']
        elif document['defaults'].get(run_type) == record['id']:
            document['defaults'].pop(run_type)
    save(paths, document)
    return record, dict(document['defaults'])


def delete(paths, preset_id) -> str:
    """Remove one preset; a default that named it is cleared with it."""
    document = load(paths)
    record = _find(document, preset_id)
    document['presets'].remove(record)
    run_type = record.get('run_type')
    if document['defaults'].get(run_type) == record['id']:
        document['defaults'].pop(run_type)
    save(paths, document)
    return record['id']


def _find(document, preset_id) -> dict:
    for record in document['presets']:
        if record.get('id') == preset_id:
            return record
    raise UnknownPreset(f'No preset has the id {preset_id!r}')


def _refuse_duplicate(document, run_type, name, ignore=None):
    """Raise `DuplicatePreset` naming the existing preset, so the reader knows which one already has the name."""
    for preset in document['presets']:
        if preset is not ignore and preset.get('run_type') == run_type and _same_name(preset.get('name'), name):
            raise DuplicatePreset(f'A preset named {preset.get("name")!r} already exists for {run_type}')


def _same_name(left, right) -> bool:
    """Names compare without case or surrounding space: "CG standard" and "cg standard" are one name."""
    return isinstance(left, str) and left.strip().casefold() == str(right).strip().casefold()
