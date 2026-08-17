var MeetingOpsPure = (function () {
  var MINUTE_MS = 60 * 1000;
  var WEEK_MS = 7 * 24 * 60 * MINUTE_MS;
  var MAX_CUSTOM_INSTRUCTIONS_LENGTH = 4000;

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

  function offsetMilliseconds_(date, timeZone) {
    var offset = Utilities.formatDate(date, timeZone, 'Z');
    var match = String(offset).match(/^([+-])(\d{2})(\d{2})$/);
    if (!match) throw new Error('Could not read timezone offset ' + offset);
    var milliseconds = (
      Number(match[2]) * 60 * 60 * 1000 +
      Number(match[3]) * 60 * 1000
    );
    return match[1] === '-' ? -milliseconds : milliseconds;
  }

  function localDateToUtc_(parts, timeZone) {
    var localMillis = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      parts.millisecond
    );
    var offset = offsetMilliseconds_(new Date(localMillis), timeZone);
    var result = new Date(localMillis - offset);
    // Re-read the offset after applying it so a DST boundary uses the target
    // date's offset rather than the offset at the UTC guess.
    var adjustedOffset = offsetMilliseconds_(result, timeZone);
    if (adjustedOffset !== offset) result = new Date(localMillis - adjustedOffset);
    return result;
  }

  function localDateTime_(date, timeZone) {
    var dateParts = Utilities.formatDate(date, timeZone, 'yyyy-MM-dd')
      .split('-').map(Number);
    var timeParts = Utilities.formatDate(date, timeZone, 'HH:mm:ss')
      .split(':').map(Number);
    return {
      year: dateParts[0],
      month: dateParts[1],
      day: dateParts[2],
      hour: timeParts[0],
      minute: timeParts[1],
      second: timeParts[2],
      millisecond: date.getMilliseconds()
    };
  }

  function nextOccurrence(occurrence, cadenceType, timeZone) {
    var zone = timeZone || 'UTC';
    var parts = localDateTime_(occurrence, zone);
    var dayDelta = cadenceType === 'weekly' ? 7 :
      cadenceType === 'bi-weekly' ? 14 : 0;
    if (dayDelta) {
      var nextDay = new Date(Date.UTC(
        parts.year, parts.month - 1, parts.day + dayDelta
      ));
      parts.year = nextDay.getUTCFullYear();
      parts.month = nextDay.getUTCMonth() + 1;
      parts.day = nextDay.getUTCDate();
      return localDateToUtc_(parts, zone);
    }
    var months = cadenceType === 'quarterly' ? 3 : 1;
    var day = parts.day;
    var sourceLastDay = new Date(Date.UTC(parts.year, parts.month, 0)).getUTCDate();
    var monthEndAnchor = day === sourceLastDay;
    var monthIndex = parts.month - 1 + months;
    parts.year += Math.floor(monthIndex / 12);
    parts.month = monthIndex % 12 + 1;
    var lastDay = new Date(Date.UTC(parts.year, parts.month, 0)).getUTCDate();
    parts.day = monthEndAnchor ? lastDay : Math.min(day, lastDay);
    return localDateToUtc_(parts, zone);
  }

  function shouldPost(now, occurrence, delayMin) {
    return now.getTime() >= occurrence.getTime() + delayMin * MINUTE_MS;
  }

  function normalizeCustomInstructions(value) {
    if (typeof value !== 'string') return '';
    return value
      .replace(/\r\n?/g, '\n')
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g, '')
      .trim()
      .slice(0, MAX_CUSTOM_INSTRUCTIONS_LENGTH)
      .trim();
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
    if (['weekly', 'bi-weekly', 'monthly', 'quarterly'].indexOf(cadenceType) === -1) {
      throw new Error('cadence must be weekly, bi-weekly, monthly, or quarterly');
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
      notesTabName: cadence.notesTabName || 'Meeting Notes',
      attendees: cadence.attendees || [],
      documentEditorEmails: uniqueStrings(cadence.documentEditorEmails || []),
      previousMeetingLink: cadence.previousMeetingLink || '',
      timeZone: cadence.timeZone || null,
      status: cadence.status || 'active'
    };
  }

  function isCadenceAuthorized(cadence, requesterSlackUserId) {
    if (!requesterSlackUserId) return false;
    if (cadence.status && cadence.status !== 'active') return false;
    if (cadence.visibility === 'public') return true;
    var privateUsers = [cadence.ownerSlackUserId]
      .concat(cadence.accessSlackUserIds || [])
      .concat(cadence.notificationRecipients || []);
    return privateUsers.indexOf(String(requesterSlackUserId)) !== -1;
  }

  function authorizedCadences(cadences, requesterSlackUserId) {
    return (cadences || []).filter(function (cadence) {
      return (!cadence.status || cadence.status === 'active') &&
        isCadenceAuthorized(cadence, requesterSlackUserId);
    });
  }

  function uniqueStrings(values) {
    var seen = {};
    return (values || []).map(String).filter(function (value) {
      if (!value || seen[value]) return false;
      seen[value] = true;
      return true;
    });
  }

  function notificationRecipients(cadence, requesterSlackUserId, scheduled) {
    if (cadence.visibility !== 'private') return [null];
    if (cadence.notifyChannel) return [null];
    if (scheduled) {
      var scheduledRecipients = uniqueStrings(cadence.notificationRecipients || []);
      if (!scheduledRecipients.length) {
        throw new Error('scheduled private cadences require notificationRecipients');
      }
      return scheduledRecipients;
    }
    if (!requesterSlackUserId) {
      throw new Error('private notification delivery requires a requester');
    }
    return [String(requesterSlackUserId)];
  }

  function wasNotificationDelivered(record, kind, requesterSlackUserId) {
    if (record[kind + 'Notified']) return true;
    if (!requesterSlackUserId) return false;
    return (record[kind + 'NotifiedRecipients'] || [])
      .map(String)
      .indexOf(String(requesterSlackUserId)) !== -1;
  }

  function markNotificationDelivered(record, kind, requesterSlackUserId) {
    if (!requesterSlackUserId) {
      record[kind + 'Notified'] = true;
      return record;
    }
    record[kind + 'NotifiedRecipients'] = uniqueStrings(
      (record[kind + 'NotifiedRecipients'] || []).concat([requesterSlackUserId])
    );
    return record;
  }

  function notificationKey(cadenceId, occurrence, timeZone, kind, recipientSlackUserId) {
    var key = String(kind) + ':' + String(cadenceId) + ':' + dateKey(occurrence, timeZone);
    return recipientSlackUserId ? key + ':' + String(recipientSlackUserId) : key;
  }

  return {
    dateKey: dateKey,
    escapeRegExp: escapeRegExp,
    isWithinAgendaWindow: isWithinAgendaWindow,
    isCadenceAuthorized: isCadenceAuthorized,
    markNotificationDelivered: markNotificationDelivered,
    normalizeCustomInstructions: normalizeCustomInstructions,
    nextOccurrence: nextOccurrence,
    nextWeeklyOccurrence: nextWeeklyOccurrence,
    normalizeCadence: normalizeCadence,
    notificationRecipients: notificationRecipients,
    notificationKey: notificationKey,
    authorizedCadences: authorizedCadences,
    resolveDocName: resolveDocName,
    shouldPost: shouldPost,
    wasNotificationDelivered: wasNotificationDelivered
  };
})();

if (typeof module !== 'undefined') {
  module.exports = MeetingOpsPure;
}
