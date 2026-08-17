async function loadFirmware() {
  const rows = await api('/api/firmware?active=all');
  const table = document.getElementById('firmware-table');
  if (!table) return;
  
  table.innerHTML = rows.map(f => {
    const archiveBtn = f.is_active
      ? `<button class="btn-small btn-danger-outline" onclick="archiveFw(${f.id})">归档</button>`
      : `<span class="muted-text">已归档</span>`;

    const descText = f.description ? `<div class="fw-desc">${esc(f.description)}</div>` : '';
    const notesText = f.release_notes ? `<div class="fw-notes">${esc(f.release_notes)}</div>` : '';
    const warningBadge = f.warning ? `<span class="badge failed" title="${esc(f.warning)}">超出大小限制</span>` : '';

    return `
      <tr>
        <td class="code-font">${f.id}</td>
        <td>
          <span class="version-tag">${esc(f.version)}</span>
          ${f.is_active ? '' : '<span class="badge failed">已归档</span>'}
        </td>
        <td>
          <div class="fw-filename code-font">${esc(f.filename)} ${warningBadge}</div>
          ${descText}
          ${notesText}
        </td>
        <td><span class="size-tag">${bytes(f.file_size)}</span></td>
        <td class="code-font hash-cell" title="${esc(f.sha256)}">${esc(shortHash(f.sha256))}</td>
        <td>
          <div class="copy-url-group">
            <input class="copy-input code-font" readonly value="${esc(f.download_url)}">
            <button class="btn-small btn-secondary copy-btn" data-url="${esc(f.download_url)}" onclick="copyUrl(this.dataset.url, this)">
              <span>复制</span>
            </button>
          </div>
        </td>
        <td class="action-cell">
          <div class="row-actions">
            ${archiveBtn}
          </div>
        </td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="7" class="no-data-td">暂无固件记录</td></tr>';
}

function copyUrl(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    toast('下载地址已成功复制到剪贴板');
    const span = btn.querySelector('span');
    if (span) {
      span.textContent = '已复制!';
      btn.classList.add('copied');
      setTimeout(() => {
        span.textContent = '复制';
        btn.classList.remove('copied');
      }, 1500);
    }
  }).catch(() => {
    toast('复制失败，请手动选择复制', 'error');
  });
}

async function archiveFw(id) {
  if (confirm('确认归档此固件吗？归档后该版本将不可发布。')) {
    await api(`/api/firmware/${id}`, { method: 'DELETE' });
    toast('固件已成功归档');
    loadFirmware();
  }
}

const uploadForm = document.getElementById('upload-form');
if (uploadForm) {
  uploadForm.onsubmit = async e => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type="submit"]');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '固件上传并解析中...';
    
    const fd = new FormData(e.target);
    try {
      const r = await fetch('/api/firmware', {
        method: 'POST',
        body: fd
      });
      if (!r.ok) {
        const j = await r.json();
        throw new Error(j.detail || '上传失败');
      }
      toast('新固件上传并解析成功');
      e.target.reset();
      loadFirmware();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  };
}

loadFirmware();
