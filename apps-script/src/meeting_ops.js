var AGENDA_RECORD_PREFIX = 'AGENDA_RECORD:';
var NEXT_OCCURRENCE_PREFIX = 'NEXT_OCCURRENCE:';
var ORBIE_OUTBOX_PREFIX = 'ORBIE_OUTBOX:';
var DEFAULT_TEMPLATE_TAB_TITLE = 'Template';
var DEFAULT_TIME_ZONE = 'Europe/Warsaw';
var WORLD_SLACK_TEAM_ID = 'TL1HM8UUU';

// Entry point for Orbie via the Apps Script Execution API. The caller supplies
// a cadence id and a stable, testable clock; configuration and Google auth stay
// inside Apps Script, while Slack delivery stays with Orbie.
function runCadenceJob(payload) {
  var request = typeof payload === 'string' ? JSON.parse(payload) : (payload || {});
  return withScriptLock_(function () {
    var cadence = getMeetingConfig_().filter(function (item) {
      return item.id === request.cadenceId;
    })[0];
    if (!cadence) throw new Error('Unknown cadence ' + request.cadenceId);
    var caller = parseCaller_(request);
    if (!MeetingOpsPure.isCadenceAuthorized(cadence, caller.requesterSlackUserId)) {
      throw new Error('Cadence is not authorized for ' + caller.requesterSlackUserId);
    }
    var now = request.now ? new Date(request.now) : new Date();
    var requesterSlackUserId = caller.requesterSlackUserId;
    processNotesNotification_(cadence, now, requesterSlackUserId);
    return processAgenda_(cadence, now, requesterSlackUserId);
  });
}

// Return only active cadences the supplied Slack user may run. The workflow
// validates the authenticated Slack team before calling this function; the
// team check here is defense in depth for direct Execution API callers.
function getAuthorizedCadences(payload) {
  var caller = parseCaller_(payload);
  return MeetingOpsPure.authorizedCadences(
    getMeetingConfig_(),
    caller.requesterSlackUserId
  );
}

function getPendingOrbieNotifications() {
  var properties = PropertiesService.getScriptProperties().getProperties();
  return Object.keys(properties).filter(function (key) {
    return key.indexOf(ORBIE_OUTBOX_PREFIX) === 0;
  }).map(function (key) {
    return JSON.parse(properties[key]);
  });
}

function getPendingOrbieNotificationsForCaller(payload) {
  var caller = parseCaller_(payload);
  var properties = PropertiesService.getScriptProperties().getProperties();
  return Object.keys(properties).filter(function (key) {
    if (key.indexOf(ORBIE_OUTBOX_PREFIX) !== 0) return false;
    var notification = JSON.parse(properties[key]);
    return notification.visibility === 'private' &&
      notification.recipientSlackUserId === caller.requesterSlackUserId;
  }).map(function (key) {
    return JSON.parse(properties[key]);
  });
}

function acknowledgeOrbieNotification(notificationId) {
  if (!notificationId) throw new Error('notificationId is required');
  var properties = PropertiesService.getScriptProperties();
  var key = ORBIE_OUTBOX_PREFIX + notificationId;
  if (!properties.getProperty(key)) {
    throw new Error('Unknown notification ' + notificationId);
  }
  properties.deleteProperty(key);
  return { acknowledged: true, notificationId: notificationId };
}

function acknowledgeOrbieNotificationForCaller(payload) {
  var request = typeof payload === 'string' ? JSON.parse(payload) : (payload || {});
  var caller = parseCaller_(request);
  if (!request.notificationId) {
    throw new Error('notificationId is required');
  }
  var properties = PropertiesService.getScriptProperties();
  var key = ORBIE_OUTBOX_PREFIX + request.notificationId;
  var raw = properties.getProperty(key);
  if (!raw) throw new Error('Unknown notification ' + request.notificationId);
  var notification = JSON.parse(raw);
  if (notification.visibility !== 'private' ||
      notification.recipientSlackUserId !== caller.requesterSlackUserId) {
    throw new Error('Notification is not authorized for ' + caller.requesterSlackUserId);
  }
  properties.deleteProperty(key);
  return { acknowledged: true, notificationId: request.notificationId };
}

