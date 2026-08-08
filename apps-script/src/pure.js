var MeetingOpsPure = (function () {
  var MINUTE_MS = 60 * 1000;
  var WEEK_MS = 7 * 24 * 60 * MINUTE_MS;

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function dateKey(date, timeZone) {
    return Utilities.formatDate(date, timeZone, 'yyyy-MM-dd');
  }

  function resolveDocName(template, date, timeZone) {
    return String(template).replace('{YYYY-MM-DD}', dateKey(date, timeZone));
  }

  function isWithinAgendaWindow(now, occurrence, leadMin, staleWindowMin) {
    var lowerBound = occurrence.getTime() - leadMin * MINUTE_MS;
    var upperBound = occurrence.getTime() + staleWindowMin * MINUTE_MS;
    return now.getTime() >= lowerBound && now.getTime() <= upperBound;
  }

  function nextWeeklyOccurrence(occurrence) {
    return new Date(occurrence.getTime() + WEEK_MS);
  }

  function shouldPost(now, occurrence, delayMin) {
    return now.getTime() >= occurrence.getTime() + delayMin * MINUTE_MS;
  }

  function normalizeCadence(input) {
    var cadence = input || {};
    var visibility = cadence.visibility || 'public';
    var notificationMode = cadence.notificationMode || 'orbie';
    var cadenceType = cadence.cadence || cadence.cadenceType || 'weekly';
    var recipients = cadence.notificationRecipients || [];

    if (visibility !== 'public' && visibility !== 'private') {
      throw new Error('visibility must be public or private');
    }
    if (notificationMode !== 'orbie') {
      throw new Error('notificationMode must be orbie');
    }
    if (cadenceType !== 'weekly') {
      throw new Error('Only weekly cadence is supported by the current worker');
    }
    if (!Array.isArray(recipients)) {
      throw new Error('notificationRecipients must be an array');
    }
    if (visibility === 'private' && !cadence.ownerSlackUserId) {
      throw new Error('private cadences require ownerSlackUserId');
    }
    if (visibility === 'private' && recipients.length === 0) {
      throw new Error('private cadences require notificationRecipients');
    }
    return {
      id: cadence.id,
      title: cadence.title,
      sourceDocId: cadence.sourceDocId,
      outputFolderId: cadence.outputFolderId,
      nextOccurrenceAt: cadence.nextOccurrenceAt,
      cadence: cadenceType,
      cadenceCron: cadence.cadenceCron || null,
      notifyChannel: cadence.notifyChannel || null,
      notifyChannelName: cadence.notifyChannelName || null,
      notificationRecipients: recipients,
      notificationMode: notificationMode,
      visibility: visibility,
      ownerSlackUserId: cadence.ownerSlackUserId || null,
      accessSlackUserIds: cadence.accessSlackUserIds || [],
      notifyLeadMin: cadence.notifyLeadMin,
      notesDelayMin: cadence.notesDelayMin,
      durationMin: cadence.durationMin,
      docNameTemplate: cadence.docNameTemplate,
      templateTabName: cadence.templateTabName || 'Template',
      attendees: cadence.attendees || [],
      previousMeetingLink: cadence.previousMeetingLink || '',
      timeZone: cadence.timeZone || null,
      status: cadence.status || 'active'
    };
  }

  function notificationKey(cadenceId, occurrence, timeZone, kind) {
    return String(kind) + ':' + String(cadenceId) + ':' + dateKey(occurrence, timeZone);
  }

  return {
    dateKey: dateKey,
    escapeRegExp: escapeRegExp,
    isWithinAgendaWindow: isWithinAgendaWindow,
    nextWeeklyOccurrence: nextWeeklyOccurrence,
    normalizeCadence: normalizeCadence,
    notificationKey: notificationKey,
    resolveDocName: resolveDocName,
    shouldPost: shouldPost
  };
})();

if (typeof module !== 'undefined') {
  module.exports = MeetingOpsPure;
}
