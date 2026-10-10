// Read-only smoke check of the deployed UI; restore the configured theme.
async page => {
  const writes=[],errors=[];
  const handler=route=>route.request().method()==='GET'?route.continue():(writes.push(route.request().method()),route.abort());
  const onError=e=>errors.push(e.message);
  page.on('pageerror',onError);
  await page.route('**/api/**',handler);
  try {
    await page.waitForFunction(()=>state.theme?.presets?.length===20);
    await page.evaluate(()=>skipModernGuide());
    await page.getByRole('button',{name:'管理',exact:true}).click();
    await page.getByRole('tab',{name:'外观与访问',exact:true}).click();
    const result=await page.evaluate(()=>{
      const active=state.theme.active;
      applyThemeValues({...state.theme,active:'golden-iris'});
      const field=document.getElementById('theme-select');
      const select=getComputedStyle(field), option=getComputedStyle(field.options[0]);
      const light={foreground:select.color,background:select.backgroundColor,scheme:select.colorScheme,
        optionForeground:option.color,optionBackground:option.backgroundColor};
      if(select.color===select.backgroundColor||option.color===option.backgroundColor)throw Error('Dropdown text invisible');
      applyThemeValues({...state.theme,active:'rose-carbon'});
      const dark={foreground:getComputedStyle(field.options[0]).color,background:getComputedStyle(field.options[0]).backgroundColor};
      applyThemeValues(state.theme);
      return {count:field.options.length,active,light,dark,viewport:{width:innerWidth,height:innerHeight},overflow:document.documentElement.scrollWidth>innerWidth+2};
    });
    if(result.overflow||writes.length||errors.length)throw Error(JSON.stringify({result,writes,errors}));
    return {result,writes,errors};
  } finally {
    await page.evaluate(()=>applyThemeValues(state.theme));
    await page.unroute('**/api/**',handler);page.off('pageerror',onError);
    const client=await page.context().newCDPSession(page);
    try {await client.send('Emulation.setDeviceMetricsOverride',{width:0,height:0,deviceScaleFactor:0,mobile:false});}
    finally {await client.detach();}
  }
}
