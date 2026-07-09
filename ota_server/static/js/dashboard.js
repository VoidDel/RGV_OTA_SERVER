async function loadDashboard() {
  const [health, fw, dev, dep, events] = await Promise.all([
    api('/api/health'),
    api('/api/firmware'),
    api('/api/devices'),
    api('/api/deployments?limit=10'),
    api('/api/events/recent?limit=20')
  ]);

  const mqttStat = document.getElementById('stat-mqtt');
  if (mqttStat) {
    mqttStat.textContent = health.mqtt_connected ? '正常' : '异常';
    mqttStat.className = health.mqtt_connected ? 'status-text ok' : 'status-text bad';
  }
  
  const brokerStat = document.getElementById('stat-broker');
  if (brokerStat) {
    brokerStat.textContent = health.mqtt_broker || '--';
  }
  
  const fwStat = document.getElementById('stat-fw');
  if (fwStat) fwStat.textContent = fw.length;
  
  const devStat = document.getElementById('stat-dev');
  if (devStat) devStat.textContent = dev.length;
  
  const deployStat = document.getElementById('stat-deploy');
  if (deployStat) deployStat.textContent = dep.length;

  const sf = document.getElementById('quick-firmware');
  if (sf) {
    sf.innerHTML = fw.map(x => `<option value="${x.id}">${x.version} - ${x.description || x.filename}</option>`).join('') || '<option value="">无可用固件</option>';
  }
  
  const sd = document.getElementById('quick-device');
  if (sd) {
    sd.innerHTML = dev.map(x => `<option value="${x.rgv_id}">${x.rgv_id} ${x.name ? '(' + x.name + ')' : ''}</option>`).join('') || '<option value="">无注册设备</option>';
  }

  const eventsEl = document.getElementById('events');
  if (eventsEl) {
    eventsEl.innerHTML = events.map(e => {
      const timeStr = e.created_at ? e.created_at.replace('T', ' ').split('.')[0] : '--';
      return `
        <div class="event-item">
          <div class="event-header">
            <span class="event-id code-font">${e.rgv_id || 'SYSTEM'}</span>
            <span class="event-time">${timeStr}</span>
          </div>
          <div class="event-body">
            <span class="event-msg">${e.message || ''}</span>
            <div class="event-badge">${badge(e.status)}</div>
          </div>
        </div>
      `;
    }).join('') || '<div class="no-data">暂无最新运行事件</div>';
  }

  const depTable = document.getElementById('deployments-table');
  if (depTable) {
    depTable.innerHTML = dep.map(d => `
      <tr>
        <td class="code-font">${d.id}</td>
        <td><strong class="color-primary">${d.rgv_id}</strong></td>
        <td><span class="version-tag">${d.firmware_version}</span></td>
        <td>${badge(d.status)}</td>
        <td>${progress(d.progress)}</td>
        <td class="table-msg">${d.message || '--'}</td>
      </tr>
    `).join('') || '<tr><td colspan="6" class="no-data-td">暂无部署记录</td></tr>';
  }
}

const deployBtn = document.getElementById('quick-deploy');
if (deployBtn) {
  deployBtn.onclick = async () => {
    const firmware_id = Number(document.getElementById('quick-firmware').value);
    const rgv = document.getElementById('quick-device').value;
    if (!firmware_id || !rgv) {
      toast('请选择固件和目标设备', 'error');
      return;
    }
    try {
      await api('/api/deployments', {
        method: 'POST',
        body: JSON.stringify({
          firmware_id,
          rgv_ids: [rgv],
          force: document.getElementById('quick-force').checked,
          reboot: document.getElementById('quick-reboot').checked
        })
      });
      toast('OTA 推送指令已发布成功');
      loadDashboard();
    } catch (e) {
      toast(e.message, 'error');
    }
  };
}

loadDashboard();
setInterval(loadDashboard, 3000);
