// Exercise actual installed-page update download without applying an update.
async page => {
  const writes = [], downloads = [];
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') {
      writes.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  page.on('request', request => {
    if (request.url().includes('/api/update/download?')) downloads.push(request.url());
  });
  const result = await page.evaluate(async () => {
    const modern = typeof downloadModernUpdate === 'function';
    if (modern) await checkModernUpdate(); else await checkGithubUpdate();
    const info = modern ? modernLatestUpdate : latestGithubUpdate;
    if (!info?.ok || !info.asset?.download_url.startsWith('/api/update/download?')) {
      throw Error('Installed update metadata is not same-origin');
    }
    const oldConfirm = window.confirm, oldOpen = window.open;
    let confirms = 0, fileSize = 0, fileName = '';
    let originalHandler;
    window.confirm = () => ++confirms === 1; // Download permitted; installation explicitly cancelled.
    window.open = () => null;
    const handler = async file => {
      fileSize = file.size; fileName = file.name;
      return originalHandler(file);
    };
    try {
      info.has_update = true; // Simulate an older client without changing persisted app version.
      if (modern) {
        originalHandler = handleModernUpdateFile;
        handleModernUpdateFile = handler;
        await downloadModernUpdate();
      } else {
        originalHandler = handleUpdateFile;
        handleUpdateFile = handler;
        await downloadGithubUpdate();
      }
    } finally {
      window.confirm = oldConfirm; window.open = oldOpen;
      info.has_update = false;
      if (modern) handleModernUpdateFile = originalHandler; else handleUpdateFile = originalHandler;
    }
    if (confirms !== 2 || fileSize < 1000 || fileName !== info.asset.name) {
      throw Error('Download or second confirmation failed: ' + JSON.stringify({confirms, fileSize, fileName}));
    }
    return {frontend: modern ? 'modern' : 'classic', release: info.latest_version, confirms, fileSize, fileName};
  });
  if (writes.length) throw Error('Unexpected write attempted: ' + writes.join(','));
  if (downloads.length !== 1 || !downloads[0].startsWith(new URL(page.url()).origin + '/api/update/download?')) {
    throw Error('Unexpected download request: ' + JSON.stringify(downloads));
  }
  await page.evaluate(value => { window.installerUpdateValidation = value; }, {...result, writes: writes.length});
  console.log('UPDATE_UI_DOWNLOAD_OK', JSON.stringify({...result, writes: writes.length}));
}
