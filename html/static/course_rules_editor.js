/* Course rules editor: pending inputs stay local; saves update selected courses. */
'use strict';
window.createCourseRulesEditor = function (root, options) {
  const KEY = 'assignment-dashboard-course-editor-draft-v1';
  const fields = ['confirmed_aliases', 'keywords', 'suggested_aliases'];
  const labels = { confirmed_aliases: '确认别名', keywords: '课程关键词', suggested_aliases: '待确认别名' };
  const clone = value => JSON.parse(JSON.stringify(value));
  const escape = options.escapeHtml;
  const split = text => {
    const seen = new Set();
    return String(text || '').split(/[\n,，、;；]+/).map(word => word.trim()).filter(word => {
      const key = word.toLocaleLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key); return true;
    });
  };
  const $ = role => root.querySelector(`[data-courses-role="${role}"]`);
  let model = { rows: [], saved: [], inputs: {}, expanded: [] };
  let initialized = false, editing = null, saving = false, error = '', sourceSignature = '', savedAt = '';
  root.classList.add('course-rules-editor');
  root.innerHTML = `<div class="cr-toolbar"><div><h3>课程规则 <span data-courses-role="count" class="cr-count"></span></h3><p data-courses-role="status" role="status"></p></div><div class="cr-actions"><button data-global="review">查看改动</button><button data-global="undo">撤销未保存修改</button><button class="primary" data-global="save">保存全部</button></div></div><p data-courses-role="error" class="cr-error" role="alert" hidden></p><div data-courses-role="list" class="cr-list"></div><div class="cr-footer"><button data-global="add">＋ 添加课程</button><button data-global="reload">重新载入规则</button></div><p class="cr-note">保存后用于后续分类；未保存输入会暂存在当前浏览器。</p><dialog data-courses-role="dialog"><div class="cr-dialog-head"><h3>未保存改动</h3><button data-global="close-dialog" aria-label="关闭课程改动预览">×</button></div><div data-courses-role="changes"></div></dialog>`;
  function row(id) { return model.rows.find(item => item.id === id); }
  function key(id, field) { return `${id}:${field}`; }
  function data(item) {
    return { active: item.active, confirmed_aliases: item.confirmed_aliases, suggested_aliases: item.suggested_aliases,
      keywords: item.keywords, assignment_types: item.assignment_types, source: item.source };
  }
  function fromRules(pack) {
    return Object.entries(pack?.subjects || {}).map(([name, item]) => ({ id: `course:${name}`, originalName: name, name,
      active: item.active !== false, ...Object.fromEntries(fields.map(field => [field, clone(item[field] || [])])),
      assignment_types: clone(item.assignment_types || []), source: item.source || 'user_confirmed' }));
  }
  function dirty(item) {
    const saved = model.saved.find(entry => entry.id === item.id);
    return !saved || JSON.stringify(item) !== JSON.stringify(saved) || fields.some(field => model.inputs[key(item.id, field)]?.trim()) || editing?.id === item.id;
  }
  function dirtyCount() { return model.rows.filter(dirty).length + model.saved.filter(item => !row(item.id)).length; }
  function persist() {
    try {
      if (dirtyCount()) localStorage.setItem(KEY, JSON.stringify({ version: 1, ...model, editing }));
      else localStorage.removeItem(KEY);
    } catch { /* Inputs remain in the open editor if browser storage is unavailable. */ }
  }
  function errors() {
    const result = new Map(), names = new Map(), aliases = new Map();
    const add = (id, message) => result.set(id, [...(result.get(id) || []), message]);
    for (const item of model.rows) {
      const name = item.name.trim(), nameKey = name.toLocaleLowerCase();
      if (!name || name.length > 80) add(item.id, '请填写不超过 80 个字符的正式课程名称。');
      if (item.originalName && item.name !== item.originalName) add(item.id, '已保存的课程名称关联作业，请通过别名补充简称。');
      if (names.has(nameKey)) { add(item.id, '课程名称重复。'); add(names.get(nameKey), '课程名称重复。'); }
      names.set(nameKey, item.id);
      for (const field of fields) {
        if (item[field].length > (field === 'keywords' ? 200 : 100) || item[field].some(word => word.length > 80)) add(item.id, `${labels[field]}数量或长度超过上限。`);
      }
      for (const alias of [name, ...item.confirmed_aliases]) {
        if (!alias) continue;
        const aliasKey = alias.toLocaleLowerCase(), owner = aliases.get(aliasKey);
        if (owner && owner.id !== item.id) { add(item.id, `“${alias}”与“${owner.name}”冲突。`); add(owner.id, `“${alias}”与“${name}”冲突。`); }
        else aliases.set(aliasKey, { id: item.id, name });
      }
    }
    return result;
  }
  function tokenHTML(item, field, word, index) {
    const attrs = `data-id="${escape(item.id)}" data-field="${field}" data-index="${index}"`;
    if (field === 'suggested_aliases') return `<span class="token"><span class="token-label">${escape(word)}</span><button data-action="confirm-token" ${attrs} class="token-confirm" aria-label="确认别名：${escape(word)}">✓</button><button data-action="remove-token" ${attrs} class="token-remove" aria-label="忽略待确认别名：${escape(word)}">×</button></span>`;
    if (editing?.id === item.id && editing.field === field && editing.index === index) return `<span class="token token-editing"><input data-edit-token ${attrs} value="${escape(editing.value)}" aria-label="修改${labels[field]}：${escape(word)}"><button data-action="commit-edit" aria-label="确定标签修改">✓</button><button data-action="cancel-edit" aria-label="取消标签修改">×</button></span>`;
    return `<span class="token"><button class="token-edit" data-action="edit-token" ${attrs} aria-label="修改${labels[field]}：${escape(word)}">${escape(word)}</button><button class="token-remove" data-action="remove-token" ${attrs} aria-label="删除${labels[field]}：${escape(word)}">×</button></span>`;
  }
  function fieldHTML(item, field) {
    const suggested = field === 'suggested_aliases';
    const hint = { confirmed_aliases: '只填写已确认的可靠简称或缩写，例如 DSP。', keywords: '填写知识点、器件、工具或专业术语，避免“作业”“报告”等泛词。', suggested_aliases: '这里只显示系统建议。确认后参与分类，不合适的建议可忽略。' }[field];
    const input = suggested ? '' : `<div class="token-add"><input data-add-token data-id="${escape(item.id)}" data-field="${field}" value="${escape(model.inputs[key(item.id, field)] || '')}" placeholder="输入后按回车，支持粘贴多个词" aria-label="添加${labels[field]}：${escape(item.name || '新课程')}"><button data-action="add-token" data-id="${escape(item.id)}" data-field="${field}">添加</button></div>`;
    return `<section class="token-field ${suggested ? 'suggested-field' : ''}"><div class="field-heading"><strong>${labels[field]}</strong><span>${item[field].length} 个</span></div><div class="token-box">${item[field].map((word, index) => tokenHTML(item, field, word, index)).join('') || `<span class="token-empty">${suggested ? '暂无待确认别名' : '还没有标签，试着添加一个'}</span>`}</div>${input}<p class="field-hint">${hint}</p></section>`;
  }
  function render() {
    const focused = document.activeElement;
    const focus = root.contains(focused) && focused?.dataset.id && focused.tagName === 'INPUT' && focused.type !== 'checkbox'
      ? { id: focused.dataset.id, field: focused.dataset.field, type: focused.hasAttribute('data-edit-token') ? 'edit-token' : focused.hasAttribute('data-add-token') ? 'add-token' : 'course-name', start: focused.selectionStart, end: focused.selectionEnd } : null;
    $('list').innerHTML = model.rows.map((item, index) => `<details class="course-card" data-course-id="${escape(item.id)}" ${model.expanded.includes(item.id) ? 'open' : ''}><summary><span class="course-mark">${String(index + 1).padStart(2, '0')}</span><span class="course-summary-main"><span class="course-title">${escape(item.name || '未命名课程')}</span><small class="course-meta"></small></span><span class="course-state"></span><span class="chevron" aria-hidden="true">›</span></summary><div class="course-body"><div class="course-identity"><label class="name-field">正式课程名称<input data-course-name data-id="${escape(item.id)}" value="${escape(item.name)}" ${item.originalName ? 'readonly title="已关联作业的正式名称受到保护，可编辑下方别名"' : ''} aria-label="正式课程名称：${escape(item.name || '新课程')}"></label><label class="enabled-field"><input type="checkbox" data-course-active data-id="${escape(item.id)}" ${item.active ? 'checked' : ''}>参与分类</label></div><div class="token-grid">${fieldHTML(item, 'confirmed_aliases')}${fieldHTML(item, 'keywords')}</div>${fieldHTML(item, 'suggested_aliases')}<p class="row-error" hidden></p><div class="row-footer"><p>保存本课只更新这门课程，其他课程的未保存修改会保留。</p><div class="row-actions"><button class="danger" data-action="delete-course" data-id="${escape(item.id)}">移除规则</button><button data-action="cancel-row" data-id="${escape(item.id)}">取消修改</button><button class="primary" data-action="save-row" data-id="${escape(item.id)}">保存本课</button></div></div></div></details>`).join('') || '<div class="empty">暂无课程。添加课程或导入专业包开始配置。</div>';
    updateChrome();
    if (focus) {
      const target = [...$('list').querySelectorAll(`[data-${focus.type}]`)].find(input => input.dataset.id === focus.id && (!focus.field || input.dataset.field === focus.field));
      if (target) { target.focus({ preventScroll: true }); target.setSelectionRange(focus.start, focus.end); }
    }
  }
  function updateChrome() {
    const invalid = errors(), count = dirtyCount();
    $('count').textContent = `${model.rows.length} 门`;
    $('status').textContent = saving ? '正在保存课程规则…' : count ? `${count} 门课程有未保存修改 · 刷新状态不会清空输入` : savedAt ? `已保存 · ${savedAt}` : '点击标签修改，按回车添加，支持粘贴多个词。';
    $('error').hidden = !error && !invalid.size;
    $('error').textContent = error || (invalid.size ? '请处理标红的名称或别名问题，再保存。' : '');
    root.querySelectorAll('[data-global]').forEach(button => button.disabled = saving);
    root.querySelector('[data-global="save"]').disabled = saving || !count || !!invalid.size;
    root.querySelector('[data-global="undo"]').disabled = saving || !count;
    for (const card of $('list').querySelectorAll('.course-card')) {
      const item = row(card.dataset.courseId); if (!item) continue;
      const changed = dirty(item), issues = invalid.get(item.id) || [], modelLabel = options.modelLabel?.(item.originalName || item.name) || '';
      card.classList.toggle('is-dirty', !!changed);
      card.querySelector('.course-title').textContent = item.name || '未命名课程';
      card.querySelector('.course-meta').textContent = `${item.active ? '启用中' : '已停用'} · ${item.confirmed_aliases.length} 个别名 · ${item.keywords.length} 个关键词${modelLabel ? ' · ' + modelLabel : ''}`;
      card.querySelector('.course-state').textContent = changed ? '未保存' : '已保存';
      card.querySelector('.row-error').hidden = !issues.length;
      card.querySelector('.row-error').textContent = [...new Set(issues)].join(' ');
      card.querySelectorAll('button,input').forEach(input => input.disabled = saving);
      card.querySelector('[data-action="save-row"]').disabled = saving || !changed || !!invalid.size;
      card.querySelector('[data-action="cancel-row"]').disabled = saving || !changed;
    }
  }
  function changed(full = false) { error = ''; persist(); if (full) render(); else updateChrome(); }
  function commitEdit() {
    if (!editing) return true;
    const item = row(editing.id), words = split(editing.value);
    if (!words.length || words.some(word => word.length > 80)) { options.notify('标签不能为空，每项最多 80 个字符。'); return false; }
    if (item) { item[editing.field].splice(editing.index, 1, ...words); item[editing.field] = split(item[editing.field].join('，')); }
    editing = null; return true;
  }
  function addTokens(id, field, full = true) {
    if (!['confirmed_aliases', 'keywords'].includes(field)) return;
    const item = row(id), buffer = key(id, field), words = split(model.inputs[buffer]);
    if (!item || !words.length) return;
    item[field] = split([...item[field], ...words].join('，')); model.inputs[buffer] = ''; changed(full);
  }
  function flush(id) {
    if ((!id || editing?.id === id) && !commitEdit()) return false;
    for (const item of model.rows.filter(item => !id || item.id === id)) {
      item.name = item.name.trim();
      for (const field of ['confirmed_aliases', 'keywords']) addTokens(item.id, field, false);
      item.suggested_aliases = item.suggested_aliases.filter(word => !item.confirmed_aliases.some(alias => alias.toLocaleLowerCase() === word.toLocaleLowerCase()));
    }
    return true;
  }
  async function save(id) {
    if (saving || !flush(id)) return;
    if (errors().size) { changed(true); return options.notify('请先处理名称或别名冲突。'); }
    const changes = model.rows.filter(item => (!id || item.id === id) && dirty(item)).map(item => {
      const previous = model.saved.find(entry => entry.id === item.id);
      return { name: item.name, expected: previous ? data(previous) : null, course: data(item) };
    });
    if (!id) for (const saved of model.saved) if (!row(saved.id)) changes.push({ name: saved.name, expected: data(saved), delete: true });
    if (!changes.length) return;
    saving = true; error = ''; render();
    try {
      const response = await options.save(changes);
      if (id) {
        const item = row(id), official = response.rule_pack.subjects[item.name];
        const normalized = { ...item, ...clone(official), originalName: item.name };
        model.rows[model.rows.findIndex(entry => entry.id === id)] = normalized;
        const savedIndex = model.saved.findIndex(entry => entry.id === id);
        if (savedIndex < 0) model.saved.push(clone(normalized)); else model.saved[savedIndex] = clone(normalized);
      } else { model.rows = fromRules(response.rule_pack); model.saved = clone(model.rows); model.inputs = {}; editing = null; }
      sourceSignature = JSON.stringify(response.rule_pack);
      savedAt = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      persist(); options.onSaved(response.rule_pack); options.notify(id ? '本课规则已保存。' : '课程规则已保存。');
    } catch (failure) { error = `保存失败：${failure.message || failure}。输入已保留。`; persist(); }
    finally { saving = false; render(); }
  }
  function cancel(id) {
    const previous = model.saved.find(entry => entry.id === id), index = model.rows.findIndex(item => item.id === id);
    if (index < 0) return;
    if (previous) model.rows[index] = clone(previous); else model.rows.splice(index, 1);
    fields.forEach(field => delete model.inputs[key(id, field)]);
    if (editing?.id === id) editing = null;
    changed(true);
  }
  function remove(id) {
    const item = row(id);
    if (!item || !confirm(`从课程规则中移除“${item.name || '未命名课程'}”吗？\n保存后生效，不会删除已有作业和提交记录。`)) return;
    model.rows = model.rows.filter(entry => entry.id !== id); fields.forEach(field => delete model.inputs[key(id, field)]);
    if (editing?.id === id) editing = null;
    changed(true);
  }
  function add(name = '') {
    const id = globalThis.crypto?.randomUUID?.() || `new:${Date.now()}:${Math.random()}`;
    model.rows.push({ id, originalName: null, name, active: true, confirmed_aliases: [], suggested_aliases: [], keywords: [], assignment_types: [], source: 'user_confirmed' });
    model.expanded.push(id); changed(true);
    const input = [...$('list').querySelectorAll('[data-course-name]')].find(input => input.dataset.id === id);
    input?.focus(); input?.scrollIntoView({ block: 'nearest' });
  }
  function review() {
    const groups = [];
    for (const item of model.rows.filter(dirty)) {
      const old = model.saved.find(entry => entry.id === item.id), lines = [];
      if (!old) lines.push('新增课程');
      if (old && old.active !== item.active) lines.push(item.active ? '启用参与分类' : '停用参与分类');
      for (const field of fields) {
        const added = item[field].filter(word => !(old?.[field] || []).includes(word)), removed = (old?.[field] || []).filter(word => !item[field].includes(word));
        if (added.length) lines.push(`${labels[field]}新增：${added.join('、')}`);
        if (removed.length) lines.push(`${labels[field]}移除：${removed.join('、')}`);
        if (model.inputs[key(item.id, field)]?.trim()) lines.push(`${labels[field]}尚待添加：${model.inputs[key(item.id, field)]}`);
      }
      if (editing?.id === item.id) lines.push(`正在修改标签：${editing.value}`);
      groups.push({ name: item.name || '未命名课程', lines });
    }
    for (const item of model.saved) if (!row(item.id)) groups.push({ name: item.name, lines: ['移除课程规则'] });
    $('changes').innerHTML = groups.map(group => `<section class="change-group"><strong>${escape(group.name)}</strong>${group.lines.map(line => `<p>${escape(line)}</p>`).join('')}</section>`).join('') || '<p class="cr-note">目前没有未保存修改。</p>';
    $('dialog').showModal();
  }
  root.addEventListener('input', event => {
    const el = event.target, item = row(el.dataset.id); if (!item || saving) return;
    if (el.hasAttribute('data-course-name') && !item.originalName) item.name = el.value;
    else if (el.hasAttribute('data-add-token')) model.inputs[key(item.id, el.dataset.field)] = el.value;
    else if (el.hasAttribute('data-edit-token') && editing) editing.value = el.value;
    changed();
  });
  root.addEventListener('change', event => { if (event.target.hasAttribute('data-course-active') && !saving) { const item = row(event.target.dataset.id); if (item) { item.active = event.target.checked; changed(); } } });
  root.addEventListener('toggle', event => {
    if (!event.target.matches('.course-card')) return;
    const id = event.target.dataset.courseId;
    model.expanded = model.expanded.filter(entry => entry !== id); if (event.target.open) model.expanded.push(id);
  }, true);
  root.addEventListener('keydown', event => {
    if (event.isComposing || saving) return;
    const el = event.target;
    if (event.key === 'Enter' && el.hasAttribute('data-add-token')) { event.preventDefault(); addTokens(el.dataset.id, el.dataset.field); }
    if (el.hasAttribute('data-edit-token')) {
      if (event.key === 'Enter') { event.preventDefault(); if (commitEdit()) changed(true); }
      if (event.key === 'Escape') { editing = null; changed(true); }
    }
  });
  root.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || saving) return;
    const global = button.dataset.global;
    if (global === 'save') return save();
    if (global === 'add') return add();
    if (global === 'review') return review();
    if (global === 'close-dialog') return $('dialog').close();
    if (global === 'undo') { model.rows = clone(model.saved); model.inputs = {}; editing = null; return changed(true); }
    if (global === 'reload') {
      if (dirtyCount() && !confirm('放弃所有未保存的课程修改，并读取最新规则吗？')) return;
      try { const pack = await options.reload(); reset(pack); } catch (failure) { error = `读取失败：${failure.message || failure}。输入已保留。`; updateChrome(); }
      return;
    }
    const { action, id, field } = button.dataset, item = row(id), index = Number(button.dataset.index);
    if (action === 'save-row') return save(id);
    if (action === 'cancel-row') return cancel(id);
    if (action === 'delete-course') return remove(id);
    if (action === 'add-token') return addTokens(id, field);
    if (action === 'cancel-edit') { editing = null; return changed(true); }
    if (action === 'commit-edit') { if (commitEdit()) changed(true); return; }
    if (!item) return;
    const word = item[field]?.[index];
    if (!word || !commitEdit()) return;
    const currentIndex = item[field].indexOf(word);
    if (currentIndex < 0) return changed(true);
    if (action === 'edit-token' && field !== 'suggested_aliases') {
      editing = { id, field, index: currentIndex, value: word }; changed(true);
      const input = root.querySelector('[data-edit-token]'); input?.focus(); input?.select();
    } else if (action === 'remove-token' || action === 'confirm-token') {
      if (action === 'confirm-token') item.confirmed_aliases = split([...item.confirmed_aliases, word].join('，'));
      item[field].splice(currentIndex, 1); changed(true);
    }
  });
  function reset(pack) {
    const expandedNames = model.rows.filter(item => model.expanded.includes(item.id)).map(item => item.name);
    model.rows = fromRules(pack); model.saved = clone(model.rows); model.inputs = {}; editing = null; error = '';
    model.expanded = model.rows.filter(item => expandedNames.includes(item.name)).map(item => item.id);
    if (!model.expanded.length && model.rows[0]) model.expanded = [model.rows[0].id];
    sourceSignature = JSON.stringify(pack); persist(); render();
  }
  function sync(pack) {
    if (!pack) return;
    if (!initialized) {
      let cached;
      try { cached = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { cached = null; }
      initialized = true; reset(pack);
      try {
        if (cached?.version === 1 && Array.isArray(cached.rows) && Array.isArray(cached.saved) && cached.rows.every(item => fields.every(field => Array.isArray(item[field])))) {
          model = cached; editing = cached.editing || null; persist(); render();
        }
      } catch { /* Ignore an invalid editor-only cache. */ }
      return;
    }
    if (!saving && !dirtyCount() && sourceSignature !== JSON.stringify(pack)) reset(pack);
    else updateChrome();
  }
  return { sync, save, add, remove, dirtyCount, collectRules: () => ({ ...options.rules(), subjects: Object.fromEntries(model.rows.filter(item => item.name.trim()).map(item => [item.name.trim(), data(item)])) }) };
};