function processAgenda_(meeting, now, requesterSlackUserId) {
  validateMeeting_(meeting);
  var leadMin = meeting.notifyLeadMin == null ? 60 : Number(meeting.notifyLeadMin);
  var staleWindowMin = meeting.staleWindowMin == null
    ? 12 * 60
    : Number(meeting.staleWindowMin);
  var occurrence = findPendingAgendaOccurrence_(
    meeting,
    now,
    leadMin,
    staleWindowMin,
    requesterSlackUserId
  ) || getNextOccurrence_(meeting);
  if (!MeetingOpsPure.isWithinAgendaWindow(now, occurrence, leadMin, staleWindowMin)) {
    return;
  }

  var timeZone = meeting.timeZone || DEFAULT_TIME_ZONE;
  var date = MeetingOpsPure.dateKey(occurrence, timeZone);
  var docName = MeetingOpsPure.resolveDocName(meeting.docNameTemplate, occurrence, timeZone);
  var recordKey = AGENDA_RECORD_PREFIX + meeting.id + ':' + date;
  var properties = PropertiesService.getScriptProperties();
  var record = readJsonProperty_(properties, recordKey);
  if (!record) {
    var file = findDocument_(meeting.outputFolderId, docName);
    if (!file) {
      file = createDocumentFromTemplate_(meeting, docName);
    }
    record = {
      meetingId: meeting.id,
      occurrenceAt: occurrence.toISOString(),
      docId: file.getId(),
      docUrl: file.getUrl(),
      docName: docName,
      agendaNotified: false,
      notesNotified: false
    };
  }

  if (!MeetingOpsPure.wasNotificationDelivered(
    record,
    'agenda',
    requesterSlackUserId
  )) {
    var agendaText = '📋 ' + meeting.title + ' agenda is ready: ' + record.docUrl +
      '\nAttendees: ' + formatAttendees_(meeting.attendees);
    deliverNotification_(
      meeting,
      record,
      'agenda',
      agendaText,
      occurrence,
      recordKey,
      requesterSlackUserId
    );
    MeetingOpsPure.markNotificationDelivered(
      record,
      'agenda',
      requesterSlackUserId
    );
  }

  writeJsonProperty_(properties, recordKey, record);
  properties.setProperty(
    NEXT_OCCURRENCE_PREFIX + meeting.id,
    advanceOccurrence_(meeting, occurrence).toISOString()
  );
  return {
    meetingId: meeting.id,
    occurrenceAt: occurrence.toISOString(),
    docId: record.docId,
    docUrl: record.docUrl,
    notificationMode: meeting.notificationMode
  };
}

function processNotesNotification_(meeting, now, requesterSlackUserId) {
  validateMeeting_(meeting);
  var properties = PropertiesService.getScriptProperties();
  var prefix = AGENDA_RECORD_PREFIX + meeting.id + ':';
  var all = properties.getProperties();
  Object.keys(all).forEach(function (key) {
    if (key.indexOf(prefix) !== 0) return;
    var record = JSON.parse(all[key]);
    if (MeetingOpsPure.wasNotificationDelivered(
      record,
      'notes',
      requesterSlackUserId
    )) return;

    var occurrence = new Date(record.occurrenceAt);
    var delayMin = meeting.notesDelayMin == null
      ? Number(meeting.durationMin == null ? 60 : meeting.durationMin)
      : Number(meeting.notesDelayMin);
    if (!MeetingOpsPure.shouldPost(now, occurrence, delayMin)) return;

    var notesText = '✅ Notes from today\'s ' + meeting.title + ': ' + record.docUrl;
    deliverNotification_(
      meeting,
      record,
      'notes',
      notesText,
      occurrence,
      key,
      requesterSlackUserId
    );
    MeetingOpsPure.markNotificationDelivered(
      record,
      'notes',
      requesterSlackUserId
    );
    writeJsonProperty_(properties, key, record);
  });
}

