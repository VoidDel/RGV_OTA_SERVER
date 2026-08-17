const STATUS_MAP = {
  'queued': '排队中',
  'published': '已下发',
  'received': '已接收',
  'downloading': '下载中',
  'verifying': '校验中',
  'writing': '写入中',
  'success': '成功',
  'failed': '失败',
  'rebooting': '重启中',
  'skipped': '已跳过',
  'unknown': '未知'
};

// HTML 转义：所有插入 innerHTML 的服务器/设备数据必须经过此函数，
// 防止存储型 XSS（设备可通过 MQTT 上报注入任意 message/rgv_id）。
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[c]);
}

async function api(path, options={}) {
  const r = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  });
  if (!r.ok) {
    let msg = '请求失败';
    try {
      const j = await r.json();
      msg = j.detail || msg;
    } catch(e) {}
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, type = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  
  // Reset content and status
  el.textContent = msg;
  
  // Force a CSS reflow to restart the progress bar timer animation smoothly
  el.classList.remove('show', 'success', 'error', 'info');
  void el.offsetWidth; 
  
  el.className = `toast show ${type}`;
  
  if (window.toastTimeout) {
    clearTimeout(window.toastTimeout);
  }
  window.toastTimeout = setTimeout(() => {
    el.className = 'toast hidden';
  }, 3000);
}

function badge(status) {
  const s = (status || 'unknown').toLowerCase().replace(/[^a-z]/g, '') || 'unknown';
  const text = STATUS_MAP[s] || status || '未知';
  return `<span class="badge ${s}"><span class="badge-dot"></span>${esc(text)}</span>`;
}

function progress(v) {
  const n = Math.max(0, Math.min(100, Number(v || 0)));
  let statusClass = '';
  if (n === 100) statusClass = 'complete';
  return `
    <div class="progress-wrapper">
      <div class="progress-bar-bg">
        <div class="progress-bar-fill ${statusClass}" style="width: ${n}%"></div>
      </div>
      <span class="progress-percentage">${n}%</span>
    </div>
  `;
}

function bytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n > 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function shortHash(h) {
  return h ? `${h.slice(0, 10)}...` : '';
}

async function refreshHealth() {
  try {
    const h = await api('/api/health');
    const p = document.getElementById('mqtt-pill');
    if (p) {
      const text = h.mqtt_connected ? `MQTT 已连接 (${h.mqtt_broker})` : `MQTT 未连接 ${h.mqtt_error || ''}`;
      p.className = `pill ${h.mqtt_connected ? 'ok' : 'bad'}`;
      p.innerHTML = `<span class="status-dot animate-pulse"></span><span class="status-text">${esc(text)}</span>`;
    }
  } catch (e) {}
}

refreshHealth();
setInterval(refreshHealth, 5000);

// Theme Switcher Logic
(function initThemeSwitcher() {
  const pref = localStorage.getItem('ota-theme') || 'system';
  const buttons = document.querySelectorAll('.theme-btn');
  
  function updateActiveButton(val) {
    buttons.forEach(btn => {
      if (btn.getAttribute('data-theme-val') === val) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
  }

  updateActiveButton(pref);

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      const val = btn.getAttribute('data-theme-val');
      localStorage.setItem('ota-theme', val);
      document.documentElement.setAttribute('data-theme-preference', val);
      
      let theme = val;
      if (val === 'system') {
        theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      }
      document.documentElement.setAttribute('data-theme', theme);
      updateActiveButton(val);
    });
  });

  // Listen to system theme changes
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    const currentPref = localStorage.getItem('ota-theme') || 'system';
    if (currentPref === 'system') {
      document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
    }
  });
})();
