// The Run view Analysis card's extension seam: a feature registers the sections only its analyses need.
//
// The card itself is engine shell -- the run's figures, the queue buttons, the task list and the assessment's
// diagnostics. What a feature's analyses add is a section: a label, the runs it answers for, and a function that
// draws it. A feature may also register a notice, the one sentence a reader gets when its analysis is not
// defined for this run rather than silently missing.
//
// Registration happens from the feature's own extension module before any panel mounts (`main.js` imports
// `Feature.extension_modules` ahead of the first await), so an install without the feature downloads neither the
// module nor its section and pays nothing for the seam.
//
// `mount({host, job, side, isCurrent, button})` is called the first time a section is opened for a run; the card
// keeps the pane and the section owns its contents until the run changes. `refresh(...)` is called when an
// analysis task settles, which is the one moment a published record can have changed; a section that fetched
// nothing yet, or the same attempt, decides for itself whether to re-read. `isCurrent()` answers false once the
// monitor has moved to another run, so a late answer writes nothing.
const sections = [];
const notices = [];

export function registerRunViewAnalysisSection(section) {
  if (!section || typeof section !== 'object' || typeof section.serves !== 'function'
      || typeof section.mount !== 'function') {
    throw new TypeError('registerRunViewAnalysisSection needs an object with serves(job) and mount(...)');
  }
  // Registering one name twice replaces it, so a module that is imported twice (or a test that re-registers)
  // leaves one tab rather than two.
  const index = sections.findIndex(existing => existing.name === section.name);
  if (index >= 0) sections[index] = section;
  else sections.push(section);
}

/** The sections a run offers, in the order they are tabbed. */
export function analysisSectionsFor(job) {
  return sections
    .filter(section => {
      try {
        return Boolean(section.serves(job));
      } catch (error) {
        return false;
      }
    })
    .sort((first, second) => (Number(first.order) || 0) - (Number(second.order) || 0));
}

export function registerRunViewAnalysisNotice(notice) {
  if (!notice || typeof notice !== 'object' || typeof notice.serves !== 'function'
      || typeof notice.text !== 'function') {
    throw new TypeError('registerRunViewAnalysisNotice needs an object with serves(job) and text(job)');
  }
  const index = notices.findIndex(existing => existing.name === notice.name);
  if (index >= 0) notices[index] = notice;
  else notices.push(notice);
}

/** The first notice that applies to this run, or ''. */
export function analysisNoticeFor(job) {
  for (const notice of notices) {
    try {
      if (notice.serves(job)) return String(notice.text(job) || '');
    } catch (error) {
      // A notice that cannot answer leaves the card to the section's own missing-record sentence.
    }
  }
  return '';
}
