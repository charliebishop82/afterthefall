// Pure helpers shared by the refresh display and optional Node regressions.
function panelChanges(state, shownRevision, shownStatus) {
  return state.revision !== shownRevision || state.status !== shownStatus;
}
function clockDescription(status) {
  return ({active:'Time is running.',finalizing:'Season is finalizing.',paused:'Time is paused.',
    suspended:'Your settlement is frozen.',finished:'Season finished.'})[status] || 'Waiting for season start.';
}
if (typeof module !== 'undefined') module.exports = {panelChanges, clockDescription};