function validateMeeting_(meeting) {
  [
    'id', 'title', 'sourceDocId', 'outputFolderId',
    'docNameTemplate', 'nextOccurrenceAt'
  ].forEach(function (field) {
    if (!meeting[field] || String(meeting[field]).indexOf('REPLACE_WITH_') === 0) {
      throw new Error('Missing meeting field ' + field + ' for ' + (meeting.id || 'unknown'));
    }
  });
  if (!Array.isArray(meeting.attendees)) {
    throw new Error('attendees must be an array for ' + meeting.id);
  }
  if (meeting.cadence !== 'weekly') {
    throw new Error('Only weekly cadence is supported in Layer 0 for ' + meeting.id);
  }
  if (meeting.visibility === 'public' &&
      (!meeting.notifyChannel || !meeting.notifyChannelName)) {
    throw new Error('public cadences require notifyChannel and notifyChannelName');
  }
  if (meeting.visibility === 'private' &&
      (!meeting.ownerSlackUserId || !meeting.notificationRecipients.length)) {
    throw new Error('private cadences require an owner and notification recipients');
  }
  if (isNaN(new Date(meeting.nextOccurrenceAt).getTime())) {
    throw new Error('nextOccurrenceAt must be an ISO timestamp for ' + meeting.id);
  }
}

function deliverNotification_(
  meeting,
  record,
  kind,
  text,
  occurrence,
  recordKey,
  requesterSlackUserId
) {
  queueOrbieNotification_(
    meeting,
    record,
    kind,
    text,
    occurrence,
    recordKey,
    requesterSlackUserId
  );
}

function queueOrbieNotification_(
  meeting,
  record,
  kind,
  text,
  occurrence,
  recordKey,
  requesterSlackUserId
) {
  if (meeting.visibility === 'public') assertAllowedChannel_(meeting);
  var timeZone = meeting.timeZone || DEFAULT_TIME_ZONE;
  var recipients = MeetingOpsPure.notificationRecipients(
    meeting,
    requesterSlackUserId
  );
  recipients.forEach(function (recipientSlackUserId) {
    var notificationId = MeetingOpsPure.notificationKey(
      meeting.id,
      occurrence,
      timeZone,
      kind,
      recipientSlackUserId
    );
    var payload = {
      notificationId: notificationId,
      kind: kind,
      meetingId: meeting.id,
      visibility: meeting.visibility,
      channelId: meeting.notifyChannel || null,
      channelName: meeting.notifyChannelName || null,
      recipientSlackUserId: recipientSlackUserId,
      recipientUserIds: recipientSlackUserId ? [recipientSlackUserId] : [],
      text: text,
      docId: record.docId,
      docUrl: record.docUrl,
      occurrenceAt: occurrence.toISOString(),
      recordKey: recordKey
    };
    PropertiesService.getScriptProperties().setProperty(
      ORBIE_OUTBOX_PREFIX + notificationId,
      JSON.stringify(payload)
    );
  });
}

function parseCaller_(payload) {
  var request = typeof payload === 'string' ? JSON.parse(payload) : (payload || {});
  if (!request.requesterSlackUserId) {
    throw new Error('requesterSlackUserId is required');
  }
  if (!request.requesterSlackTeamId) {
    throw new Error('requesterSlackTeamId is required');
  }
  if (request.requesterSlackTeamId !== WORLD_SLACK_TEAM_ID) {
    throw new Error('Unsupported Slack team ' + request.requesterSlackTeamId);
  }
  return request;
}

function uniqueStrings_(values) {
  var seen = {};
  return (values || []).map(String).filter(function (value) {
    if (!value || seen[value]) return false;
    seen[value] = true;
    return true;
  });
}

function getNextOccurrence_(meeting) {
  var properties = PropertiesService.getScriptProperties();
  var stored = properties.getProperty(NEXT_OCCURRENCE_PREFIX + meeting.id);
  return new Date(stored || meeting.nextOccurrenceAt);
}

function findPendingAgendaOccurrence_(
  meeting,
  now,
  leadMin,
  staleWindowMin,
  requesterSlackUserId
) {
  if (meeting.visibility !== 'private' || !requesterSlackUserId) return null;
  var prefix = AGENDA_RECORD_PREFIX + meeting.id + ':';
  var all = PropertiesService.getScriptProperties().getProperties();
  var pending = Object.keys(all).filter(function (key) {
    if (key.indexOf(prefix) !== 0) return false;
    var record = JSON.parse(all[key]);
    var occurrence = new Date(record.occurrenceAt);
    return MeetingOpsPure.isWithinAgendaWindow(
      now,
      occurrence,
      leadMin,
      staleWindowMin
    ) && !MeetingOpsPure.wasNotificationDelivered(
      record,
      'agenda',
      requesterSlackUserId
    );
  }).map(function (key) {
    return new Date(JSON.parse(all[key]).occurrenceAt);
  }).sort(function (left, right) {
    return right.getTime() - left.getTime();
  });
  return pending[0] || null;
}

