var CADENCE_CONFIG_PROPERTY = 'CADENCE_CONFIG_JSON';
var MEETING_CONFIG_PROPERTY = 'MEETING_CONFIG_JSON';
var WF_CHANNEL_ALLOWLIST_PROPERTY = 'ALLOWED_WF_CHANNEL_IDS';

function getMeetingConfig_() {
  var raw = PropertiesService.getScriptProperties().getProperty(CADENCE_CONFIG_PROPERTY) ||
    PropertiesService.getScriptProperties().getProperty(MEETING_CONFIG_PROPERTY);
  if (!raw) {
    throw new Error('CADENCE_CONFIG_JSON is not configured in Script Properties');
  }

  var cadences = JSON.parse(raw);
  if (!Array.isArray(cadences)) {
    throw new Error('CADENCE_CONFIG_JSON must contain an array');
  }
  return cadences.map(function (cadence) {
    return MeetingOpsPure.normalizeCadence(cadence);
  });
}

function configureMeetingOps_(json) {
  var cadences = typeof json === 'string' ? JSON.parse(json) : json;
  if (!Array.isArray(cadences)) {
    throw new Error('Cadence configuration must be an array');
  }
  PropertiesService.getScriptProperties().setProperty(
    CADENCE_CONFIG_PROPERTY,
    JSON.stringify(cadences.map(function (cadence) {
      return MeetingOpsPure.normalizeCadence(cadence);
    }))
  );
}

function getScriptProperty_(name) {
  return PropertiesService.getScriptProperties().getProperty(name) || '';
}

function assertAllowedChannel_(meeting) {
  var allowlist = getScriptProperty_(WF_CHANNEL_ALLOWLIST_PROPERTY)
    .split(',')
    .map(function (value) { return value.trim(); })
    .filter(Boolean);

  if (!allowlist.length || allowlist.indexOf(meeting.notifyChannel) === -1) {
    throw new Error(
      'notifyChannel is not in ALLOWED_WF_CHANNEL_IDS for meeting ' + meeting.id
    );
  }

  var channelName = String(meeting.notifyChannelName || '');
  if (/wf[-_]?tfh/i.test(channelName) || !/^#?wf[-_]/i.test(channelName)) {
    throw new Error('notifyChannelName must identify an allowed WF channel');
  }
}

function formatAttendees_(attendees) {
  return (attendees || []).map(function (email) {
    return '<mailto:' + email + '|' + email + '>';
  }).join(', ');
}
