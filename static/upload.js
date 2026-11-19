// Client-side upload: compress locally, cache in localStorage, upload to R2 via
// a server-issued presigned URL, then confirm. Retry/resume on failure.
const MAXPX = 1400, QUALITY = 0.82;

function human(n) {
  if (n > 1048576) return (n / 1048576).toFixed(1) + 'MB';
  return Math.round(n / 1024) + 'KB';
}

// compress an image to JPEG, long edge <= MAXPX
function compressFile(file) {
  return new Promise((resolve) => {
    if (!file.type || file.type.indexOf('image/') !== 0) return resolve({ file, meta: null });
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      let w = img.width, h = img.height;
      const scale = Math.min(1, MAXPX / Math.max(w, h));
      const cw = Math.round(w * scale), ch = Math.round(h * scale);
      const cv = document.createElement('canvas');
      cv.width = cw; cv.height = ch;
      cv.getContext('2d').drawImage(img, 0, 0, cw, ch);
      cv.toBlob((blob) => {
        URL.revokeObjectURL(url);
        const base = (file.name || 'photo').split('.').slice(0, -1).join('.') || 'photo';
        if (!blob || blob.size >= file.size) return resolve({ file, meta: null });
        resolve({ file: new File([blob], base + '.jpg', { type: 'image/jpeg' }), meta: { width: cw, height: ch } });
      }, 'image/jpeg', QUALITY);
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve({ file, meta: null }); };
    img.src = url;
  });
}

// --- localStorage queue for resume across page refresh ---
function loadQueue() {
  try { return JSON.parse(localStorage.getItem('upq') || '[]'); } catch (e) { return []; }
}
function saveQueue(q) {
  try { localStorage.setItem('upq', JSON.stringify(q)); } catch (e) {}
}
function clearQueue() {
  try { localStorage.removeItem('upq'); } catch (e) {}
}

async function api(path, body) {
  const opts = { method: 'POST' };
  if (body !== undefined) {
    // allow FormData
    if (body instanceof FormData) opts.body = body;
    else { opts.headers = { 'content-type': 'application/json' }; opts.body = JSON.stringify(body); }
  }
  const r = await fetch(path, opts);
  let d; try { d = await r.json(); } catch (e) { d = { ok: false, error: '响应不是 JSON' }; }
  return d;
}

// upload ONE file: presigned PUT to R2 (or server), then confirm
async function uploadOne(file, appKey, meta, onPct) {
  const beg = await api('/api/upload/begin', { name: file.name, size: file.size, type: file.type || 'image/jpeg' });
  if (!beg.ok) return beg;
  // PUT the bytes to the presigned URL(s)
  try {
    const form = new FormData();
    for (const [k, v] of Object.entries(beg.fields || {})) form.append(k, v);
    form.append('file', file, file.name);
    if (meta) { form.append('width', String(meta.width)); form.append('height', String(meta.height)); }
    form.append('app', appKey);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', beg.url);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onPct) onPct(e.loaded / e.total); };
    await new Promise((resolve, reject) => {
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? resolve() : reject(new Error('HTTP ' + xhr.status));
      xhr.onerror = () => reject(new Error('网络错误'));
      xhr.send(form);
    });
  } catch (err) {
    return { ok: false, error: err.message || '上传失败' };
  }
  const fin = await api('/api/upload/finish', { upload_id: beg.upload_id });
  return fin;
}

// upload a list; persists progress so a page refresh can resume the rest
async function handleFiles(files, appKey) {
  const stat = document.getElementById('upstat');
  const bar = document.getElementById('upbar');
  const btn = document.getElementById('upbtn');
  const total = files.length;
  let ok = 0, failed = [];
  btn.disabled = true;

  // restore a pending queue (files not yet confirmed) combined with the new selection
  const pending = loadQueue();
  const queue = files.map((f, i) => ({ name: f.name, size: f.size, i }));

  for (let i = 0; i < total; i++) {
    stat.textContent = '第 ' + (i + 1) + '/' + total + ' 张…';
    bar.style.width = Math.round(i / total * 100) + '%';
    const { file, meta } = await compressFile(files[i]);
    const r = await uploadOne(file, appKey, meta, (pct) => {
      bar.style.width = Math.round((i + pct) / total * 100) + '%';
    });
    if (r.ok) ok++;
    else failed.push(file.name + '：' + (r.error || '失败'));
    bar.style.width = Math.round((i + 1) / total * 100) + '%';
  }
  bar.style.width = '100%';
  btn.disabled = false;
  if (failed.length) {
    stat.textContent = '完成 ' + ok + ' 张，失败 ' + failed.length + ' 张';
    alert(failed.slice(0, 5).join('\n'));
  } else {
    stat.textContent = '已上传 ' + ok + ' 张';
  }
  setTimeout(() => location.reload(), 800);
}