function advanceOccurrence_(meeting, occurrence) {
  if (meeting.cadence === 'weekly') {
    return MeetingOpsPure.nextWeeklyOccurrence(occurrence);
  }
  throw new Error('Unsupported cadence ' + meeting.cadence);
}

function findDocument_(folderId, name) {
  var folder = DriveApp.getFolderById(folderId);
  var files = folder.getFilesByName(name);
  while (files.hasNext()) {
    var file = files.next();
    if (file.getMimeType() === MimeType.GOOGLE_DOCS && !file.isTrashed()) {
      return file;
    }
  }
  return null;
}

function createDocumentFromTemplate_(meeting, docName) {
  var target = DocumentApp.create(docName);
  var targetFile = DriveApp.getFileById(target.getId());
  try {
    var folder = DriveApp.getFolderById(meeting.outputFolderId);
    targetFile.moveTo(folder);
    copyTemplateTab_(
      meeting.sourceDocId,
      target.getId(),
      meeting.templateTabName || DEFAULT_TEMPLATE_TAB_TITLE
    );
    replacePlaceholders_(target.getId(), meeting);
    return targetFile;
  } catch (error) {
    targetFile.setTrashed(true);
    throw error;
  }
}

function copyTemplateTab_(sourceDocId, targetDocId, tabTitle) {
  var source = DocumentApp.openById(sourceDocId);
  var target = DocumentApp.openById(targetDocId);
  var sourceTab = findTabByTitle_(source.getTabs(), tabTitle);
  if (!sourceTab) throw new Error('Source document has no ' + tabTitle + ' tab');

  var targetTab = target.getTabs()[0].asDocumentTab();
  var targetBody = targetTab.getBody();
  targetBody.clear();
  var sourceBody = sourceTab.asDocumentTab().getBody();
  for (var index = 0; index < sourceBody.getNumChildren(); index += 1) {
    appendCopiedElement_(targetBody, sourceBody.getChild(index));
  }
}

function findTabByTitle_(tabs, title) {
  for (var index = 0; index < tabs.length; index += 1) {
    if (tabs[index].getTitle() === title) return tabs[index];
    var child = findTabByTitle_(tabs[index].getChildTabs(), title);
    if (child) return child;
  }
  return null;
}

function appendCopiedElement_(body, element) {
  var copy = element.copy();
  switch (element.getType()) {
    case DocumentApp.ElementType.PARAGRAPH:
      body.appendParagraph(copy);
      return;
    case DocumentApp.ElementType.LIST_ITEM:
      body.appendListItem(copy);
      return;
    case DocumentApp.ElementType.TABLE:
      body.appendTable(copy);
      return;
    case DocumentApp.ElementType.PAGE_BREAK:
      body.appendPageBreak(copy);
      return;
    case DocumentApp.ElementType.HORIZONTAL_RULE:
      body.appendHorizontalRule();
      return;
    case DocumentApp.ElementType.INLINE_IMAGE:
      body.appendImage(copy);
      return;
    default:
      throw new Error('Unsupported template tab element: ' + element.getType());
  }
}

function replacePlaceholders_(documentId, meeting) {
  var document = DocumentApp.openById(documentId);
  var body = document.getTabs()[0].asDocumentTab().getBody();
  var occurrence = getNextOccurrence_(meeting);
  var timeZone = meeting.timeZone || DEFAULT_TIME_ZONE;
  var replacements = {
    '{date}': MeetingOpsPure.dateKey(occurrence, timeZone),
    '{attendees}': (meeting.attendees || []).join(', '),
    '{prev_meeting_link}': meeting.previousMeetingLink || ''
  };
  Object.keys(replacements).forEach(function (placeholder) {
    body.replaceText(
      MeetingOpsPure.escapeRegExp(placeholder),
      replacements[placeholder]
    );
  });
}

function readJsonProperty_(properties, key) {
  var raw = properties.getProperty(key);
  return raw ? JSON.parse(raw) : null;
}

function writeJsonProperty_(properties, key, value) {
  properties.setProperty(key, JSON.stringify(value));
}

function withScriptLock_(callback) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}
