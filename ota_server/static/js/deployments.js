async function loadDeployments() {
  const rows = await api('/api/deployments?limit=200');
  const table = document.getElementById('deployments-table');
  if (!table) return;
  
  table.innerHTML = rows.map(d => `
    <tr>
      <td class="code-font">${d.id}</td>
      <td><strong class="color-primary">${esc(d.rgv_id)}</strong></td>
      <td>
        <span class="version-tag">${esc(d.firmware_version)}</span>
        <div class="fw-filename-sub code-font">${esc(d.firmware_filename)}</div>
      </td>
      <td>${badge(d.status)}</td>
      <td>${progress(d.progress)}</td>
      <td><span class="topic-tag code-font">${esc(d.mqtt_topic || '--')}</span></td>
      <td class="table-msg">${esc(d.message || '--')}</td>
      <td class="action-cell">
        <button class="btn-small btn-secondary" onclick="retry(${d.id})">重试</button>
      </td>
    </tr>
  `).join('') || '<tr><td colspan="8" class="no-data-td">暂无部署历史记录</td></tr>';
}

async function retry(id) {
  if (confirm(`确定要重新发布部署 ID 为 ${id} 的 OTA 升级指令吗？`)) {
    try {
      await api(`/api/deployments/${id}/retry`, { method: 'POST' });
      toast('OTA 升级指令已重新发布');
      loadDeployments();
    } catch (e) {
      toast(e.message, 'error');
    }
  }
}

loadDeployments();
setInterval(loadDeployments, 3000);
