// Read-only popup rendering and version-dismissal regression, using fictional data.
async page => {
  const checks=[];
  const check=(name,passed)=>{checks.push({name,passed:!!passed});if(!passed)throw Error(name);};
  await page.waitForFunction(()=>state.theme && typeof showModernAnnouncementModal==='function');
  await page.evaluate(()=>{finishModernGuide(false);localStorage.setItem(MODERN_GUIDE_KEY,'1');});
  await page.emulateMedia({reducedMotion:'reduce'});
  const themes=await page.evaluate(()=>state.theme.presets.map(item=>item.id));
  const fixture=[{id:'fictional',title:'更新公告测试',type:'changelog',version:'0.1.2',author:'测试',content:'## 更新内容\n\n- 新版公告正常展示。\n- <img src=x onerror=alert(1)>',timestamp:'2026-10-09T00:00:00Z'}];
  for(const width of [390,1440]){
    await page.setViewportSize({width,height:1080});
    for(const theme of themes){
      const valid=await page.evaluate(({theme,fixture})=>{
        document.querySelectorAll('[data-modern-ann-popup]').forEach(item=>item.remove());
        applyThemeValues({...state.theme,active:theme});
        showModernAnnouncementModal(fixture,'0.1.2');
        const modal=document.querySelector('.announcement-modal');
        return !!modal && !modal.querySelector('img') && modal.textContent.includes('<img') &&
          modal.getBoundingClientRect().width<=innerWidth &&
          document.documentElement.scrollWidth<=innerWidth;
      },{theme,fixture});
      check('modern-popup-'+theme+'-'+width,valid);
    }
  }
  await page.screenshot({path:'output/playwright/announcement-popup-modern.png'});
  await page.evaluate(()=>document.querySelectorAll('[data-modern-ann-popup]').forEach(item=>item.remove()));
  const classic=await page.context().newPage();
  await classic.addInitScript(()=>localStorage.setItem('tutorial_completed','true'));
  await classic.emulateMedia({reducedMotion:'reduce'});
  const url=new URL(page.url());url.pathname='/dashboard';url.search='';url.hash='';
  await classic.goto(url.href);
  await classic.waitForFunction(()=>typeof loadAndShowAnnouncements==='function');
  const gating=await classic.evaluate(async()=>{
    const beforeGet=apiGet,beforeModal=showAnnouncementModal;
    const key='ann_dismissed_version',beforeDismiss=localStorage.getItem(key);
    let calls=0;
    try{
      showAnnouncementModal=()=>{calls++;};
      apiGet=async()=>({ok:true,version:'0.1.2',announcements:[{title:'测试',content:'内容'}]});
      localStorage.setItem(key,'0.1.1');await loadAndShowAnnouncements();
      const newVersion=calls===1;
      localStorage.setItem(key,'0.1.2');await loadAndShowAnnouncements();
      return {newVersion,currentVersion:calls===1};
    }finally{
      apiGet=beforeGet;showAnnouncementModal=beforeModal;
      if(beforeDismiss===null)localStorage.removeItem(key);else localStorage.setItem(key,beforeDismiss);
    }
  });
  check('classic-new-version',gating.newVersion);
  check('classic-dismiss-current',gating.currentVersion);
  await classic.evaluate(fixture=>showAnnouncementModal(fixture,'0.1.2',true),fixture);
  check('classic-popup-visible',await classic.locator('.ann-modal-overlay').isVisible());
  await classic.waitForFunction(()=>Number(getComputedStyle(document.querySelector('.ann-modal-overlay')).opacity)>=0.99);
  await classic.screenshot({path:'output/playwright/announcement-popup-classic.png'});
  await classic.close();
  await page.evaluate(checks=>{window.announcementPopupResults=checks;},checks);
}
