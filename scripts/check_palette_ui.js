// Playwright CLI: run against the disposable server in developer mode.
async page => {
  const originalURL=page.url(), failures=[], writes=[], errors=[];
  const blockWrites=route=>{
    if(route.request().method()!=='GET') {writes.push(route.request().method());return route.abort();}
    return route.continue();
  };
  const onError=error=>errors.push(error.message);
  page.on('pageerror',onError);
  await page.route('**/api/**',blockWrites);
  let checks=0, options=0;
  const inspect=async(label)=>{
    const result=await page.evaluate(()=>{
      const luminance=value=>{
        const c=value.match(/[\d.]+/g).slice(0,3).map(Number).map(c=>c/255)
          .map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4);
        return c.reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
      };
      const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
      const elements=[...document.querySelectorAll('select,select option,select optgroup')];
      const bad=[];
      for(const el of elements){
        const s=getComputedStyle(el),ratio=contrast(s.color,s.backgroundColor);
        if(ratio<4.5||s.backgroundColor==='rgba(0, 0, 0, 0)')bad.push({element:el.id||el.tagName,ratio,color:s.color,bg:s.backgroundColor});
      }
      return {count:elements.length,bad,overflow:document.documentElement.scrollWidth>innerWidth+2};
    });
    checks++;options+=result.count;
    if(result.bad.length||result.overflow)failures.push({label,...result});
  };
  try {
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.reload();
    await page.waitForFunction(()=>state.theme?.presets?.length===20);
    await page.evaluate(()=>skipModernGuide());
    await page.getByRole('button',{name:'管理',exact:true}).click();
    await page.getByRole('tab',{name:'外观与访问',exact:true}).click();
    const themes=await page.evaluate(()=>state.theme.presets.map(p=>p.id));
    await page.evaluate(()=>{
      const probe=document.createElement('select');probe.id='contrast-dynamic-probe';
      probe.innerHTML='<optgroup label="动态分组"><option>动态课程</option><option disabled>禁用课程</option></optgroup>';
      probe.hidden=true;document.getElementById('page-brain').append(probe);
    });
    for(const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:1000});
      for(const id of themes) {
        await page.evaluate(id=>applyThemeValues({...state.theme,active:id}),id);
        await inspect(width+':'+id);
      }
    }
    for(const style of ['modern','mecha','mecha-heart','minimal','shader','paper']) {
      for(const hex of ['#ffffff','#000000','#808080']) {
        await page.evaluate(({style,hex})=>applyThemeValues({...state.theme,active:'custom',style,
          custom:{primary:'#2563eb',accent:'#10b981',background:hex,surface:hex,text:hex,border:'#64748b'}}),{style,hex});
        await inspect('same-color-custom:'+style+':'+hex);
      }
    }
    await page.emulateMedia({forcedColors:'active'});
    await inspect('forced-colors');
    await page.emulateMedia({forcedColors:'none'});
    await page.setViewportSize({width:1440,height:1000});
    await page.evaluate(()=>applyThemeValues({...state.theme,active:'golden-iris'}));
    await page.locator('#theme-select').evaluate(el=>el.size=8);
    await page.screenshot({path:'output/playwright/palette-dropdown-contrast.png',fullPage:false});
    await page.locator('#theme-select').evaluate(el=>el.removeAttribute('size'));
    await page.evaluate(()=>{
      applyThemeValues({...state.theme,active:'spiral-nebula'});
      if(document.body.dataset.palette||document.documentElement.style.getPropertyValue('--inspiration-a'))throw Error('Palette residue on original theme');
    });
    if(failures.length||writes.length||errors.length)throw Error(JSON.stringify({failures,writes,errors}));
    return {checks,elementsChecked:options,themeCount:themes.length,writes,errors};
  } finally {
    await page.evaluate(()=>document.getElementById('contrast-dynamic-probe')?.remove());
    await page.unroute('**/api/**',blockWrites);page.off('pageerror',onError);
    await page.emulateMedia({reducedMotion:'no-preference',forcedColors:'none'});
    const client=await page.context().newCDPSession(page);
    try {await client.send('Emulation.setDeviceMetricsOverride',{width:0,height:0,deviceScaleFactor:0,mobile:false});}
    finally {await client.detach();}
  }
}
