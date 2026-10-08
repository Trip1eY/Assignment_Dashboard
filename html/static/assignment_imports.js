/* Files stay local to this dashboard server; ZIP/RAR/7z are never unpacked. */
'use strict';
window.mountAssignmentImport = function (root, assignment, options) {
  if (!root || !assignment.id) return;
  const escape = options.escapeHtml;
  const aid = assignment.id;
  const key = 'assignment-import-request:' + aid;
  const dropTarget = root.closest('.card') || root;
  const storedRequest = value => {
    try { if (value === null) sessionStorage.removeItem(key); else if (value) sessionStorage.setItem(key, value); else return sessionStorage.getItem(key); } catch { /* Upload still works without browser storage. */ }
    return '';
  };
  let items = [], students = [], busy = false, message = '正在读取导入状态…', failedFiles = null;
  root.classList.add('assignment-import');
  const $ = role => root.querySelector(`[data-import-role="${role}"]`);
  root.innerHTML = `<div class="ai-drop" data-import-role="drop" tabindex="0" role="button" aria-label="拖入或选择当前作业文件">
    <strong>拖入作业文件，自动识别提交学生</strong><span>归入：${escape([assignment.subject_group || assignment.subject, assignment.experiment || assignment.name].filter(Boolean).join(' · '))}</span>
    <span>支持多文件；单文件不超过 50 MB；压缩包直接收录，不解压。</span>
    <button type="button" data-import-role="choose">选择文件</button><input type="file" multiple hidden data-import-role="files">
  </div><div class="ai-progress" data-import-role="progress" role="status" aria-live="polite"></div>
  <div class="ai-results" data-import-role="results"></div>`;
  function render() {
    if (!root.isConnected) return;
    $('progress').textContent = message;
    $('choose').disabled = busy || !students.some(s => !s.disabled);
    $('drop').setAttribute('aria-busy', String(busy));
    const labels = { imported: '已入库', duplicate: '已收录', pending: '待确认', error: '未成功', discarded: '已取消' };
    const actionable = items.filter(i => i.status === 'pending' || i.status === 'error');
    const complete = items.filter(i => i.status !== 'pending' && i.status !== 'error').slice(0, 50);
    const rows = [...actionable, ...complete];
    const imported = items.filter(i => i.status === 'imported').length;
    $('results').innerHTML = `${items.length ? `<div class="ai-result-head"><strong>导入结果</strong><span>已入库 ${imported} 个 · 待处理 ${actionable.length} 个</span></div>` : ''}${rows.map(item => {
      const pending = item.status === 'pending' || item.status === 'error';
      const candidates = (item.candidates || []).map(c => `${c.name}${c.student_id ? '（' + c.student_id + '）' : ''}：${(c.reasons || []).join('、')}`).join('；');
      const choices = students.map(s => `<option value="${escape(s.ref)}" ${s.disabled ? 'disabled' : ''}>${escape(s.name)}${s.student_id ? ' · ' + escape(s.student_id) : ''}${s.disabled ? '（同名，需先区分名单）' : ''}</option>`).join('');
      return `<div class="ai-result ${escape(item.status)}" data-import-item="${escape(item.id)}" data-batch="${escape(item.batch_id)}">
        <div class="ai-result-copy"><strong>${escape(item.name)}</strong><span>${escape(item.student || '')} <em>${escape(labels[item.status] || item.status)}</em></span>
          <p>${escape(item.message || '')}${item.warning ? ' · ' + escape(item.warning) : ''}</p>${pending && candidates ? `<p class="ai-evidence">识别依据：${escape(candidates)}</p>` : ''}</div>
        <div class="ai-result-actions">${item.file_path ? '<button type="button" data-import-action="preview">预览</button>' : ''}
          ${pending ? `${item.stored ? `<select aria-label="为 ${escape(item.name)} 选择学生" ${busy ? 'disabled' : ''}><option value="">选择学生（名单中）</option>${choices}</select><button type="button" class="primary" data-import-action="confirm" ${busy ? 'disabled' : ''}>确认归入此作业</button>` : ''}<button type="button" data-import-action="discard" ${busy ? 'disabled' : ''}>取消此文件</button>` : ''}</div></div>`;
    }).join('')}${failedFiles ? '<button type="button" data-import-action="retry-upload">重试上传本批文件</button>' : ''}`;
  }
  async function request(url, body) {
    const response = await fetch(url, { method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.msg || '导入请求失败');
    return result;
  }
  async function refresh() {
    const result = await request('/api/assignment-import/status?assignment_id=' + encodeURIComponent(aid));
    items = result.items || []; students = result.students || [];
    message = students.some(s => !s.disabled) ? '成功归档后计入已提交；待确认文件会保留，刷新后可继续处理。' : '请先在管理页导入学生名单，并区分同名学生。';
    render();
  }
  function xhrUpload(form) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/assignment-import/upload');
      xhr.timeout = 10 * 60 * 1000;
      xhr.upload.onprogress = event => {
        message = event.lengthComputable ? `正在上传 ${Math.round(event.loaded / event.total * 100)}%…` : '正在上传…'; render();
      };
      xhr.upload.onload = () => { message = '文件已上传，正在识别和归档，请稍候…'; render(); };
      xhr.onload = () => {
        try { const result = JSON.parse(xhr.responseText); if (xhr.status >= 400 || !result.ok) throw new Error(result.msg || '导入失败'); resolve(result); }
        catch (error) { reject(error); }
      };
      xhr.onerror = () => reject(new Error('连接中断。文件可能已处理，请先刷新状态；重试不会重复收录。'));
      xhr.ontimeout = () => reject(new Error('处理超时，请先刷新状态后重试。'));
      xhr.send(form);
    });
  }
  async function upload(files, retry = false) {
    if (busy || !files.length) return;
    if (!students.some(s => !s.disabled)) { message = '请先配置可区分的学生名单。'; render(); return; }
    if (files.length > 50 || files.reduce((sum, f) => sum + f.size, 0) > 99 * 1024 * 1024) { message = '每批最多 50 个文件、合计小于 99 MB，请分批拖入。'; render(); return; }
    busy = true; failedFiles = null; message = `正在上传 ${files.length} 个文件…`; render();
    const form = new FormData(); form.append('assignment_id', aid);
    let operation = retry ? storedRequest() : '';
    operation = operation || [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
    storedRequest(operation); form.append('request_id', operation);
    files.forEach(file => form.append('files', file, file.name));
    try {
      const result = await xhrUpload(form);
      items = result.items.concat(items.filter(i => i.batch_id !== result.batch_id));
      storedRequest(null);
      message = `处理完成：入库 ${result.items.filter(i => i.status === 'imported').length} 个，重复 ${result.items.filter(i => i.status === 'duplicate').length} 个，待处理 ${result.items.filter(i => ['pending', 'error'].includes(i.status)).length} 个。`;
      await options.onChanged();
    } catch (error) { message = error.message; failedFiles = files; }
    finally { busy = false; $('files').value = ''; render(); }
  }
  $('choose').addEventListener('click', event => { event.stopPropagation(); if (!busy) $('files').click(); });
  $('drop').addEventListener('click', event => { if (event.target === $('drop') && !busy) $('files').click(); });
  $('drop').addEventListener('keydown', event => { if (event.target === $('drop') && ['Enter', ' '].includes(event.key)) { event.preventDefault(); if (!busy) $('files').click(); } });
  $('files').addEventListener('change', event => upload([...event.target.files]));
  ['dragenter', 'dragover'].forEach(type => dropTarget.addEventListener(type, event => { event.preventDefault(); event.stopPropagation(); if (!busy) $('drop').classList.add('dragging'); }));
  dropTarget.addEventListener('dragleave', event => { if (!dropTarget.contains(event.relatedTarget)) $('drop').classList.remove('dragging'); });
  dropTarget.addEventListener('drop', event => { event.preventDefault(); event.stopPropagation(); $('drop').classList.remove('dragging'); upload([...event.dataTransfer.files]); });
  $('results').addEventListener('click', async event => {
    const button = event.target.closest('[data-import-action]'); if (!button || busy) return;
    const action = button.dataset.importAction;
    if (action === 'retry-upload') return upload(failedFiles || [], true);
    const row = button.closest('[data-import-item]');
    const item = items.find(i => i.id === row.dataset.importItem && i.batch_id === row.dataset.batch); if (!item) return;
    if (action === 'preview') return options.preview(item.file_path);
    const ref = row.querySelector('select')?.value || '';
    if (action === 'confirm' && !ref) { message = '请先选择这份文件对应的学生。'; render(); return; }
    busy = true; message = action === 'discard' ? '正在取消…' : '正在归档…'; render();
    try {
      const result = await request('/api/assignment-import/resolve', { batch_id: item.batch_id, item_id: item.id, student_ref: ref, discard: action === 'discard' });
      items = result.items.concat(items.filter(i => i.batch_id !== result.batch_id));
      const changed = result.items.find(i => i.id === item.id);
      message = changed?.message || '处理完成';
      if (changed?.status === 'imported' || changed?.status === 'duplicate') await options.onChanged();
    } catch (error) { message = error.message; }
    finally { busy = false; render(); }
  });
  // Prevent the browser from navigating to a dropped file outside the target.
  if (!window._assignmentImportDropGuard) {
    window._assignmentImportDropGuard = true;
    ['dragover', 'drop'].forEach(type => document.addEventListener(type, event => {
      if ([...(event.dataTransfer?.types || [])].includes('Files')) event.preventDefault();
    }));
  }
  refresh().catch(error => { message = error.message; render(); });
};
