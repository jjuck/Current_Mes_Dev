const form = document.querySelector('#measurement-form');
const input = document.querySelector('#qr-input');
const currentSerial = document.querySelector('#current-serial');
const currentValue = document.querySelector('#current-value');
const resultPill = document.querySelector('#result-pill');
const measurementHero = document.querySelector('#measurement-hero');
const heroResultDisplay = document.querySelector('#hero-result-display');
const activityTitle = document.querySelector('#activity-title');
const activityMessage = document.querySelector('#activity-message');
const downloadFeedback = document.querySelector('#download-feedback');
const activityCard = document.querySelector('#activity-card');
const recentMeasurementsBody = document.querySelector('#recent-measurements-body');
const comBadge = document.querySelector('#com-badge');
const systemState = document.querySelector('#system-state');
const refreshStatusButton = document.querySelector('#refresh-status-button');
const processRangeText = document.querySelector('#process-range-text');
const scanButton = document.querySelector('.scan-button');

let inputRefocusDelayMs = 5000;
let countdownTimer = null;
let countdownValue = 0;

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

function setInputLocked(isLocked) {
  input.disabled = isLocked;
  scanButton.disabled = isLocked;
}

function setWaitingState() {
  activityTitle.textContent = 'WAITING';
  activityMessage.textContent = '스캔 대기 중 / Ready for next measurement';
}

function renderCountdown(secondsRemaining) {
  activityTitle.textContent = 'NEXT SCAN';
  activityMessage.textContent = `다음 스캔까지 ${secondsRemaining}초`;
}

function clearCountdownTimer() {
  window.clearInterval(countdownTimer);
  countdownTimer = null;
}

function startInputCountdown() {
  clearCountdownTimer();
  countdownValue = Math.max(1, Math.round(inputRefocusDelayMs / 1000));
  setInputLocked(true);
  renderCountdown(countdownValue);

  countdownTimer = window.setInterval(() => {
    countdownValue -= 1;
    if (countdownValue <= 0) {
      clearCountdownTimer();
      setInputLocked(false);
      setWaitingState();
      input.value = '';
      focusScanInput();
      return;
    }

    renderCountdown(countdownValue);
  }, 1000);
}

function renderMeasurement(measurement) {
  if (!measurement) {
    return;
  }

  currentSerial.textContent = measurement.qr_code;
  currentValue.textContent = measurement.current_mA;
  heroResultDisplay.textContent = measurement.result;
  resultPill.textContent = measurement.result;
  resultPill.className = `result-pill ${measurement.result === 'PASS' ? 'result-pill--pass' : 'result-pill--fail'}`;
  measurementHero.className = `measurement-hero ${measurement.result === 'PASS' ? 'measurement-hero--pass' : 'measurement-hero--fail'}`;
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

function renderStatus(status) {
  inputRefocusDelayMs = (status.inputRefocusDelaySeconds || 5) * 1000;
  comBadge.textContent = status.comLabel;
  comBadge.className = `status-pill ${status.comConnected ? 'status-pill--online' : 'status-pill--offline'}`;
  systemState.textContent = status.comConnected ? 'SYSTEM NOMINAL' : 'SYSTEM CHECK REQUIRED';
  systemState.className = `footer-right ${status.comConnected ? 'footer-right--online' : 'footer-right--offline'}`;

  if (status.processRangeText) {
    processRangeText.textContent = status.processRangeText;
  }

  if (status.lastDownload && status.lastDownload.message) {
    downloadFeedback.textContent = status.lastDownload.message;
  }

  if (status.lastMeasurement) {
    renderMeasurement(status.lastMeasurement);
    return;
  }

  heroResultDisplay.textContent = 'WAITING';
  setWaitingState();
}

async function fetchStatus() {
  const response = await fetch('/api/status');
  const status = await response.json();
  renderStatus(status);
}

async function fetchRecentMeasurements() {
  const response = await fetch('/api/measurements/recent');
  const payload = await response.json();
  renderRecentMeasurements(payload.items || []);
}

async function submitMeasurement(qrCode) {
  activityTitle.textContent = 'MEASURING';
  activityMessage.textContent = '측정 진행 중 / Measurement in progress';

  const response = await fetch('/api/measurements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ qr_code: qrCode }),
  });

  if (!response.ok) {
    const errorPayload = await response.json();
    throw new Error(errorPayload.detail || 'Measurement request failed.');
  }

  const payload = await response.json();
  renderMeasurement(payload.measurement);
  renderRecentMeasurements(payload.recent || []);
  renderStatus(payload.status || {});
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
    await submitMeasurement(qrCode);
    startInputCountdown();
  } catch (error) {
    clearCountdownTimer();
    activityTitle.textContent = 'ERROR';
    activityMessage.textContent = error.message;
    heroResultDisplay.textContent = 'FAIL';
    resultPill.textContent = 'FAIL';
    resultPill.className = 'result-pill result-pill--fail';
    measurementHero.className = 'measurement-hero measurement-hero--fail';
    setInputLocked(false);
    focusScanInput();
  }
});

refreshStatusButton.addEventListener('click', async () => {
  await fetchStatus();
  focusScanInput();
});

window.addEventListener('load', async () => {
  await Promise.all([fetchStatus(), fetchRecentMeasurements()]);
  setWaitingState();
  focusScanInput();
});
