const form = document.querySelector('#measurement-form');
const input = document.querySelector('#qr-input');
const measurementModeSelect = document.querySelector('#measurement-mode');
const modeBadge = document.querySelector('#mode-badge');
const activityPhase = document.querySelector('#activity-phase');
const currentSerial = document.querySelector('#current-serial');
const currentValue = document.querySelector('#current-value');
const resultPill = document.querySelector('#result-pill');
const measurementHero = document.querySelector('#measurement-hero');
const heroResultDisplay = document.querySelector('#hero-result-display');
const activitySymbol = document.querySelector('#activity-symbol');
const activityTitle = document.querySelector('#activity-title');
const activityMessage = document.querySelector('#activity-message');
const downloadFeedback = document.querySelector('#download-feedback');
const activityCard = document.querySelector('#activity-card');
const recentMeasurementsBody = document.querySelector('#recent-measurements-body');
const comBadge = document.querySelector('#com-badge');
const wsBadge = document.querySelector('#ws-badge');
const systemState = document.querySelector('#system-state');
const refreshStatusButton = document.querySelector('#refresh-status-button');
const processRangeText = document.querySelector('#process-range-text');
const scanButton = document.querySelector('.scan-button');
const cancelSessionButton = document.querySelector('#cancel-session-button');
const resetSessionButton = document.querySelector('#reset-session-button');

const MODE_LABELS = {
  sigmastudio: 'Digital',
  analog: 'Analog',
};

let statusSocket = null;
let socketReconnectTimer = null;
let socketReconnectAttempts = 0;
let lastRenderedStatus = null;
let socketConnected = false;

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function focusScanInput() {
  if (document.hidden || input.disabled) {
    return;
  }

  input.focus();
  input.select();
}

function getModeLabel(mode) {
  return MODE_LABELS[mode] || mode;
}

function setInputLocked(isLocked) {
  input.disabled = isLocked;
  scanButton.disabled = isLocked;
}

function updateSessionControls(status) {
  const isSessionActive = Boolean(status?.sessionActive);
  const isCancellationRequested = Boolean(status?.sessionCancellationRequested);
  cancelSessionButton.disabled = !isSessionActive || isCancellationRequested;
}

function setSocketBadge(isConnected) {
  socketConnected = isConnected;
  wsBadge.textContent = isConnected ? 'WS LIVE' : 'WS RECONNECTING';
  wsBadge.className = `status-pill ${isConnected ? 'status-pill--online' : 'status-pill--offline'}`;
}

function scheduleSocketReconnect() {
  if (socketReconnectTimer !== null) {
    return;
  }

  const reconnectDelayMs = Math.min(5000, 1000 * (socketReconnectAttempts + 1));
  socketReconnectAttempts += 1;
  socketReconnectTimer = window.setTimeout(() => {
    socketReconnectTimer = null;
    connectStatusSocket();
  }, reconnectDelayMs);
}

function renderRecentMeasurements(items) {
  recentMeasurementsBody.innerHTML = items
    .map((item) => {
      const resultClass = item.result === 'PASS' ? 'result-pill--pass' : 'result-pill--fail';
      const valueClass = item.result === 'PASS' ? '' : 'measurement-value--fail';
      const timeText = item.measured_at ? item.measured_at.slice(11, 19) : '-';
      return `
        <tr>
          <td>${escapeHtml(timeText)}</td>
          <td><strong>${escapeHtml(item.qr_code)}</strong></td>
          <td class="${valueClass}">${escapeHtml(item.current_mA)}</td>
          <td><span class="result-pill ${resultClass}">${escapeHtml(item.result)}</span></td>
        </tr>
      `;
    })
    .join('');
}

function renderMeasurement(status) {
  const displayMeasurement = status.displayMeasurement || {};

  currentSerial.textContent = displayMeasurement.serialNumber || '-';
  currentValue.textContent = displayMeasurement.currentMilliampere || '0.00';
  heroResultDisplay.textContent = displayMeasurement.resultText || 'WAITING';
  resultPill.textContent = displayMeasurement.resultText || 'WAITING';
  resultPill.className = `result-pill result-pill--${displayMeasurement.resultTone || 'idle'}`;
  measurementHero.className = `measurement-hero measurement-hero--${displayMeasurement.resultTone || 'idle'}`;
}

function renderActivity(status) {
  const activity = status.activity || {};
  activitySymbol.textContent = activity.symbol || '⌛';
  activityTitle.textContent = activity.title || 'WAITING';
  activityMessage.textContent = activity.message || '스캔 대기 중 / Ready for next measurement';
  activityPhase.textContent = activity.phaseLabel || status.phaseLabel || 'IDLE';
  activityCard.className = `waiting-panel waiting-panel--${activity.tone || 'idle'}`;
}

