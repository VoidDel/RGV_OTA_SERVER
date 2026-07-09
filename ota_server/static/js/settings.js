const form = document.getElementById('settings-form');

function checkUrl() {
  if (!form) return;
  const v = form.public_base_url.value;
  const warningEl = document.getElementById('url-warning');
  if (warningEl) {
    const isLocal = v.includes('localhost') || v.includes('127.0.0.1');
    warningEl.classList.toggle('hidden', !isLocal);
  }
}

async function loadSettings() {
  if (!form) return;
  try {
    const s = await api('/api/settings');
    for (const [k, v] of Object.entries(s)) {
      if (form.elements[k]) {
        form.elements[k].value = v;
      }
    }
    checkUrl();
  } catch (err) {
    toast('加载配置失败: ' + err.message, 'error');
  }
}

if (form) {
  form.public_base_url.oninput = checkUrl;
  form.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    
    // Convert port to integer
    if (data.mqtt_port) {
      data.mqtt_port = parseInt(data.mqtt_port, 10);
    }
    
    try {
      await api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(data)
      });
      toast('配置已成功保存，MQTT 服务正在后台重新连接...', 'success');
      refreshHealth();
    } catch (err) {
      toast('保存失败: ' + err.message, 'error');
    }
  };
  
  loadSettings();
}
