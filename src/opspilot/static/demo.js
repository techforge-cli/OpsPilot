document.addEventListener('DOMContentLoaded', function() {
  const progressDiv = document.getElementById('demo-progress');
  const logsDiv = document.getElementById('demo-logs');
  const logEntries = document.getElementById('demo-log-entries');
  const confirmBtn = document.getElementById('btn-confirm');
  const buttons = ['btn-tier1', 'btn-tier2', 'btn-tier3'].map(id => document.getElementById(id));

  const stages = ['analysis', 'guard', 'execute', 'verify', 'resolved'];
  const stageColors = {
    analysis: 'var(--secondary)',
    guard: 'var(--warning)',
    execute: 'var(--primary)',
    verify: 'var(--secondary)',
    resolved: 'var(--success)'
  };

  function setStage(stage, status) {
    const step = document.getElementById('step-' + stage);
    if (step) {
      if (status === 'active') {
        step.style.background = 'var(--warning)';
        step.style.boxShadow = '0 0 8px var(--warning)';
      } else if (status === 'done') {
        step.style.background = stageColors[stage] || 'var(--success)';
        step.style.boxShadow = 'none';
      } else if (status === 'blocked') {
        step.style.background = 'var(--danger)';
        step.style.boxShadow = 'none';
      }
    }
  }

  function resetProgress() {
    stages.forEach(s => setStage(s, 'pending'));
    document.getElementById('progress-label').textContent = 'Waiting...';
    progressDiv.style.display = 'none';
  }

  function showProgress() {
    progressDiv.style.display = 'block';
  }

  function addLogEntry(entry) {
    logsDiv.style.display = 'block';
    const div = document.createElement('div');
    div.style.marginBottom = '4px';
    div.style.color = 'var(--text-on-dark)';
    const time = new Date(entry.timestamp).toLocaleTimeString();
    div.innerHTML = '<span style="color: var(--text-dim);">[' + time + ']</span> ' +
      '<span style="color: var(--primary); font-weight: bold;">' + entry.stage + '</span>' +
      ' — ' + entry.message;
    logEntries.appendChild(div);
    div.scrollIntoView({ behavior: 'smooth' });
  }

  function processLogs(logs) {
    if (!logs || !Array.isArray(logs)) return;
    logs.forEach(entry => addLogEntry(entry));
  }

  function updateUIFromResponse(data) {
    if (!data) return;

    if (data.error) {
      document.getElementById('demo-results').innerHTML =
        '<p style="color: var(--danger);">Error: ' + data.error + '</p>';
      buttons.forEach(b => b.disabled = false);
      return;
    }

    showProgress();
    logEntries.innerHTML = '';
    logsDiv.style.display = 'none';
    processLogs(data.logs);

    const tier = data.tier;
    const status = data.status;

    if (status === 'pending_confirmation') {
      setStage('analysis', 'done');
      setStage('guard', 'active');
      document.getElementById('progress-label').textContent =
        'Tier ' + tier + ': AI proposes "' + (data.playbook_id || '') + '" — waiting for confirmation';
      if (confirmBtn) confirmBtn.style.display = 'inline-block';
    } else if (status === 'blocked' || status === 'blocked') {
      setStage('analysis', 'done');
      setStage('guard', 'active');
      if (data.reasons && data.reasons.length > 0) {
        data.reasons.forEach(() => {});
      }
      setStage('guard', 'failed');
      document.getElementById('progress-label').textContent =
        'Tier ' + tier + ': BLOCKED by safety guard — ' + (data.reasons || []).join(', ');
      buttons.forEach(b => b.disabled = false);
    } else if (status === 'resolved') {
      stages.forEach(s => setStage(s, 'done'));
      document.getElementById('progress-label').textContent =
        'Tier ' + tier + ': RESOLVED — incident closed and audited';
      buttons.forEach(b => b.disabled = false);
    } else if (data.stage === 'guard' || data.stage === 'execute' || data.stage === 'verify') {
      const currentStage = data.stage;
      const idx = stages.indexOf(currentStage);
      for (let i = 0; i < idx; i++) {
        setStage(stages[i], 'done');
      }
      setStage(currentStage, 'active');
      document.getElementById('progress-label').textContent =
        'Tier ' + tier + ': ' + currentStage + '...';
    }
  }

  const resultsDiv = document.getElementById('demo-results');
  if (resultsDiv) {
    resultsDiv.addEventListener('htmx:afterSwap', function(evt) {
      try {
        const data = JSON.parse(evt.detail.xhr.responseText);
        updateUIFromResponse(data);
      } catch (e) {}
    });
  }

  if (confirmBtn) {
    confirmBtn.addEventListener('click', function() {
      confirmBtn.style.display = 'none';
    });
  }
});
