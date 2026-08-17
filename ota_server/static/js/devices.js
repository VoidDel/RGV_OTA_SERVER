const selectedDevices = new Set();
let deviceRows = [];

async function loadFirmwareOptions() {
  const rows = await api('/api/firmware');
  const select = document.getElementById('bulk-firmware');
  if (select) {
    select.innerHTML = rows.map(f => `<option value="${f.id}">${esc(f.version)} (${bytes(f.file_size)}) - ${esc(f.description || f.filename)}</option>`).join('') || '<option value="">暂无固件</option>';
  }
}

async function loadDevices() {
  deviceRows = await api('/api/devices');
  const grid = document.getElementById('device-grid');
  if (!grid) return;
  
  grid.innerHTML = deviceRows.map(d => {
    const isSelected = selectedDevices.has(d.rgv_id);
    const lastSeenStr = d.last_seen_at ? d.last_seen_at.replace('T', ' ').split('.')[0] : '--';
    return `
      <div class="device-card ${isSelected ? 'selected' : ''}" data-rgv="${esc(d.rgv_id)}" onclick="toggleDeviceSelection(event, this.dataset.rgv)">
        <div class="device-card-header">
          <label class="checkbox-container" onclick="event.stopPropagation()">
            <input type="checkbox" class="device-check" value="${esc(d.rgv_id)}" ${isSelected ? 'checked' : ''} onchange="onDeviceCheckChange(this)">
            <span class="checkbox-checkmark"></span>
            <span class="device-id">${esc(d.rgv_id)}</span>
          </label>
          <div class="device-status-badge">
            ${badge(d.last_status || 'unknown')}
          </div>
        </div>
        <div class="device-card-body">
          <div class="device-name">${esc(d.name || '未命名车 (已自动注册)')}</div>
          <div class="device-meta-list">
            <div class="device-meta-item">
              <span class="label">当前运行版本:</span>
              <span class="value code-font">${esc(d.current_version || '--')}</span>
            </div>
            <div class="device-meta-item progress-meta">
              <span class="label">OTA 进度:</span>
              <span class="value">${progress(d.last_progress || 0)}</span>
            </div>
            ${d.last_message ? `<div class="device-error-msg">${esc(d.last_message)}</div>` : ''}
          </div>
        </div>
        <div class="device-card-footer">
          <i class="bi bi-clock" style="font-size: 11px;"></i>
          <span>最后在线: ${esc(lastSeenStr)}</span>
        </div>
      </div>
    `;
  }).join('') || '<div class="no-data">暂无注册设备，等待设备上报或手动添加</div>';
}

function toggleDeviceSelection(event, rgvId) {
  // Prevent selection toggle if user clicked on interactive elements
  if (event.target.closest('input') || event.target.closest('.checkbox-container')) return;
  const isSelected = selectedDevices.has(rgvId);
  if (isSelected) {
    selectedDevices.delete(rgvId);
  } else {
    selectedDevices.add(rgvId);
  }
  loadDevices();
}

function onDeviceCheckChange(cb) {
  if (cb.checked) {
    selectedDevices.add(cb.value);
  } else {
    selectedDevices.delete(cb.value);
  }
  loadDevices();
}

async function deploy(payload) {
  const firmwareId = Number(document.getElementById('bulk-firmware').value || 0);
  if (!firmwareId) {
    toast('请选择固件版本', 'error');
    return;
  }
  payload.firmware_id = firmwareId;
  payload.force = document.getElementById('bulk-force').checked;
  payload.reboot = document.getElementById('bulk-reboot').checked;
  
  try {
    const result = await api('/api/deployments', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    
    const resultHtml = result.deployments.map(d => `
      <div class="bulk-result-item">
        <span class="rgv-id">${esc(d.rgv_id)}</span>
        <span class="divider">:</span>
        ${badge(d.status)}
        <span class="msg">${esc(d.message || '指令发布成功')}</span>
      </div>
    `).join('');
    
    document.getElementById('bulk-result').innerHTML = `
      <div class="bulk-result-success-box">
        <h3>下发结果汇总</h3>
        <div class="bulk-result-list">${resultHtml}</div>
      </div>
    `;
    toast('OTA 任务已批量创建');
    loadDevices();
  } catch (err) {
    toast(err.message, 'error');
  }
}

document.getElementById('device-form').onsubmit = async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api('/api/devices', {
      method: 'POST',
      body: JSON.stringify({
        rgv_id: fd.get('rgv_id'),
        name: fd.get('name')
      })
    });
    toast('设备已保存');
    e.target.reset();
    loadDevices();
  } catch (err) {
    toast(err.message, 'error');
  }
};

document.getElementById('deploy-selected').onclick = () => {
  const rgvIds = [...selectedDevices];
  if (!rgvIds.length) {
    toast('请先在下方列表中选择设备', 'error');
    return;
  }
  deploy({ rgv_ids: rgvIds });
};

document.getElementById('deploy-all').onclick = () => {
  if (confirm('确定要向全部已注册设备推送此 OTA 更新吗？')) {
    deploy({ target: 'all' });
  }
};

document.getElementById('select-all-devices').onclick = () => {
  deviceRows.forEach(d => selectedDevices.add(d.rgv_id));
  loadDevices();
};

document.getElementById('clear-device-selection').onclick = () => {
  selectedDevices.clear();
  loadDevices();
};

loadFirmwareOptions();
loadDevices();
setInterval(loadDevices, 4000);
