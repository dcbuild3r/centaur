var AGENDA_RECORD_PREFIX = 'AGENDA_RECORD:';
var NEXT_OCCURRENCE_PREFIX = 'NEXT_OCCURRENCE:';
var ORBIE_OUTBOX_PREFIX = 'ORBIE_OUTBOX:';
var DEFAULT_TEMPLATE_TAB_TITLE = 'Template';
var DEFAULT_MEETING_NOTES_TAB_TITLE = 'Meeting Notes';
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
    if (request.documentEditorEmails !== undefined) {
      cadence.documentEditorEmails = request.documentEditorEmails;
    }
    var caller = parseCaller_(request);
    if (!MeetingOpsPure.isCadenceAuthorized(cadence, caller.requesterSlackUserId)) {
      throw new Error('Cadence is not authorized for ' + caller.requesterSlackUserId);
    }
    var now = request.now ? new Date(request.now) : new Date();
    var requesterSlackUserId = caller.requesterSlackUserId;
    var customInstructions = MeetingOpsPure.normalizeCustomInstructions(
      request.customInstructions
    );
    processNotesNotification_(cadence, now, requesterSlackUserId);
    return processAgenda_(cadence, now, requesterSlackUserId, {
      manual: true,
      customInstructions: customInstructions
    });
  });
}

// Orbie supplies the normalized Notion row after resolving its recipients
// against Slack. This keeps Notion and Slack credentials out of Apps Script,
// while the durable workflow remains the only production caller of this
// entrypoint.
function runScheduledCadenceJob(payload) {
  var request = typeof payload === 'string' ? JSON.parse(payload) : (payload || {});
  if (request.requesterSlackTeamId !== WORLD_SLACK_TEAM_ID) {
    throw new Error('Unsupported Slack team ' + request.requesterSlackTeamId);
  }
  if (request.scheduledByOrbie !== true || !request.cadence) {
    throw new Error('scheduledByOrbie and cadence are required');
  }
  return withScriptLock_(function () {
    var cadence = MeetingOpsPure.normalizeCadence(request.cadence);
    var manualByOwner = request.manualByOwner === true;
    var requesterSlackUserId = manualByOwner
      ? String(request.requesterSlackUserId || '')
      : null;
    if (manualByOwner && !MeetingOpsPure.isCadenceAuthorized(
      cadence,
      requesterSlackUserId
    )) {
      throw new Error('Cadence is not authorized for ' + requesterSlackUserId);
    }
    var occurrence = new Date(request.occurrenceAt);
    if (isNaN(occurrence.getTime())) {
      throw new Error('occurrenceAt must be an ISO timestamp');
    }
    validateMeeting_(cadence);
    processNotesNotification_(
      cadence,
      new Date(request.now || new Date()),
      requesterSlackUserId,
      !manualByOwner
    );
    return processAgenda_(cadence, occurrence, requesterSlackUserId, {
      manual: manualByOwner,
      scheduled: !manualByOwner,
      occurrence: occurrence,
      customInstructions: request.customInstructions
    });
  });
}

