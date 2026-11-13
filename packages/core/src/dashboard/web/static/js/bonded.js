/**
 * CG Bond Interactions: two comparison panes, each a whole model workspace, and the panel they share.
 *
 * The panel is a host plus a per-pane factory. The host finds `.bonded-column[data-side]`, builds one workspace for
 * each from the same code, and owns the things that belong to the panel rather than to a model: the global status
 * message, the hidden `#bonded-mapping-select` bridge the New run door drives (pane A only), and the second pane's
 * Minimize / Expand. `bonded-parameterization.js` owns each pane's record state and the panel's one fit card; this
 * module owns each pane's molecule and parameterization selectors, the bead geometry, the interactions table and the
 * terms save.
 *
 * Every pane id is the bare id with a suffix: pane A keeps the ids the rest of the dashboard and the browser tier
 * already address, and pane B's are the same with `-B`. `id(name)` is the only place that scheme lives, so a control
 * added to the macro is reachable in both panes by construction.
 *
 * The selector is display-only. Its options are the chosen molecule's saved mappings grouped by mapping -- each
 * mapping's revisions, or its draft connectivity when it has none -- plus the published reference when the route
 * offers one. Choosing an option reads that mapping's parameterization and shows the chosen revision; it never
 * changes the revision a run consumes, which is the pane's separate **Make current** action.
 *
 * The table edits *parameters*, not the model: the function form and a virtual site's parents are readings. A bond's
 * length+force, an angle's angle+force, a dihedral's phase+force(+multiplicity) and a rigid constraint's length are
 * inputs, and **Save in place** (the current revision, and only when the server's edit gate allows it) or **Save as
 * new** (a clone appended and made current) writes them through `parameterization.saveTerms`. A published Martini 3
 * reference is never an input: a CG run consumes it directly, so its rows are readings and both buttons are disabled
 * with the server's reason. The `source` column stays the store's reading -- an edited term reads `manual`.
 */
import { $, $$, setText, cachedApi, fillMoleculeOptions, api, invalidateResource, CATALOGUE_MAX_AGE, storage } from './shared.js';
import { mountBondedPlot } from './bonded-plot.js';
import { setupPane, setupFitCard, parseTopology, REFERENCE_REASON } from './bonded-parameterization.js';

const FUNCTION_OPTIONS = {
  // A rigid constraint has a length and no potential; the row is editable so the length can be changed, and the
  // store records that as a hand edit over the mapping's ring target.
  constraints: {1: {description: 'Rigid constraint', labels: ['length (nm)']}},
  bonds: {1: {description: 'Harmonic', labels: ['length (nm)', 'force (kJ mol^-1 nm^-2)']}},
  angles: {
    1: {description: 'Harmonic', labels: ['angle (deg)', 'force (kJ mol^-1 rad^-2)']},
    2: {description: 'GROMOS-96 cosine', labels: ['angle (deg)', 'force (kJ mol^-1)']},
    10: {description: 'Restricted bending', labels: ['angle (deg)', 'force (kJ mol^-1)']},
  },
  dihedrals: {
    1: {description: 'Proper periodic', labels: ['phase (deg)', 'force (kJ mol^-1)', 'multiplicity']},
    2: {description: 'Improper harmonic', labels: ['phase (deg)', 'force (kJ mol^-1 rad^-2)']},
    9: {description: 'Proper periodic multi-term', labels: ['phase (deg)', 'force (kJ mol^-1)', 'multiplicity']},
  },
};

/** The molecule select's group for CG compositions: not a molecule, so it cannot come from `/api/molecules`. */
const COMPOSITIONS = '__compositions__';
/** Where the second pane's collapsed state is remembered, in `localStorage` under `ddm.bonded.state`. */
const STATE_KEY = 'bonded.state';

const formatNumber = value => Number.isFinite(Number(value)) ? Number(value).toString() : '';
const date = iso => (typeof iso === 'string' ? iso.slice(0, 10) : '');

/** A display option's value: a revision of a saved mapping, or a model that carries no revision. */
function optionValue(file, revision) {
  return revision === null || revision === undefined ? `draft:${file}` : `revision:${file}:${revision}`;
}

/** The mapping file and the revision (or `null`) an option value names. */
function optionTarget(value) {
  const text = String(value || '');
  if (text.startsWith('revision:')) {
    const rest = text.slice('revision:'.length);
    const cut = rest.lastIndexOf(':');
    const revision = Number(rest.slice(cut + 1));
    return {file: rest.slice(0, cut), revision: Number.isInteger(revision) ? revision : null};
  }
  return {file: text.startsWith('draft:') ? text.slice('draft:'.length) : text, revision: null};
}

function optionsFor(kind) {
  return Object.entries(FUNCTION_OPTIONS[kind] || {}).map(([value, spec]) => ({
    value, label: `Function ${value}`, description: spec.description, labels: spec.labels,
  }));
}

function normalizeTerm(term, fallbackId) {
  const kind = term.kind || 'bonds';
  const functionValue = String(term.function || '1');
  const options = term.function_options?.length ? term.function_options.map(option => ({
    value: String(option.value), label: option.label, description: option.description || '', labels: option.parameter_labels || [],
  })) : optionsFor(kind);
  const selected = options.find(option => option.value === functionValue) || options[0];
  const spec = (FUNCTION_OPTIONS[kind] || {})[functionValue];
  return {...term, id: term.id || fallbackId, kind, beads: [...(term.beads || [])],
    function: functionValue, parameters: [...(term.parameters || [])],
    // A row is editable when its function has a known parameter list *and* the stored line carries exactly that
    // many values; `mappingTerms` passes false because a draft connectivity is not a stored revision. A mismatched
    // row is a reading: offering inputs the store's validator would refuse is a control that cannot act.
    editable: term.editable ?? !!(spec && term.parameters?.length === spec.labels.length),
    function_options: options, source: term.source || 'unrecorded',
    parameter_labels: term.parameter_labels?.length ? [...term.parameter_labels] : [...(selected?.labels || [])]};
}

