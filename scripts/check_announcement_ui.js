// Playwright CLI regression checks on the real UI. No production writes.
async page => {
  const writes = [];
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') {
      writes.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  await page.evaluate(() => { showPage('manage'); document.querySelector('.developer-console-disclosure').open = true; });
  const results = await page.evaluate(async () => {
    const checks = [];
    const check = (name, value) => { checks.push({name, passed: !!value}); if (!value) throw Error(name); };
    const make = id => ({id, title: '虚构测试公告'+id, type:'notice', version:'0.1.1', author:'测试', content:'旧内容', timestamp:'2026-10-09T00:00:00Z'});
    const original = state.announcements;
    const originalGet = apiGet;
    const originalModal = showModernAnnouncementModal;
    const originalFetch = window.fetch;
    const originalToast = toast;
    let fetches = 0, calls = 0, message = '';
    try {
      toast = value => {message = value;};
      window.fetch = async () => {fetches++; throw Error('Unexpected write');};
      state.announcements = [make('a'), make('b'), make('c')];
      editModernAnnouncement(1);
      check('编辑保留原公告', state.announcements.length===3 && state.announcements[1].id==='b');
      check('编辑按钮切换', document.getElementById('modern-ann-save').textContent==='保存修改' && document.getElementById('modern-ann-cancel').style.display!=='none');
      await buildModernUpdatePackage();
      check('未保存编辑阻止打包', fetches===0 && message.includes('未保存'));
      const count = state.announcements.length;
      await loadExistingAnnouncementsModern();
      check('未保存编辑阻止覆盖加载', state.announcements.length===count);
      clearModernAnnouncementForm();
      check('取消保留原文', state.announcements[1].content==='旧内容' && !state.editingAnnouncement);
      editModernAnnouncement(1);
      document.getElementById('modern-ann-content').value='修改后';
      addModernAnnouncement();
      check('保存原位替换不重复', state.announcements.length===3 && state.announcements[1].id==='b' && state.announcements[1].content==='修改后');
      check('保存后表单复位', !state.editingAnnouncement && document.getElementById('modern-ann-save').textContent==='加入公告列表');
      editModernAnnouncement(2);
      const confirmBefore = window.confirm;
      window.confirm = () => true;
      try {
        removeModernAnnouncement(0);
        document.getElementById('modern-ann-content').value='删除前项后保存';
        addModernAnnouncement();
        check('删除前项后仍保存正确公告', state.announcements[1].id==='c' && state.announcements[1].content==='删除前项后保存');
        editModernAnnouncement(0);
        removeModernAnnouncement(0);
        check('删除编辑项清理状态', !state.editingAnnouncement && document.getElementById('modern-ann-title').value==='');
        editModernAnnouncement(0);
        clearModernAnnouncements();
        check('清空列表清理编辑', state.announcements.length===0 && !state.editingAnnouncement);
      } finally { window.confirm=confirmBefore; }
      document.getElementById('modern-ann-title').value='未加入的新公告';
      await buildModernUpdatePackage();
      check('新公告未入列表阻止打包', fetches===0);
      clearModernAnnouncementForm();
      state.announcements=[make('old')];
      apiGet=async () => ({ok:false});
      await loadExistingAnnouncementsModern();
      check('加载失败保留队列', state.announcements[0].id==='old');
      showModernAnnouncementModal=() => {calls++;};
      const key='modern_ann_dismissed_version', dismissed=localStorage.getItem(key);
      try {
        localStorage.setItem(key,'0.1.1');
        apiGet=async () => ({ok:true,version:'0.1.2',announcements:[make('new')]});
        await loadAndShowModernAnnouncements();
        check('新版本仍展示公告', calls===1);
        localStorage.setItem(key,'0.1.2');
        await loadAndShowModernAnnouncements();
        check('忽略当前版本不重复弹窗', calls===1);
      } finally {
        if(dismissed===null) localStorage.removeItem(key); else localStorage.setItem(key,dismissed);
      }
    } finally {
      window.fetch=originalFetch; apiGet=originalGet; showModernAnnouncementModal=originalModal; toast=originalToast;
      clearModernAnnouncementForm(); state.announcements=original; renderModernAnnouncementList();
    }
    return checks;
  });
  if(writes.length) throw Error('Production write attempted: '+writes.join(','));
  await page.evaluate(checks => { window.announcementFixResults=checks; }, results);
}
