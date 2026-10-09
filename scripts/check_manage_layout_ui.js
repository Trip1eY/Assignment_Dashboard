// Playwright CLI check against /modern, already opened in developer mode on the management page.
// Uses read-only APIs and local theme application, never clicks a saving/destructive action.
async page => {
  const results=[], failures=[], writes=[];
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.route('**/api/**', route=>{
    if(route.request().method() !== 'GET') { writes.push(route.request().method()+' '+new URL(route.request().url()).pathname); return route.abort(); }
    return route.continue();
  });
  const themes=await page.evaluate(()=>state.theme.presets.map(item=>item.id));
  const activeTheme=await page.evaluate(()=>state.theme.active);
  await page.locator('.developer-console-disclosure').evaluate(item=>item.open=true);
  for(const width of [320,390,768,1440]) {
    await page.setViewportSize({width,height:1080});
    for(const theme of themes) {
      await page.evaluate(id=>applyThemeValues({...state.theme,active:id}),theme);
      for(const [name,group] of [['基础配置','basic'],['识别与归档','recognition'],['外观与访问','appearance'],['系统维护','system']]) {
        await page.getByRole('tab',{name,exact:true}).click();
        await page.mouse.move(0,0);
        const check=await page.evaluate(group=>{
          const cards=[...document.querySelectorAll('#page-manage [data-manage-group]')];
          const visible=cards.filter(item=>getComputedStyle(item).display!=='none');
          const rect=s=>document.querySelector(s).getBoundingClientRect();
          const icon=rect('.announcement-icon'),bell=rect('.announcement-bell');
          const result={groups:visible.length>0&&visible.every(item=>item.dataset.manageGroup===group),overflow:document.documentElement.scrollWidth>innerWidth,bell:Math.abs(icon.left+icon.width/2-bell.left-bell.width/2)<1&&Math.abs(icon.top+icon.height/2-bell.top-bell.height/2)<1};
          if(group==='system') {
            const a=rect('.manage-preview-card'),b=rect('.manage-update-card'),s=rect('.manage-server-card');
            result.layout=innerWidth<=900 ? a.top<b.top&&b.top<s.top : Math.abs(a.height-b.height)<1&&Math.abs(a.top-b.top)<1&&Math.abs(s.left-a.left)<1&&Math.abs(s.right-b.right)<1;
          }
          return result;
        },group);
        results.push({width,theme,group,...check});
        if(!check.groups||check.overflow||!check.bell||check.layout===false) failures.push(results[results.length-1]);
      }
    }
  }
  await page.setViewportSize({width:1440,height:1080});
  await page.evaluate(id=>applyThemeValues({...state.theme,active:id}),activeTheme);
  await page.getByRole('tab',{name:'系统维护',exact:true}).click();
  await page.evaluate(()=>document.body.classList.remove('developer-mode'));
  const developerHidden=!(await page.locator('.manage-server-card').isVisible());
  await page.evaluate(()=>document.body.classList.add('developer-mode'));
  const handlers=await page.locator('#manage-workspace-tabs [data-manage-section]').evaluateAll(items=>items.every(item=>!item.disabled&&item.getAttribute('onclick').includes('switchManageSection')));
  await page.evaluate(data=>window.manageLayoutChecks=data,{cases:results.length,failures,developerHidden,handlers,writes});
  await page.evaluate(()=>scrollTo(0,0));
}
