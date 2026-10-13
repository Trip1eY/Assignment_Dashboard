// Only use the disposable service on 18874, never production writes.
async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:18874/modern');
 await page.waitForFunction(()=>state.theme?.presets?.length===28 && state.dashboard);
 await page.evaluate(()=>{if(typeof finishModernGuide==='function')finishModernGuide(false);});
 await page.emulateMedia({reducedMotion:'reduce'});
 const ids=await page.evaluate(()=>state.theme.presets.map(p=>p.id));
 let checks=0;
 for(const width of [320,390,900,1440]){
  await page.setViewportSize({width,height:1000});
  for(const id of ids){
   const result=await page.evaluate(id=>{
    showPage('manage');switchManageSection('appearance');previewThemePalette(id);
    const family=document.getElementById('theme-family');const arrow=getComputedStyle(family);
    const progress=[...document.querySelectorAll('.progress')];
    const lum=v=>themeLuminance(themeColorChannels(v));
    const contrast=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
    const badProgress=progress.some(el=>{if(!el.firstElementChild)return false;return contrast(getComputedStyle(el).backgroundColor,getComputedStyle(el.firstElementChild).backgroundColor)<3;});
    return {overflow:document.documentElement.scrollWidth>innerWidth,
     arrow:arrow.appearance==='auto'&&arrow.backgroundImage==='none',ink:contrast(arrow.color,arrow.backgroundColor),
     selected:document.querySelectorAll('.theme-colorway[aria-pressed=true]').length,
     family:family.value,expected:state.theme.presets.find(p=>p.id===id).family,badProgress};
   },id);
   if(result.overflow||!result.arrow||result.ink<4.5||result.selected!==1||result.family!==result.expected||result.badProgress)throw Error(JSON.stringify({width,id,...result}));
   checks++;
  }
 }
 await page.setViewportSize({width:1440,height:1100});
 await page.evaluate(()=>{if(typeof closeModernAnnouncementModal==='function')closeModernAnnouncementModal();});
 await page.selectOption('#theme-family','jade');
 await page.getByRole('button',{name:/玉叙荷白/}).click();
 await page.selectOption('#motion-mode','stars');
 await page.locator('#motion-intensity').evaluate(el=>{el.value='41';el.dispatchEvent(new Event('input'));});
 await page.getByRole('button',{name:'保存主题',exact:true}).click();
 await page.waitForFunction(()=>state.theme.active==='jade-lotus' && state.theme.motion.mode==='stars');
 await page.reload();await page.waitForFunction(()=>state.theme?.active==='jade-lotus');
 const saved=await page.evaluate(()=>({active:state.theme.active,motion:state.theme.motion}));
 if(saved.motion.mode!=='stars'||saved.motion.intensity!==41)throw Error('Persistence failed');
 // Restore disposable fixture to another palette and verify classic omission preserves motion.
 const legacy=await page.evaluate(async()=>await apiPost('/api/theme/save',{active:'clean-blue'}));
 if(legacy.theme.motion.mode!=='stars'||legacy.theme.motion.intensity!==41)throw Error('Legacy motion lost');
 await page.evaluate(()=>{if(typeof finishModernGuide==='function')finishModernGuide(false);showPage('manage');switchManageSection('appearance');});
 await page.evaluate(()=>{if(typeof closeModernAnnouncementModal==='function')closeModernAnnouncementModal();});
 await page.screenshot({path:'D:/codex workspace/Assignment-Dashboard-public-upload/output/playwright/theme-family-formal-merge.png',fullPage:true});
 if(errors.length)throw Error(JSON.stringify(errors));
 return {ok:true,checks,persistence:true,classicCompatibility:true,errors};
}