// Process notes for all already-created occurrences without creating the
// next agenda early. This is called on each scheduler tick so advancing a
// Notion Next date does not delay the previous meeting's notes notification.
function runScheduledNotificationsJob(payload) {
  var request = typeof payload === 'string' ? JSON.parse(payload) : (payload || {});
  if (request.requesterSlackTeamId !== WORLD_SLACK_TEAM_ID) {
    throw new Error('Unsupported Slack team ' + request.requesterSlackTeamId);
  }
  if (request.scheduledByOrbie !== true || !request.cadence) {
    throw new Error('scheduledByOrbie and cadence are required');
  }
  return withScriptLock_(function () {
    var cadence = MeetingOpsPure.normalizeCadence(request.cadence);
    validateMeeting_(cadence);
    processNotesNotification_(cadence, new Date(request.now || new Date()), null, true);
    return { status: 'notifications-processed', meetingId: cadence.id };
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
      (notification.recipientSlackUserId === caller.requesterSlackUserId ||
        (notification.channelId &&
          notification.requesterSlackUserId === caller.requesterSlackUserId));
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
  var isCallerRecipient = notification.recipientSlackUserId === caller.requesterSlackUserId;
  var isCallerChannelRequest = notification.channelId &&
    notification.requesterSlackUserId === caller.requesterSlackUserId;
  if (notification.visibility !== 'private' ||
      (!isCallerRecipient && !isCallerChannelRequest)) {
    throw new Error('Notification is not authorized for ' + caller.requesterSlackUserId);
  }
  properties.deleteProperty(key);
  return { acknowledged: true, notificationId: request.notificationId };
}

function processAgenda_(meeting, now, requesterSlackUserId, options) {
  options = options || {};
  validateMeeting_(meeting);
  var leadMin = meeting.notifyLeadMin == null ? 60 : Number(meeting.notifyLeadMin);
  var staleWindowMin = meeting.staleWindowMin == null
    ? 12 * 60
    : Number(meeting.staleWindowMin);
  var occurrenceSelection = options.occurrence ? {
    occurrence: options.occurrence,
    oneOffManual: false
  } : selectAgendaOccurrence_(
      meeting,
      now,
      leadMin,
      staleWindowMin,
      requesterSlackUserId,
      options.manual === true
    );
  if (!occurrenceSelection) {
    return;
  }
  var occurrence = occurrenceSelection.occurrence;
  var customInstructions = MeetingOpsPure.normalizeCustomInstructions(
    options.customInstructions
  );

  var timeZone = meeting.timeZone || DEFAULT_TIME_ZONE;
  var date = MeetingOpsPure.dateKey(occurrence, timeZone);
  var docName = MeetingOpsPure.resolveDocName(meeting.docNameTemplate, occurrence, timeZone);
  var recordKey = AGENDA_RECORD_PREFIX + meeting.id + ':' + date;
  var properties = PropertiesService.getScriptProperties();
  var record = readJsonProperty_(properties, recordKey);
  if (!record) {
    var file = findDocument_(meeting.outputFolderId, docName);
    if (!file) {
      file = createDocumentFromTemplate_(
        meeting,
        docName,
        occurrence,
        customInstructions
      );
    } else {
      try {
        prepareTemplateCopy_(file.getId(), meeting, occurrence);
      } catch (error) {
        supersedeMalformedDocument_(file);
        file = createDocumentFromTemplate_(
          meeting,
          docName,
          occurrence,
          customInstructions
        );
      }
    }
    record = {
      meetingId: meeting.id,
      occurrenceAt: occurrence.toISOString(),
      docId: file.getId(),
      docUrl: file.getUrl(),
      docName: docName,
      oneOffManual: occurrenceSelection.oneOffManual,
      agendaNotified: false,
      notesNotified: false
    };
    if (customInstructions) record.customInstructions = customInstructions;
    // Reserve the document for this cadence occurrence before permissions or
    // notification work. Those downstream operations can be retried without
    // cloning another template copy if they fail after Drive creation.
    writeJsonProperty_(properties, recordKey, record);
  } else {
    var recordedFile = DriveApp.getFileById(record.docId);
    var replaceRecordedDocument = recordedFile.isTrashed();
    if (!replaceRecordedDocument && recordedFile.getName() !== docName) {
      // A title edit does not make a structurally valid occurrence document
      // disposable. Restore the configured title in place so retries keep the
      // same durable document identity instead of producing another copy.
      recordedFile.setName(docName);
      record.docName = docName;
      writeJsonProperty_(properties, recordKey, record);
    }
    if (!replaceRecordedDocument) {
      try {
        assertTemplateCopyReady_(record.docId, meeting, false);
      } catch (error) {
        supersedeMalformedDocument_(recordedFile);
        replaceRecordedDocument = true;
      }
    }
    if (replaceRecordedDocument) {
      var replacement = createDocumentFromTemplate_(
        meeting,
        docName,
        occurrence,
        customInstructions
      );
      record.docId = replacement.getId();
      record.docUrl = replacement.getUrl();
      record.docName = docName;
      record.agendaNotified = false;
      record.agendaNotifiedRecipients = [];
      record.notesNotified = false;
      record.notesNotifiedRecipients = [];
      if (customInstructions) {
        record.customInstructions = customInstructions;
      } else {
        delete record.customInstructions;
      }
      // Persist the replacement before later validation and notification work
      // for the same reason as the first-copy reservation above.
      writeJsonProperty_(properties, recordKey, record);
    }
  }
  assertTemplateCopyReady_(record.docId, meeting, false);
  ensureDocumentEditors_(record.docId, meeting);

  if (!MeetingOpsPure.wasNotificationDelivered(
    record,
    'agenda',
    requesterSlackUserId
  )) {
    var agendaText = '📋 ' + meeting.title + ' agenda is ready: ' +
      slackDocumentLink_(record.docUrl) +
      '\nAttendees: ' + formatAttendees_(meeting.attendees);
    deliverNotification_(
      meeting,
      record,
      'agenda',
      agendaText,
      occurrence,
      recordKey,
      requesterSlackUserId,
      options.scheduled === true
    );
    MeetingOpsPure.markNotificationDelivered(
      record,
      'agenda',
      requesterSlackUserId
    );
  }

  writeJsonProperty_(properties, recordKey, record);
  if (!occurrenceSelection.oneOffManual && !options.scheduled) {
    properties.setProperty(
      NEXT_OCCURRENCE_PREFIX + meeting.id,
      advanceOccurrence_(meeting, occurrence).toISOString()
    );
  }
  var result = {
    meetingId: meeting.id,
    occurrenceAt: occurrence.toISOString(),
    docId: record.docId,
    docUrl: record.docUrl,
    notificationMode: meeting.notificationMode
  };
  if (record.customInstructions) {
    result.customInstructions = record.customInstructions;
  }
  return result;
}

function processNotesNotification_(meeting, now, requesterSlackUserId, scheduled) {
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

    var notesText = '✅ Notes from today\'s ' + meeting.title + ': ' +
      slackDocumentLink_(record.docUrl);
    deliverNotification_(
      meeting,
      record,
      'notes',
      notesText,
      occurrence,
      key,
      requesterSlackUserId,
      scheduled === true
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
  if (['weekly', 'bi-weekly', 'monthly', 'quarterly'].indexOf(meeting.cadence) === -1) {
    throw new Error('Unsupported cadence ' + meeting.cadence);
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
  requesterSlackUserId,
  scheduled
) {
  queueOrbieNotification_(
    meeting,
    record,
    kind,
    text,
    occurrence,
    recordKey,
    requesterSlackUserId,
    scheduled
  );
}

function queueOrbieNotification_(
  meeting,
  record,
  kind,
  text,
  occurrence,
  recordKey,
  requesterSlackUserId,
  scheduled
) {
  // Manual runs are already authenticated against the cadence owners. Keep
  // the destination allowlist only for unattended scheduled execution.
  if (meeting.visibility === 'public' && scheduled === true) {
    assertAllowedChannel_(meeting);
  }
  var timeZone = meeting.timeZone || DEFAULT_TIME_ZONE;
  var recipients = MeetingOpsPure.notificationRecipients(
    meeting,
    requesterSlackUserId,
    scheduled === true
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
      requesterSlackUserId: requesterSlackUserId || null,
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

function selectAgendaOccurrence_(
  meeting,
  now,
  leadMin,
  staleWindowMin,
  requesterSlackUserId,
  manual
) {
  if (manual) {
    var timeZone = meeting.timeZone || DEFAULT_TIME_ZONE;
    var sameDateRecord = findAgendaRecordForDate_(meeting, now, timeZone);
    if (sameDateRecord) {
      return {
        occurrence: new Date(sameDateRecord.occurrenceAt),
        oneOffManual: Boolean(sameDateRecord.oneOffManual)
      };
    }
  }

  var current = findCurrentAgendaOccurrence_(
    meeting,
    now,
    leadMin,
    staleWindowMin,
    requesterSlackUserId
  );
  if (current) {
    var currentRecord = findAgendaRecordForOccurrence_(meeting, current);
    return {
      occurrence: current,
      oneOffManual: Boolean(currentRecord && currentRecord.oneOffManual)
    };
  }

  if (manual) {
    return {
      occurrence: new Date(now.getTime()),
      oneOffManual: true
    };
  }

  var next = getNextOccurrence_(meeting);
  if (!MeetingOpsPure.isWithinAgendaWindow(now, next, leadMin, staleWindowMin)) {
    return null;
  }
  return { occurrence: next, oneOffManual: false };
}

function findAgendaRecordForOccurrence_(meeting, occurrence) {
  return findAgendaRecordForDate_(
    meeting,
    occurrence,
    meeting.timeZone || DEFAULT_TIME_ZONE
  );
}

function findAgendaRecordForDate_(meeting, date, timeZone) {
  var key = AGENDA_RECORD_PREFIX + meeting.id + ':' +
    MeetingOpsPure.dateKey(date, timeZone);
  return readJsonProperty_(
    PropertiesService.getScriptProperties(),
    key
  );
}

function findCurrentAgendaOccurrence_(
  meeting,
  now,
  leadMin,
  staleWindowMin,
  requesterSlackUserId
) {
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
    );
  }).map(function (key) {
    return new Date(JSON.parse(all[key]).occurrenceAt);
  }).sort(function (left, right) {
    return right.getTime() - left.getTime();
  });
  return pending[0] || null;
}

function advanceOccurrence_(meeting, occurrence) {
  if (typeof MeetingOpsPure.nextOccurrence === 'function') {
    return MeetingOpsPure.nextOccurrence(
      occurrence,
      meeting.cadence,
      meeting.timeZone || DEFAULT_TIME_ZONE
    );
  }
  return MeetingOpsPure.nextWeeklyOccurrence(occurrence);
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

function createDocumentFromTemplate_(meeting, docName, occurrence, customInstructions) {
  var folder = DriveApp.getFolderById(meeting.outputFolderId);
  var sourceFile = DriveApp.getFileById(meeting.sourceDocId);
  var targetFile = sourceFile.makeCopy(docName, folder);
  try {
    prepareTemplateCopy_(
      targetFile.getId(),
      meeting,
      occurrence,
      customInstructions
    );
    return targetFile;
  } catch (error) {
    targetFile.setTrashed(true);
    throw error;
  }
}

function slackDocumentLink_(url) {
  return '<' + String(url) + '|Open document>';
}

function ensureDocumentEditors_(documentId, meeting) {
  var emails = meeting.documentEditorEmails || [];
  if (!Array.isArray(emails)) {
    throw new Error('documentEditorEmails must be an array');
  }
  var normalized = uniqueStrings_(emails.map(function (email) {
    return String(email).trim().toLowerCase();
  }).filter(function (email) {
    return email;
  }));
  normalized.forEach(function (email) {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      throw new Error('documentEditorEmails contains an invalid email');
    }
  });
  if (!normalized.length) return;
  var file = DriveApp.getFileById(documentId);
  var existing = {};
  (file.getEditors ? file.getEditors() : []).forEach(function (editor) {
    var email = String(editor.getEmail ? editor.getEmail() : '').trim().toLowerCase();
    if (email) existing[email] = true;
  });
  var missing = normalized.filter(function (email) {
    return !existing[email];
  });
  if (missing.length) file.addEditors(missing);
}

function supersedeMalformedDocument_(file) {
  var suffix = ' — superseded malformed copy ' +
    Utilities.formatDate(new Date(), DEFAULT_TIME_ZONE, 'yyyy-MM-dd HH:mm:ss');
  file.setName(file.getName() + suffix);
}

function prepareTemplateCopy_(documentId, meeting, occurrence, customInstructions) {
  assertTemplateCopyReady_(documentId, meeting);
  var document = DocumentApp.openById(documentId);
  var notesTitle = meeting.notesTabName || DEFAULT_MEETING_NOTES_TAB_TITLE;
  var notesTab = findTabByTitle_(document.getTabs(), notesTitle);
  setMeetingDate_(
    notesTab.asDocumentTab().getBody(),
    occurrence,
    meeting.timeZone || DEFAULT_TIME_ZONE
  );
  insertCustomInstructions_(
    notesTab.asDocumentTab().getBody(),
    customInstructions
  );
  document.saveAndClose();
}

function insertCustomInstructions_(body, customInstructions) {
  var instructions = MeetingOpsPure.normalizeCustomInstructions(customInstructions);
  if (!instructions) return;
  body.insertParagraph(1, instructions);
}

function findTabByTitle_(tabs, title) {
  for (var index = 0; index < tabs.length; index += 1) {
    if (tabs[index].getTitle() === title) return tabs[index];
    var child = findTabByTitle_(tabs[index].getChildTabs(), title);
    if (child) return child;
  }
  return null;
}

function assertTemplateCopyReady_(documentId, meeting, compareSourceTopology) {
  var target = DocumentApp.openById(documentId);
  var source = DocumentApp.openById(meeting.sourceDocId);
  if (compareSourceTopology !== false) {
    var sourceTopology = tabTopology_(source.getTabs(), '');
    var targetTopology = tabTopology_(target.getTabs(), '');
    if (JSON.stringify(sourceTopology) !== JSON.stringify(targetTopology)) {
      throw new Error('Generated document does not preserve the source template tab tree');
    }
  }
  var notesTitle = meeting.notesTabName || DEFAULT_MEETING_NOTES_TAB_TITLE;
  var formatTitle = meeting.templateTabName || DEFAULT_TEMPLATE_TAB_TITLE;
  if (!findTabByTitle_(target.getTabs(), notesTitle)) {
    throw new Error('Template copy has no ' + notesTitle + ' tab');
  }
  if (!findTabByTitle_(target.getTabs(), formatTitle)) {
    throw new Error('Template copy has no ' + formatTitle + ' tab');
  }
  [notesTitle, formatTitle].forEach(function (title) {
    var sourceTab = findTabByTitle_(source.getTabs(), title);
    var targetTab = findTabByTitle_(target.getTabs(), title);
    assertTabStructurePreserved_(sourceTab, targetTab, title);
  });
}

function assertTabStructurePreserved_(sourceTab, targetTab, title) {
  if (!sourceTab) throw new Error('Source template has no ' + title + ' tab');
  var sourceSignature = bodyStructureSignature_(sourceTab.asDocumentTab().getBody());
  var targetSignature = bodyStructureSignature_(targetTab.asDocumentTab().getBody());
  if (targetSignature.children < sourceSignature.children ||
      targetSignature.tables < sourceSignature.tables) {
    throw new Error(title + ' tab has lost source template structure');
  }
}

function bodyStructureSignature_(body) {
  var signature = { children: body.getNumChildren(), tables: 0 };
  for (var index = 0; index < body.getNumChildren(); index += 1) {
    if (String(body.getChild(index).getType()) === 'TABLE') signature.tables += 1;
  }
  return signature;
}

function tabTopology_(tabs, parentPath) {
  var topology = [];
  for (var index = 0; index < tabs.length; index += 1) {
    var path = parentPath + '/' + tabs[index].getTitle();
    topology.push(path);
    topology = topology.concat(tabTopology_(tabs[index].getChildTabs(), path));
  }
  return topology;
}

function setMeetingDate_(body, occurrence, timeZone) {
  var date = Utilities.formatDate(occurrence, timeZone, 'MMM d, yyyy');
  if (body.getNumChildren() === 0) {
    throw new Error('Meeting Notes template has no date paragraph');
  }
  var first = body.getChild(0);
  if (first.getType() !== DocumentApp.ElementType.PARAGRAPH) {
    throw new Error('Meeting Notes template does not start with a date paragraph');
  }
  if (first.getText() === date) return;
  // Google Docs date smart chips are copied natively but DocumentApp exposes
  // their paragraph text as empty. Replacing that one leading paragraph turns
  // the stale chip into the occurrence date without touching the notes layout.
  if (first.getText() === '') {
    first.asParagraph().setText(date);
    return;
  }
  if (!/^[A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4}$/.test(first.getText())) {
    throw new Error('Meeting Notes template starts with an unrecognized date');
  }
  first.asParagraph().setText(date);
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

if (typeof module !== 'undefined') {
  module.exports = {
    assertTemplateCopyReady_: assertTemplateCopyReady_,
    bodyStructureSignature_: bodyStructureSignature_,
    createDocumentFromTemplate_: createDocumentFromTemplate_,
    findCurrentAgendaOccurrence_: findCurrentAgendaOccurrence_,
    insertCustomInstructions_: insertCustomInstructions_,
    prepareTemplateCopy_: prepareTemplateCopy_,
    processAgenda_: processAgenda_,
    runCadenceJob: runCadenceJob,
    runScheduledCadenceJob: runScheduledCadenceJob,
    runScheduledNotificationsJob: runScheduledNotificationsJob,
    setMeetingDate_: setMeetingDate_
  };
}