function renderStatusMeta(status) {
  measurementModeSelect.value = status.selectedMode || 'sigmastudio';
  modeBadge.textContent = status.modeLabel || getModeLabel(status.selectedMode || 'sigmastudio');
  comBadge.textContent = status.comLabel;
  comBadge.className = `status-pill ${status.comConnected ? 'status-pill--online' : 'status-pill--offline'}`;
  systemState.textContent = status.comConnected ? 'SYSTEM NOMINAL' : 'SYSTEM CHECK REQUIRED';
  systemState.className = `footer-right ${status.comConnected ? 'footer-right--online' : 'footer-right--offline'}`;
  setInputLocked(Boolean(status.sessionActive));

  if (status.processRangeText) {
    processRangeText.textContent = status.processRangeText;
  }

  downloadFeedback.textContent = status.latestFeedbackMessage || '';
  updateSessionControls(status);
}

function renderStatus(status) {
  lastRenderedStatus = status;
  renderStatusMeta(status);
  renderActivity(status);
  renderMeasurement(status);
  renderRecentMeasurements(status.recentMeasurements || []);

  if (!status.sessionActive) {
    window.setTimeout(() => {
      focusScanInput();
    }, 0);
  }
}

async function synchronizeStatus() {
  const response = await fetch('/api/status');
  if (!response.ok) {
    throw new Error('Status sync failed.');
  }

  const status = await response.json();
  renderStatus(status);
}

async function updateSelectedMode(mode) {
  const response = await fetch('/api/status/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });

  if (!response.ok) {
    throw new Error('Mode update failed.');
  }

  return response.json();
}

async function submitMeasurement(qrCode) {
  const response = await fetch('/api/measurements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ qr_code: qrCode, mode: measurementModeSelect.value }),
  });

  if (!response.ok) {
    const errorPayload = await response.json();
    throw new Error(errorPayload.detail || 'Measurement request failed.');
  }

  return response.json();
}

async function requestSessionCancel() {
  const response = await fetch('/api/session/cancel', {
    method: 'POST',
  });

  if (!response.ok) {
    const errorPayload = await response.json();
    throw new Error(errorPayload.detail || 'Session cancel failed.');
  }

  return response.json();
}

function connectStatusSocket() {
  if (statusSocket !== null) {
    statusSocket.close();
  }

  setSocketBadge(false);
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  statusSocket = new WebSocket(`${protocol}//${window.location.host}/ws/status`);

  statusSocket.addEventListener('open', () => {
    socketReconnectAttempts = 0;
    setSocketBadge(true);
  });

  statusSocket.addEventListener('message', (event) => {
    const status = JSON.parse(event.data);
    renderStatus(status);
  });

  statusSocket.addEventListener('close', () => {
    setSocketBadge(false);
    scheduleSocketReconnect();
  });

  statusSocket.addEventListener('error', () => {
    setSocketBadge(false);
    statusSocket.close();
  });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const qrCode = input.value.trim();
  if (!qrCode) {
    focusScanInput();
    return;
  }

  if (input.disabled) {
    return;
  }

  setInputLocked(true);

  try {
    const payload = await submitMeasurement(qrCode);
    input.value = '';
    if (payload.status) {
      renderStatus(payload.status);
    }
  } catch (error) {
    setInputLocked(false);
    await synchronizeStatus().catch(() => {
      activityCard.className = 'waiting-panel waiting-panel--error';
      activityTitle.textContent = 'ERROR';
      activityMessage.textContent = error.message;
    });
  }
});

refreshStatusButton.addEventListener('click', async () => {
  await synchronizeStatus();
  focusScanInput();
});

cancelSessionButton.addEventListener('click', async () => {
  try {
    const payload = await requestSessionCancel();
    if (payload.status) {
      renderStatus(payload.status);
    }
  } catch (error) {
    await synchronizeStatus().catch(() => console.error(error));
  }
});

resetSessionButton.addEventListener('click', () => {
  if (lastRenderedStatus?.sessionActive) {
    cancelSessionButton.click();
    return;
  }

  input.value = '';
  if (lastRenderedStatus) {
    renderStatus(lastRenderedStatus);
  }
  focusScanInput();
});

measurementModeSelect.addEventListener('change', async () => {
  try {
    const payload = await updateSelectedMode(measurementModeSelect.value);
    if (payload.status) {
      renderStatus(payload.status);
    }
  } catch (error) {
    await synchronizeStatus().catch(() => console.error(error));
  }
});

window.addEventListener('load', async () => {
  connectStatusSocket();
  await synchronizeStatus().catch(() => {
    activityCard.className = 'waiting-panel waiting-panel--error';
    activityTitle.textContent = 'OFFLINE';
    activityMessage.textContent = '초기 상태를 불러오지 못했습니다.';
  });
  focusScanInput();
});