/** `Function 10 — Restricted bending`, or the section's own answer where it has no potential. */
function functionSentence(term) {
  // A constraint has a length but no potential; say so rather than printing the editable-row spec's name.
  if (term.kind === 'constraints') return '1 — rigid constraint, no potential';
  const spec = FUNCTION_OPTIONS[term.kind]?.[term.function];
  if (spec) return `${term.function} — ${spec.description}`;
  if (term.kind === 'virtual_sitesn') return `${term.function} — virtual site`;
  return term.function || '—';
}

/** The parameters in their own units, taken from the function's label list where it has one. */
function parameterSentence(term) {
  if (term.kind === 'virtual_sitesn') {
    return (term.parents || []).length ? `parents ${term.parents.join(' · ')}` : 'no parents recorded';
  }
  const labels = term.parameter_labels || [];
  if (!term.parameters.length) return '—';
  const parts = term.parameters.map((value, index) => {
    if (term.kind === 'constraints' && index === 0) return `${value} nm`;
    return labels[index] ? `${value} ${labels[index].replace(/^.*\((.*)\)$/, '$1')}` : String(value);
  });
  return parts.join(' · ');
}

export function setupBondedWorkspace(mappingData, {loadMapping}) {
  const host = $('.bonded-workspace');
  if (!host || !mappingData) return;
  const message = $('.bonded-panel-message', host);
  const columnsWrap = $('.bonded-columns', host);
  const bridgeSelect = $('#bonded-mapping-select', host);
  const minimizeButton = $('#bonded-minimize-B', host);
  const columns = $$('.bonded-column[data-side]', host);
  const bySide = new Map(columns.map(root => [root.dataset.side, root]));
  const panes = [];
  let fitCard = null;
  //: The mapping the New run door asked pane A to show. A cold load mounts the panel while the door is still waiting
  //: for its option, so the request is re-applied once the pane's own first load has finished (see `mount`).
  let doorTarget = '';
  //: Only the second pane minimises; its remembered state is per side, so a saved layout survives a reload.
  let minimized = {B: false};

  /** The panel's one status line. A pane's clear only clears its own sentence, so two panes cannot erase each other. */
  function notice(text, side = 'A') {
    if (text) {
      setText(message, side === 'A' ? text : `Model ${side}: ${text}`);
      message.dataset.side = side;
    } else if (message.dataset.side === side) {
      setText(message, '');
      delete message.dataset.side;
    }
  }

  // --- the panes --------------------------------------------------------------------------------------------------

  function createPane(root, side) {
    const suffix = side === 'A' ? '' : `-${side}`;
    const id = name => root.querySelector('#' + name + suffix);
    const moleculeSelect = id('bonded-molecule-select');
    const displaySelect = id('bonded-parameterization-display');
    //: The hidden bridge the New run door drives: `new-run.js` preselects a saved mapping by setting its value and
    //: dispatching `change`. It addresses pane A, and carries no state of its own.
    //: ponytail: kept because `new-run.js` and three test modules outside this lane address it; delete it with them.
    const paneBridge = side === 'A' ? bridgeSelect : null;
    const deleteButton = id('bonded-delete-parameterization');
    const tableHost = $('.bonded-interaction-table', root);
    const selectionStatus = $('.bonded-selection-status', root);
    const saveInPlace = id('bonded-save-terms-inplace');
    const saveNew = id('bonded-save-terms-new');
    const termsStatus = id('bonded-terms-status');
    const plot = mountBondedPlot($('.bonded-plot', root), {
      uirevision: `bonded-${side}`,
      onBeadSelection: selected => { selectedBeads = selected; renderState(); },
      onTermSelection: termId => { selectedTermId = termId; renderState(); },
      onPlotError: text => notice(text, side),
    });
    let selectedMapping = null;
    let candidates = [];
    let reference = null;
    //: Each saved mapping's own parameterization record, read to label its options: the display selector has to name
    //: every mapping's revisions, not only the shown mapping's.
    let modelRecords = new Map();
    let structure = null;
    let geometryNotice = '';
    let terms = [];
    let selectedBeads = [];
    let selectedTermId = '';
    //: Unsaved parameter values by term id, `{values: string[]}`. A map, not a flag, because every
    //: table re-render (a bead or row selection) must keep what the reader typed. Cleared when the shown terms key
    //: changes (a selector/molecule switch) or after a successful save.
    let pending = new Map();
    //: What the shown terms are: file + revision + digest, or the reference. It is how a background record re-read of
    //: the same revision keeps typed values while a switch discards them (the status says so; no dialog).
    let termsKey = '';
    //: A server refusal or a save sentence, held until the next edit or model switch. The base sentence otherwise.
    let pinnedStatus = null;
    let saving = false;
    let generation = 0;
    let optionsGeneration = 0;

    const parameterization = setupPane({
      root, suffix,
      fitBusy: file => (fitCard ? fitCard.isFitting(file) : false),
      onChanged: change => reloadPanes(change, pane),
      onTerms: revisionTerms => {
        // `null` is the mapping's own draft: a model with no revision still shows the connectivity its mapping
        // declares, and every row of it says where it came from rather than being presented as a fitted term.
        // A published reference is different in kind: its terms are the ITP it transcribed, marked as that reading,
        // and read-only -- a CG run consumes it directly.
        const shown = parameterization.shownRevision();
        // The server's `parameters_editable` is the one rule: a transcribed revision is read-only in the table, not
        // merely unsaveable, so its rows are readings like the published reference's.
        const editable = !shown || shown.parameters_editable !== false;
        const rows = selectedMapping?.read_only ? referenceTerms(selectedMapping)
          : revisionTerms ? revisionTerms.map(row => normalizeTerm(editable ? row : {...row, editable: false}, row.id))
            : (structure ? mappingTerms(selectedMapping || {}) : []);
        const key = selectedMapping?.read_only
          ? `reference:${selectedMapping.file || ''}`
          : `${selectedMapping?.file || ''}:${shown ? `${shown.revision}:${shown.sha256 || ''}` : 'draft'}`;
        // A selector/molecule switch changes the key and discards typed values with a sentence; a background re-read
        // of the same revision (a fit finishing, another pane saving) keeps them. No dialog.
        if (key !== termsKey) {
          // One switch can produce two `onTerms` calls (the null draft answer, then the record's); the notice must
          // survive both, so it is marked and only a new edit/save replaces it. A switch with nothing pending clears
          // an older message.
          if (pending.size) pinnedStatus = {text: 'Unsaved parameter changes were discarded.', kind: 'warn', discarded: true};
          else if (!pinnedStatus || !pinnedStatus.discarded) pinnedStatus = null;
          pending.clear();
          termsKey = key;
        }
        terms = rows;
        renderState();
      },
      // A record the pane re-read (a fit finished, a revision became current, a parameterization was deleted)
      // relabels the selector's options: they state which revision is current, and a new one must appear there.
      onRecord: record => {
        if (record?.mapping?.file) modelRecords.set(record.mapping.file, record);
        fillDisplay();
        syncDisplay();
        fillBridge();
      },
    });

    /** Whether the shown model is a saved mapping whose parameterization this pane may delete. */
    function deletable() {
      return !!(selectedMapping && !selectedMapping.read_only
        && !String(selectedMapping.file || '').startsWith('composition:'));
    }

    function updateDelete() {
      if (!deleteButton) return;
      const file = selectedMapping?.file || '';
      const held = parameterization.revisionCount();
      const allowed = deletable() && held > 0;
      deleteButton.disabled = !allowed;
      deleteButton.title = selectedMapping?.read_only
        ? 'The published reference carries no parameterization to delete.'
        : file.startsWith('composition:')
          ? 'A CG composition carries no parameterization to delete.'
          : !deletable() ? 'Choose a saved mapping first.'
          : held ? `Delete the parameterization of ${file}: ${held === 1 ? 'its single revision' : `its ${held} revisions`}`
          : 'This model has no parameterization to delete.';
    }

    /** Delete the selected model's parameterization, and say what went with it.
     *
     * The saved mapping is not this control's to delete: the pane reads models and the editor owns the catalogue, so
     * what goes is what this pane is about -- the revisions, the fits that produced them, the frames those fits built
     * and the reference histograms recorded with them. The warning says exactly that, because the reader's only
     * protection before an irreversible click is the truth about what the click removes. Runs that already recorded a
     * revision keep their own copy, which is what makes it safe to offer here at all.
     */
    async function deleteParameterization() {
      const file = selectedMapping?.file || '';
      if (!deletable()) return notice('No saved mapping is selected.', side);
      const count = parameterization.revisionCount();
      if (!count) return notice('This model has no parameterization to delete.', side);
      if (parameterization.isBusy()) {
        return notice('A fit of this model is running: cancel it before deleting the parameterization.', side);
      }
      const hash = parameterization.contentHash();
      if (!hash) return notice('This model has no parameterization to delete.', side);
      // The revision *number*, not the revision: the route compares it against the record it is about to remove.
      const current = parameterization.currentRevisionNumber();
      const holds = count === 1 ? 'Its single bond interaction revision goes with it'
        : `Its ${count} bond interaction revisions go with it`;
      const agreed = window.confirm(
        `Delete the parameterization of ${file}?\n\n${holds}, along with the fit jobs and staged frames built for `
        + 'them, and the reference histograms they recorded. The saved mapping itself is not touched.\n\n'
        + 'Runs that already recorded these terms keep their own copy.');
      if (!agreed) return;
      let answer;
      try {
        answer = await api('/api/bonded-parameterizations/' + encodeURIComponent(hash), {
          method: 'DELETE', headers: {'Content-Type': 'application/json'},
          // The revision the pane was showing: a record that moved on since answers 409 instead of losing newer work.
          body: JSON.stringify({confirm: true, revision: current}),
        });
      } catch (error) {
        return notice(`The parameterization was not deleted: ${error.message}`, side);
      }
      const removed = (answer && answer.revisions) || [];
      const jobs = (answer && answer.jobs) || [];
      const fate = removed.length
        ? `${removed.length === 1 ? 'its single bond interaction revision' : `its ${removed.length} bond interaction revisions`} went`
        : 'it held no revisions';
      const built = jobs.length ? ` and ${jobs.length === 1 ? 'the fit that built it' : `the ${jobs.length} fits that built them`}` : '';
      // The catalogue is untouched, so neither it nor the selection is re-read: only this model's own record changed.
      invalidateResource('/api/bonded-parameterizations');
      // Stated before the reload, so a pane that fails to re-read still tells the reader what happened.
      notice(`Parameterization deleted: ${fate}${built}. The saved mapping ${file} is untouched.`, side);
      updateDelete();
      try {
        await parameterization.load(selectedMapping);
        // The other pane may show the same mapping: its record is gone too.
        reloadPanes({file, contentHash: hash}, pane);
      } catch (error) {
        notice(`Parameterization deleted: ${fate}${built}. The saved mapping ${file} is untouched. `
          + `The pane could not be re-read: ${error.message}`, side);
      }
    }

    async function resolveStructure(mapping) {
      // A candidate names the molecule it maps, and the pane must draw *that* molecule. Reading one structure for
      // every candidate drew sucrose's beads on DDM's atoms, because the same atom id is a different atom in another
      // molecule -- a candidate that maps 23 atoms cannot be measured against an 81-atom reference.
      //
      // There is no fallback: a model with no molecule, a context route that fails, or a context answer with no atoms
      // means the diagram is not drawn. Substituting the packaged molecule would draw another molecule's atoms and
      // bonds under this model's bead names -- the wrong picture presented as this one.
      if (mapping?.molecule?.atoms?.length) return mapping.molecule;   // a composition's own synthesized geometry
      const moleculeId = mapping?.molecule_id;
      if (!moleculeId) {
        throw new Error('This model names no molecule, so its beads cannot be placed on any atoms');
      }
      let payload;
      try {
        payload = await cachedApi('/api/mappings/context?molecule_id=' + encodeURIComponent(moleculeId),
                                  {maxAge: 60000});
      } catch (error) {
        throw new Error(`the coordinates of ${moleculeId} could not be read (${error.message})`);
      }
      const answer = payload?.molecule || payload?.context;
      if (!answer || !(answer.atoms || []).length) {
        throw new Error(`the route returned no coordinates for ${moleculeId}`);
      }
      return answer;
    }

    function structureAtoms() {
      const atoms = structure?.atoms || [];
      const legacyAngstrom = !structure?.molecule_id && !structure?.snapshot;
      const factor = legacyAngstrom ? 0.1 : 1;
      return new Map(atoms.map(atom => [Number(atom.id), {...atom, xyz: (atom.xyz || [0, 0, 0]).map(value => Number(value) * factor)}]));
    }

    function beadGeometry(mapping) {
      const atoms = structureAtoms();
      const centers = new Map();
      for (const bead of mapping?.beads || []) {
        if (bead.virtual_site) continue;
        const points = (bead.atoms || []).map(atomId => atoms.get(Number(atomId))?.xyz).filter(Boolean);
        if (points.length) centers.set(bead.name, points[0].map((_, index) => points.reduce((sum, point) => sum + point[index], 0) / points.length));
      }
      for (const bead of mapping?.beads || []) {
        if (!bead.virtual_site) continue;
        const points = (bead.virtual_site.parents || []).map(name => centers.get(name)).filter(Boolean);
        if (points.length) centers.set(bead.name, points[0].map((_, index) => points.reduce((sum, point) => sum + point[index], 0) / points.length));
      }
      const physical = new Set((mapping?.beads || []).filter(bead => !bead.virtual_site).map(bead => bead.name));
      let edges = (mapping?.connections || []).map(pair => [...pair]);
      if (!edges.length) {
        // The molecule the mapping names, never the packaged one: a bond between atom ids of another molecule would
        // draw a connectivity this model does not have.
        const owners = new Map();
        for (const bead of mapping?.beads || []) for (const atomId of bead.atoms || []) owners.set(Number(atomId), bead.name);
        edges = (structure?.bonds || []).map(edge => Array.isArray(edge) ? edge : [edge.a, edge.b])
          .map(([first, second]) => [owners.get(Number(first)), owners.get(Number(second))])
          .filter(([first, second]) => first && second && first !== second && physical.has(first) && physical.has(second));
      }
      return {beads: [...centers].map(([name, position]) => {
        const definition = (mapping?.beads || []).find(bead => bead.name === name) || {};
        return {name, position, size: definition.size || 'R', type: definition.type || 'Unspecified',
          virtual_site: definition.virtual_site};
      }), edges};
    }

    /** A revision's bead names, as the scene's: `B01` is the first bead of the mapping, virtual sites included. */
    function revisionAliases(mapping) {
      return new Map((mapping?.beads || []).map((bead, index) => [`B${String(index + 1).padStart(2, '0')}`, bead.name]));
    }

    /** A published reference's own ITP, read the way a revision's is, and never an input: a run consumes it. */
    function referenceTerms(mapping) {
      return parseTopology(mapping?.topology).map(term =>
        normalizeTerm({...term, source: 'martini-reference', editable: false}, term.id));
    }

    /** The mapping's own connectivity, for a model that has no revision: a start, not a fitted result. */
    function mappingTerms(mapping) {
      const geometry = beadGeometry(mapping);
      const positions = new Map(geometry.beads.map(bead => [bead.name, bead.position]));
      const distance = (first, second) => {
        const a = positions.get(first), b = positions.get(second);
        if (!a || !b) return 0.3;
        return Math.sqrt(a.reduce((sum, value, index) => sum + (value - b[index]) ** 2, 0));
      };
      return (mapping?.connections || geometry.edges).map((pair, index) => normalizeTerm({
        id: `mapping:${index}`, kind: 'bonds', beads: pair, function: '1',
        parameters: [formatNumber(distance(pair[0], pair[1])), '5000'], editable: false, source: 'mapping',
      }, `mapping:${index}`));
    }

    // --- editable parameters ---------------------------------------------------------------------------------------

    /** The stored values as strings, the way an input holds them. */
    function storedValues(term) { return (term.parameters || []).map(value => String(value)); }

    /** The values the inputs show: the reader's pending edit when there is one, else the stored revision. */
    function pendingValues(term) {
      const entry = pending.get(term.id);
      return entry ? entry.values : storedValues(term);
    }

    /** Whether two input strings name the same number; an empty/unparseable string is never the stored value. */
    function sameNumber(text, stored) {
      const value = Number(text);
      return String(text).trim() !== '' && Number.isFinite(value) && value === Number(stored);
    }

    function termDirty(term) {
      const entry = pending.get(term.id);
      return !!entry && entry.values.some((value, index) => !sameNumber(value, term.parameters[index]));
    }

    /** Record one input's value; a term whose every value matches the stored revision leaves the pending map. */
    function setPendingValue(term, index, value) {
      const entry = pending.get(term.id) || {values: storedValues(term)};
      const values = [...entry.values];
      values[index] = value;
      if (values.some((item, at) => !sameNumber(item, term.parameters[at]))) pending.set(term.id, {values});
      else pending.delete(term.id);
      pinnedStatus = null;
    }

    function dirtyTerms() { return terms.filter(term => term.editable && termDirty(term)); }

    /** The sentence the status line shows: a pinned server/save message, else what the shown state allows. */
    function baseStatus() {
      if (pinnedStatus) return pinnedStatus;
      if (!selectedMapping) return {text: 'Choose a model to read its terms.', kind: ''};
      if (selectedMapping.read_only) return {text: REFERENCE_REASON, kind: 'warn'};
      const shown = parameterization.shownRevision();
      if (!shown) return {text: 'This model has no stored revision: its rows are the mapping\'s draft connectivity and cannot be saved here.', kind: ''};
      if (shown.revision !== parameterization.currentRevisionNumber()) {
        return {text: `Revision ${shown.revision} is earlier: Save in place writes the revision a run consumes. Make it`
          + ' current first, or use Save as new.', kind: 'warn'};
      }
      if (shown.save_in_place !== true) {
        // The server owns the rule; quote its sentence instead of restating one here.
        return {text: shown.save_in_place_reason || `Revision ${shown.revision} cannot be saved in place.`, kind: 'warn'};
      }
      const dirty = dirtyTerms();
      return dirty.length
        ? {text: `${dirty.length} parameter change${dirty.length === 1 ? '' : 's'}, not saved.`, kind: 'warn'}
        : {text: `Showing revision ${shown.revision}, the revision a run consumes.`, kind: ''};
    }

    /** Both buttons and the status: the matrix is the server's gate and the pane's own shown/current state. */
    function updateTermActions() {
      if (!saveInPlace || !saveNew || !termsStatus) return;
      const reference = !!selectedMapping?.read_only;
      const shown = parameterization.shownRevision();
      const dirty = dirtyTerms();
      const editable = !!shown && shown.parameters_editable !== false;
      const inPlaceAllowed = !reference && parameterization.canSaveInPlace();
      saveInPlace.disabled = saving || !inPlaceAllowed || dirty.length === 0;
      saveInPlace.title = reference
        ? REFERENCE_REASON
        : !selectedMapping ? 'Choose a saved mapping first.'
          : !shown ? 'This model has no stored revision to save.'
            : shown.revision !== parameterization.currentRevisionNumber()
              ? `Revision ${shown.revision} is earlier. Make it current, or use Save as new.`
              : shown.save_in_place !== true
                ? (shown.save_in_place_reason || `Revision ${shown.revision} cannot be saved in place.`)
                : dirty.length ? `Save the ${dirty.length} edited term${dirty.length === 1 ? '' : 's'} in place in revision ${shown.revision}.`
                  : 'No unsaved parameter changes.';
      saveNew.disabled = saving || reference || !shown || !editable;
      saveNew.title = reference
        ? REFERENCE_REASON
        : !shown ? 'This model has no stored revision to clone.'
          : !editable ? (shown.save_in_place_reason || 'This revision is read-only.')
            : dirty.length ? `Save the ${dirty.length} edited term${dirty.length === 1 ? '' : 's'} as a new revision and make it current.`
              : 'Save the shown terms as a new revision and make it current.';
      const status = baseStatus();
      setText(termsStatus, status.text);
      termsStatus.dataset.state = status.kind || '';
    }

    /** The request's term list: every dirty row's numeric values, or `null` with the reason in the status line. */
    function collectEdits() {
      const edits = [];
      for (const term of dirtyTerms()) {
        const values = pendingValues(term);
        const numbers = values.map(value => Number(value));
        if (values.some(value => String(value).trim() === '') || numbers.some(value => !Number.isFinite(value))) {
          pinnedStatus = {text: 'Every edited parameter needs a number.', kind: 'error'};
          updateTermActions();
          return null;
        }
        edits.push({id: term.id, parameters: numbers});
      }
      return edits;
    }

    /** Save the dirty rows: in place on the current revision, or a new clone made current. */
    async function saveEditedTerms(mode) {
      if (saving) return;
      const edits = collectEdits();
      if (edits === null) return;
      const shown = parameterization.shownRevision();
      if (mode === 'in_place' && !edits.length) {
        pinnedStatus = {text: 'No parameter changes to save.', kind: 'warn'};
        updateTermActions();
        return;
      }
      if (mode === 'in_place' && !parameterization.canSaveInPlace()) {
        pinnedStatus = {text: parameterization.gateReason(), kind: 'error'};
        updateTermActions();
        return;
      }
      if (mode === 'new' && (!shown || shown.parameters_editable === false || selectedMapping?.read_only)) {
        pinnedStatus = {text: parameterization.gateReason(), kind: 'error'};
        updateTermActions();
        return;
      }
      saving = true;
      pinnedStatus = null;
      updateTermActions();
      try {
        const saved = await parameterization.saveTerms({mode, edits});
        pending.clear();
        const message = mode === 'in_place'
          ? `Revision ${shown.revision} saved in place: ${edits.length} term${edits.length === 1 ? '' : 's'} edited; Source reads manual.`
          : `Revision ${saved.revision} saved and current; revision ${shown.revision} is unchanged.`;
        // The reload is the record, not the route's echo: it re-reads the revision the save made current (in place,
        // the same number with a new digest; as new, the appended one).
        await loadShown(saved.file, saved.revision);
        // The other pane may show the same mapping; its record's labels are now stale.
        reloadPanes({file: saved.file, contentHash: parameterization.contentHash()}, pane);
        pinnedStatus = {text: message, kind: ''};
      } catch (error) {
        // A 409/400 carries the server's own sentence; the status says exactly that.
        pinnedStatus = {text: `The terms were not saved: ${error.message}`, kind: 'error'};
      } finally {
        saving = false;
        updateTermActions();
      }
    }

    function renderTable() {
      tableHost.replaceChildren();
      if (!terms.length) {
        tableHost.textContent = 'No bonded terms loaded.';
        return;
      }
      const table = document.createElement('table');
      table.innerHTML = '<caption>Kind names the GROMACS topology section; function is its potential form; source is where the term came from. Editable parameters are inputs; a virtual site\'s parents are readings, and the function form is never a draft. A Fast-Forward torsion is one line per harmonic, so each such row is one line.</caption>'
        + '<thead><tr><th>Kind</th><th>Beads</th><th>Function</th><th>Parameters</th><th>Source</th></tr></thead>';
      const body = document.createElement('tbody');
      for (const term of terms) {
        const row = document.createElement('tr');
        row.dataset.id = term.id;
        row.tabIndex = 0;
        row.setAttribute('aria-selected', String(term.id === selectedTermId));
        const kindCell = document.createElement('td');
        kindCell.textContent = term.kind;
        const beadsCell = document.createElement('td');
        beadsCell.textContent = term.beads.join(' · ');
        const functionCell = document.createElement('td');
        functionCell.textContent = functionSentence(term);
        row.append(kindCell, beadsCell, functionCell);
        const parameters = document.createElement('td');
        if (term.editable) {
          const grid = document.createElement('div');
          grid.className = 'bonded-term-inputs';
          const values = pendingValues(term);
          const labels = term.parameters.map((_, index) => term.parameter_labels[index] || `parameter ${index + 1}`);
          for (const [index, label] of labels.entries()) {
            const wrap = document.createElement('label');
            wrap.textContent = label;
            const input = document.createElement('input');
            input.type = 'number';
            input.step = /multiplicity/i.test(label) ? '1' : 'any';
            input.inputMode = 'decimal';
            input.value = values[index] ?? '';
            input.dataset.dirty = String(termDirty(term) && !sameNumber(values[index], term.parameters[index]));
            input.setAttribute('aria-label', `${term.kind} ${term.beads.join(' ')} ${label}`);
            input.oninput = () => {
              setPendingValue(term, index, input.value);
              input.dataset.dirty = String(termDirty(term));
              updateTermActions();
            };
            // An input click must not bubble to the row: selecting the row re-renders the table and would steal focus
            // from the field the reader is typing in. The value survives either way through `pending`.
            input.onclick = event => event.stopPropagation();
            wrap.append(input);
            grid.append(wrap);
          }
          parameters.append(grid);
        } else {
          parameters.className = 'bonded-readonly-parameter';
          parameters.textContent = parameterSentence(term);
          parameters.title = term.kind === 'virtual_sitesn' || term.kind === 'virtual_sites3'
            ? 'read-only: these parents are the mapping’s own beads'
            : 'read-only: this term has no editable parameter list';
        }
        const source = document.createElement('td');
        source.className = 'bonded-source';
        source.textContent = term.source || 'unrecorded';
        row.append(parameters, source);
        row.onclick = event => {
          if (event.target.closest('input, select')) return;
          selectedTermId = term.id;
          renderState();
        };
        row.onkeydown = event => {
          if (event.target.closest('input')) return;
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            selectedTermId = term.id;
            renderState();
          }
        };
        body.append(row);
      }
      table.append(body);
      tableHost.append(table);
    }

    function renderState() {
      renderTable();
      updateTermActions();
      if (!structure) {
        // No atoms, no scene: an empty figure and the reason, never another molecule's geometry under these names.
        plot.render({beads: [], edges: [], terms: [], selectedBeads, selectedTermId, beadAliases: new Map()});
        setText(selectionStatus, geometryNotice || 'Select a bead to read its name.');
        return;
      }
      const geometry = beadGeometry(selectedMapping || {});
      plot.render({beads: geometry.beads, edges: geometry.edges, terms, selectedBeads, selectedTermId,
                   beadAliases: revisionAliases(selectedMapping)});
      setText(selectionStatus, selectedBeads.length
        ? `Selected beads: ${selectedBeads.join(' · ')}`
        : 'Select a bead to read its name.');
    }

    /** The molecule select: every all-atom molecule the catalogue offers, plus CG compositions as one last group. */
    async function fillMolecules() {
      // Compositions are CG models, not molecules, so they are not in `/api/molecules`: offered only where the
      // catalogue holds one, and last, because they are a different kind of thing rather than another molecule.
      const offered = (mappingData.candidates || []).some(candidate => String(candidate.file || '').startsWith('composition:'));
      const named = (mappingData.candidates || []).find(candidate => candidate.molecule_id);
      await fillMoleculeOptions(moleculeSelect, {
        extra: offered ? [new Option('CG compositions', COMPOSITIONS)] : [],
        preferred: named?.molecule_id,
      });
    }

    /** Each saved mapping's parameterization record: the selector names every revision, not only the shown mapping's. */
    async function readRecords(list) {
      // ponytail: one full record read per saved mapping, because the selector must label every revision and the route
      // answers one record at a time. A bulk summary route would trim the payloads if a molecule ever carries many.
      const records = new Map();
      await Promise.all(list.map(async candidate => {
        const params = new URLSearchParams();
        // The content identity first: it is what a revision is addressed by, and a rename keeps it.
        if (candidate.mapping_content_hash) params.set('content_hash', candidate.mapping_content_hash);
        if (candidate.mapping_hash) params.set('mapping_hash', candidate.mapping_hash);
        if (![...params].length) return;
        try {
          records.set(candidate.file, await api('/api/bonded-parameterizations?' + params));
        } catch (error) {
          // The options still list the mapping; its label says the record could not be read rather than claiming a draft.
          records.set(candidate.file, {error: error.message, summary: null, revisions: []});
        }
      }));
      return records;
    }

    /** The one display selector: every revision of every saved mapping, grouped by mapping. */
    function fillDisplay() {
      const wanted = displaySelect.value;
      const groups = [];
      for (const candidate of candidates) {
        const record = modelRecords.get(candidate.file);
        const revisions = [...(record?.revisions || [])].sort((first, second) => second.revision - first.revision);
        const current = record?.summary?.revision ?? null;
        const name = candidate.name || candidate.file;
        const group = document.createElement('optgroup');
        group.label = name;
        if (revisions.length) {
          for (const item of revisions) {
            group.append(new Option(`${name} · Revision ${item.revision} · `
              + `${item.revision === current ? 'current' : 'earlier'} · ${item.engine || 'fit'} · `
              + `${date(item.created_at) || 'no date recorded'}`, optionValue(candidate.file, item.revision)));
          }
        } else {
          group.append(new Option(record?.error ? 'Revisions could not be read'
            : 'Draft mapping connectivity (no parameterization)', optionValue(candidate.file, null)));
        }
        groups.push(group);
      }
      if (reference) {
        const group = document.createElement('optgroup');
        group.label = 'Published Martini 3 reference';
        group.append(new Option(
          `Martini 3 reference · ${reference.reference_entry || reference.molecule_id} (read-only)`,
          optionValue(reference.file, null)));
        groups.push(group);
      }
      if (!groups.length) {
        displaySelect.replaceChildren(new Option(moleculeSelect.value === COMPOSITIONS
          ? 'No saved CG compositions yet'
          : `No saved mapping for ${moleculeSelect.value || 'this molecule'} yet`, ''));
        return;
      }
      displaySelect.replaceChildren(...groups);
      const values = [...displaySelect.options].map(option => option.value);
      displaySelect.value = values.includes(wanted) ? wanted : defaultOptionValue();
    }

    /** What the selector answers when nothing is chosen: the first mapping's current revision, else its draft, else
     * the reference when it is the only option. It only reads -- a mount must never make a revision current. */
    function defaultOptionValue() {
      const first = candidates[0];
      if (first) {
        const record = modelRecords.get(first.file);
        const number = record?.summary?.revision ?? null;
        if (record?.revisions?.some(item => item.revision === number)) return optionValue(first.file, number);
        return optionValue(first.file, null);
      }
      return reference ? optionValue(reference.file, null) : '';
    }

    /** Point the selector at the revision the pane is actually showing (a load may have fallen back to current). */
    function syncDisplay() {
      if (!selectedMapping?.file) return;
      const shown = parameterization.shownRevision();
      const wanted = optionValue(selectedMapping.file, shown ? shown.revision : null);
      if ([...displaySelect.options].some(option => option.value === wanted)) displaySelect.value = wanted;
    }

    /** The hidden bridge's options, pane A only: one per model a door can name, so `new-run.js` can wait for its own.
     *
     * It lists the whole catalogue, not only pane A's current molecule: a door names one saved mapping by file, and
     * its molecule need not be the one this pane happens to show -- `select` resolves the molecule from the file.
     */
    function fillBridge() {
      if (!paneBridge) return;
      const already = new Set();
      const options = [];
      for (const candidate of mappingData.candidates || []) {
        if (!candidate.file || candidate.error || already.has(candidate.file)) continue;
        already.add(candidate.file);
        options.push(new Option(candidate.name || candidate.file, candidate.file));
      }
      for (const candidate of candidates) {
        if (!candidate.file || already.has(candidate.file)) continue;
        already.add(candidate.file);
        options.push(new Option(candidate.name || candidate.file, candidate.file));
      }
      if (reference) {
        options.push(new Option(reference.name || `Published reference · ${reference.molecule_id}`, reference.file));
      }
      paneBridge.replaceChildren(...options);
      if (selectedMapping?.file && options.some(option => option.value === selectedMapping.file)) {
        paneBridge.value = selectedMapping.file;
      }
    }

    /** The selected molecule's saved mappings and each one's parameterization record, then its published reference. */
    async function fillMappings(molecule) {
      const token = ++optionsGeneration;
      let list = [];
      if (molecule === COMPOSITIONS) {
        list = (mappingData.candidates || []).filter(candidate =>
          String(candidate.file || '').startsWith('composition:') && !candidate.error);
      } else if (molecule) {
        try {
          // Asked of the route, not filtered from a catalogue already in memory: the route holds both the molecule and
          // its snapshot, and a summary row does not have to carry `molecule_id` for this pane to work.
          const answer = await cachedApi(
            '/api/mappings?view=summary&molecule_id=' + encodeURIComponent(molecule), {maxAge: CATALOGUE_MAX_AGE});
          list = (answer.candidates || []).filter(candidate => !candidate.error && candidate.file);
        } catch (error) { list = []; }
      }
      let published = null;
      if (molecule && molecule !== COMPOSITIONS) {
        try {
          // A 404 is "this molecule has no published entry", which is an answer and not a failure to report.
          const answer = await cachedApi(
            '/api/mappings/reference/' + encodeURIComponent(molecule), {maxAge: CATALOGUE_MAX_AGE});
          published = answer?.model || null;
        } catch (error) { published = null; }
      }
      const records = await readRecords(list);
      if (token !== optionsGeneration) return false;
      candidates = list;
      reference = published;
      modelRecords = records;
      fillDisplay();
      fillBridge();
      return true;
    }

    /** Load and show one model. `revision` is the revision the selector asked for; `null` is its draft or a reference. */
    async function loadShown(file, revision) {
      const token = ++generation;
      // The switch is busy from the click, not from the pane load: the selector already shows the new model while the
      // catalogue answer is still in flight, so anything acting on the old pane's contents would act on a model that
      // is no longer selected.
      root.setAttribute('aria-busy', 'true');
      try {
        const loaded = await loadMapping(file);
        if (token !== generation) return;
        selectedMapping = loaded || null;
        geometryNotice = '';
        if (!loaded) {
          // A molecule with no saved model (or no composition) is a normal state: the table and the scene must not
          // keep showing the previous molecule's model while the pane says there is nothing selected.
          structure = null;
          await parameterization.load(null);
          updateDelete();
          fillBridge();
          notice(moleculeSelect?.value === COMPOSITIONS ? 'No CG composition is selected.'
            : `No saved mapping for ${moleculeSelect?.value || 'this molecule'} yet.`, side);
          renderState();
          return;
        }
        // Before anything is drawn from it: every geometry below is measured against this molecule's atoms. A geometry
        // that cannot be read is stated, not replaced by the packaged molecule's.
        try {
          structure = await resolveStructure(loaded);
        } catch (error) {
          structure = null;
          geometryNotice = error.message;
        }
        if (token !== generation) return;
        // The pane's record, the delete button and the status are read from the mapping's own parameterization; the
        // terms come back through `onTerms` once that record has been read.
        await parameterization.load(loaded, {shown: revision});
        updateDelete();
        syncDisplay();
        fillBridge();
        notice(geometryNotice ? `The diagram is not drawn: ${geometryNotice}.` : '', side);
      } catch (error) {
        if (token === generation) {
          notice(error.message, side); selectedMapping = null; structure = null; terms = []; renderState();
        }
      } finally {
        // A superseded switch must not report the newer one idle: only the current generation owns the state.
        if (token === generation) root.setAttribute('aria-busy', 'false');
      }
    }

    /** The selector's choice, applied. A revision of the mapping already shown is display-only: it reads no route and
     * changes nothing a run consumes. */
    async function showOption(value) {
      const target = optionTarget(value);
      if (!target.file) return;
      if (selectedMapping?.file === target.file) {
        if (target.revision !== null) {
          parameterization.show(target.revision);
          syncDisplay();
        }
        return;
      }
      await loadShown(target.file, target.revision);
    }

    const pane = {
      side,
      file: () => parameterization.file(),
      contentHash: () => parameterization.contentHash(),
      reload: () => (parameterization.file() ? loadShown(parameterization.file(), null) : Promise.resolve()),
      resize: () => plot.resize(),
      select,
      mount,
    };

    if (displaySelect) displaySelect.onchange = () => showOption(displaySelect.value);
    if (paneBridge) paneBridge.onchange = () => { doorTarget = paneBridge.value; select(paneBridge.value); };
    if (moleculeSelect) moleculeSelect.onchange = async () => {
      await fillMappings(moleculeSelect.value);
      if (displaySelect.value) await showOption(displaySelect.value);
      else await loadShown('');
    };
    if (deleteButton) deleteButton.onclick = () => deleteParameterization();
    if (saveInPlace) saveInPlace.onclick = () => saveEditedTerms('in_place');
    if (saveNew) saveNew.onclick = () => saveEditedTerms('new');

    async function mount() {
      // One model load at mount: the selects are set and their options filled here, and `showOption` below loads the
      // model once. A `change` event dispatched at mount would load a second time for no reader-visible gain.
      root.setAttribute('aria-busy', 'true');
      try {
        await fillMolecules();
        await fillMappings(moleculeSelect.value);
        updateDelete();
        if (displaySelect.value) await showOption(displaySelect.value);
        else await loadShown('');
      } finally {
        // `loadShown` reports its own switch idle; a mount that failed before reaching it must not leave the pane busy.
        if (!selectedMapping) root.setAttribute('aria-busy', 'false');
      }
    }

    async function select(file) {
      // The catalog path, driven by whoever is handing a model over instead of by a click:
      // selecting the option is what a user picking it from the list does.
      if (!file) return false;
      const listed = () => candidates.some(candidate => candidate.file === file)
        || !!(reference && reference.file === file);
      if (!listed()) {
        if (file.startsWith('composition:')) {
          // A composition belongs to the catalogue's last group rather than to a molecule.
          if ([...moleculeSelect.options].some(option => option.value === COMPOSITIONS)) {
            moleculeSelect.value = COMPOSITIONS;
            await fillMappings(COMPOSITIONS);
          }
        } else if (file.startsWith('reference:')) {
          const molecule = file.slice('reference:'.length);
          if ([...moleculeSelect.options].some(option => option.value === molecule)) {
            moleculeSelect.value = molecule;
            await fillMappings(molecule);
          }
        } else {
          // A saved mapping names the molecule it maps, but a door's address carries only the file. Read the mapping
          // once (the same cached read `loadShown` will reuse) and move the molecule select to its own.
          let candidate = null;
          try { candidate = await loadMapping(file); } catch (error) { candidate = null; }
          const molecule = candidate?.molecule_id;
          if (molecule && [...moleculeSelect.options].some(option => option.value === molecule)) {
            moleculeSelect.value = molecule;
            await fillMappings(molecule);
          }
        }
      }
      if (!listed()) return false;
      const record = modelRecords.get(file);
      const revision = record?.revisions?.length ? (record.summary?.revision ?? null) : null;
      await loadShown(file, revision);
      return true;
    }

    return pane;
  }

  for (const root of columns) panes.push(createPane(root, root.dataset.side));
  const paneA = panes.find(pane => pane.side === 'A');

  /** Reload the panes that show the record that just changed; every other pane keeps its state and typed edits. */
  function reloadPanes(change, except, {refreshFit = true} = {}) {
    const file = change?.file || '';
    const contentHash = change?.contentHash || '';
    for (const pane of panes) {
      if (pane === except) continue;
      const same = (file && pane.file() === file) || (contentHash && pane.contentHash() === contentHash);
      if (same) pane.reload().catch(error => notice(error.message, pane.side));
    }
    // The fit card's result card is the same record: keep it from going stale behind a pane's write. A fit's own
    // completion re-read it already, so that path skips the second read.
    if (refreshFit) fitCard?.refresh(change);
  }

  fitCard = setupFitCard({
    loadMapping,
    onFitted: change => reloadPanes(change, undefined, {refreshFit: false}),
    onMessage: text => notice(text),
  });

  // The second pane's Minimize / Expand, remembered across a reload. Pane A is never hidden and its state never moves.
  function remembered() {
    const state = storage.get(STATE_KEY, null);
    return state && typeof state === 'object' ? state : {};
  }

  function remember() {
    const state = {minimized: {}};
    state.minimized.B = Boolean(minimized.B);
    storage.set(STATE_KEY, state);
  }

  function applyMinimized() {
    const column = bySide.get('B');
    const collapsed = Boolean(minimized.B);
    if (column) column.dataset.minimized = String(collapsed);
    if (columnsWrap) columnsWrap.classList.toggle('one-column', collapsed);
    if (minimizeButton) {
      minimizeButton.textContent = collapsed ? 'Expand' : 'Minimize';
      minimizeButton.setAttribute('aria-expanded', String(!collapsed));
    }
  }

  function toggleMinimized() {
    minimized.B = !minimized.B;
    applyMinimized();
    remember();
    // The grid changes width for both panes, not only the collapsed one: A widens when B collapses and narrows
    // again when it expands, and B's host measured zero width while it was hidden. Measure both after the switch.
    for (const pane of panes) pane.resize();
    requestAnimationFrame(() => { for (const pane of panes) pane.resize(); });
  }

  // Bound once with the DOM it acts on: a re-entry to the panel (a resource invalidation re-mounts the workspace)
  // must not add a second listener, or one click would toggle the pane twice and appear to do nothing.
  if (minimizeButton) minimizeButton.addEventListener('click', toggleMinimized);

  async function mount() {
    const state = remembered();
    minimized = {B: Boolean((state.minimized || {}).B)};
    applyMinimized();
    await Promise.all([...panes.map(pane => pane.mount()), fitCard.mount()]);
    // The door's `change` can land while pane A is still mounting, and the pane's own first load would then win the
    // generation race. Applying the door's request after the mount makes the cold-load path deterministic.
    if (doorTarget && paneA && paneA.file() !== doorTarget) await paneA.select(doorTarget);
  }

  return {mount, select: file => (paneA ? paneA.select(file) : Promise.resolve(false))};
}
