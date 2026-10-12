/* FlipMD desktop client. All document operations use the local pywebview API. */
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="#icon-${name}"/></svg>`;
  const clone = value => JSON.parse(JSON.stringify(value));
  const activeStates = new Set(['queued', 'running']);
  const stateNames = {
    queued: '等待处理', running: '处理中', completed: '已完成', partial: '部分完成',
    failed: '失败', stopped: '已停止', interrupted: '意外中断'
  };
  const modeNames = { convert: '文档转换', merge: '合并文档', summary: '大纲与摘要' };
  const state = {
    ready: false, booting: false, page: 'new', settings: null, settingsDraft: null,
    task: null, queue: [], selected: new Set(), jobs: [], historySelected: new Set(),
    filter: 'all', query: '', ocr: { available: false, message: '' },
    result: null, resultId: null, resultView: 'rendered', sourceId: null, syncSourceId: null,
    sourcePage: 1, sourceTotal: 1, sourceLoading: false, pdfPageEditing: false, pdfView: null, resultRequest: 0,
    previewRequest: 0, mergeFiles: [], pending: new Set(), jobsSignature: '',
    pollTimer: null, polling: false, logSelection: '', confirmResolver: null, confirmTrigger: null
  };
  let toastTimer;
  const settingsSave = {
    revision: 0, savedRevision: 0, running: false, error: '',
    rangeTimer: null, rangePending: false, rangeError: ''
  };

  function openDrawer(kind) {
    $('summary-details').hidden = kind !== 'summary';
    $('log-details').hidden = kind !== 'log';
    $('drawer-title').textContent = kind === 'summary' ? '大纲与摘要' : '处理详情与日志';
    if (!$('result-drawer').open) $('result-drawer').show();
    $('result-drawer').scrollTop = 0;
  }

  document.addEventListener('keydown', event => {
    // Non-modal dialogs do not get the browser's modal Escape handling.
    if (event.key === 'Escape' && $('result-drawer').open && !document.querySelector('dialog:modal')) {
      event.preventDefault();
      $('result-drawer').close();
    }
  });

  let splitPreference = 55;
  let draggingSplit = false;
  function saveSplit() {
    try { localStorage.setItem('flipmd-split', String(splitPreference)); } catch { /* Optional preference. */ }
  }
  try {
    const saved = Number(localStorage.getItem('flipmd-split'));
    if (saved > 0 && saved < 100) splitPreference = saved;
    const zoom = sessionStorage.getItem('flipmd-zoom');
    if (['fit', 'page', '100', '125', '150', '200'].includes(zoom)) $('pdf-zoom').value = zoom;
  } catch { /* Display preferences are optional. */ }

  function setSplit(value, persist = false) {
    const grid = $('compare-grid');
    const width = grid.clientWidth;
    if (!width || window.matchMedia('(max-width:760px)').matches) return;
    const minimum = 320 / width * 100;
    const maximum = (width - 326) / width * 100;
    const clamped = Math.max(minimum, Math.min(maximum, value));
    grid.style.setProperty('--split', `${clamped}%`);
    const divider = $('pane-divider');
    divider.setAttribute('aria-valuemin', String(Math.ceil(minimum)));
    divider.setAttribute('aria-valuemax', String(Math.floor(maximum)));
    divider.setAttribute('aria-valuenow', String(Math.round(clamped)));
    divider.setAttribute('aria-valuetext', `原文 ${Math.round(clamped)}%，结果 ${Math.round(100 - clamped)}%`);
    if (persist) {
      splitPreference = value;
      saveSplit();
    }
    applyZoom();
  }
  const divider = $('pane-divider');
  divider.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    draggingSplit = true;
    divider.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing');
    divider.focus();
  });
  divider.addEventListener('pointermove', event => {
    if (!divider.hasPointerCapture(event.pointerId)) return;
    const bounds = $('compare-grid').getBoundingClientRect();
    splitPreference = Math.max(1, Math.min(99, (event.clientX - bounds.left) / bounds.width * 100));
    setSplit(splitPreference);
  });
  for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    divider.addEventListener(eventName, event => {
      if (!draggingSplit) return;
      draggingSplit = false;
      saveSplit();
      if (divider.hasPointerCapture(event.pointerId)) divider.releasePointerCapture(event.pointerId);
      document.body.classList.remove('resizing');
    });
  }
  divider.addEventListener('dblclick', () => setSplit(55, true));
  divider.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
    event.preventDefault();
    const current = Number(divider.getAttribute('aria-valuenow'));
    setSplit(event.key === 'Home' ? 55 : current + (event.key === 'ArrowLeft' ? -2 : 2), true);
  });
  new ResizeObserver(() => {
    if (state.page === 'result') setSplit(splitPreference);
  }).observe($('compare-grid'));
  new ResizeObserver(applyZoom).observe($('source-preview'));

  // Proportional only: no PDF page mapping is implied by the current output.
  const syncing = new WeakSet();
  const sourcePane = $('source-preview');
  const resultPanes = [$('rendered-result'), $('markdown-result')];
  function syncScroll(from, to) {
    if (syncing.has(from)) { syncing.delete(from); return; }
    if (!$('sync-scroll').checked || $('sync-scroll').disabled || state.sourceLoading || !state.result || !to || to.hidden) return;
    const range = from.scrollHeight - from.clientHeight;
    const targetRange = to.scrollHeight - to.clientHeight;
    if (range <= 0 || targetRange <= 0) return;
    const target = Math.round(from.scrollTop / range * targetRange);
    if (Math.abs(to.scrollTop - target) < 1) return;
    syncing.add(to);
    to.scrollTop = target;
    requestAnimationFrame(() => requestAnimationFrame(() => syncing.delete(to)));
  }
  sourcePane.addEventListener('scroll', () => {
    schedulePDFViewport();
    syncScroll(sourcePane, resultPanes.find(pane => !pane.hidden));
  }, { passive: true });
  for (const pane of resultPanes) pane.addEventListener('scroll', () => syncScroll(pane, sourcePane), { passive: true });

  function errorMessage(error) {
    if (typeof error === 'string') return error;
    if (error?.message) return String(error.message);
    return '操作未完成，请重试。';
  }

  function toast(message, isError = false) {
    clearTimeout(toastTimer);
    const node = document.createElement('div');
    node.className = `toast${isError ? ' error' : ''}`;
    node.textContent = String(message);
    $('toast-region').replaceChildren(node);
    toastTimer = setTimeout(() => $('toast-region').replaceChildren(), isError ? 8500 : 5000);
  }

  async function api(method, ...arguments_) {
    const bridge = window.pywebview?.api;
    if (!bridge || typeof bridge[method] !== 'function') {
      throw new Error('桌面连接不可用，请从 FlipMD 桌面窗口操作。');
    }
    return await bridge[method](...arguments_);
  }

  async function perform(key, operation, button = null) {
    if (state.pending.has(key)) return;
    state.pending.add(key);
    const wasDisabled = button?.disabled;
    if (button) button.disabled = true;
    updateAvailability();
    try {
      return await operation();
    } catch (error) {
      toast(errorMessage(error), true);
      return undefined;
    } finally {
      state.pending.delete(key);
      if (button?.isConnected) button.disabled = Boolean(wasDisabled);
      updateAvailability();
    }
  }

  function applyTheme(theme) {
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }

  function directoryName(path) { return path || '原文件所在文件夹'; }

  function renderOutputLocation(scope) {
    const config = scope === 'task' ? state.task : state.settingsDraft;
    const path = config.output_dir;
    $(`${scope}-output-reset`).disabled = !path;
    $(`${scope}-output`).textContent = path || '与原文件保存在同一文件夹';
    if (scope === 'task') {
      $('empty-output-label').textContent = `输出到${directoryName(path)}`;
      $('conversion-summary').textContent = `${state.queue.length} 个文件 · ${state.task.format === 'html' ? 'HTML' : 'Markdown'} · ${directoryName(path)}`;
    }
  }
  function fileSize(bytes) {
    if (typeof bytes !== 'number' || !Number.isFinite(bytes)) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function statusMarkup(value) {
    const known = Object.hasOwn(stateNames, value) ? value : 'queued';
    return `<span class="status ${known}">${escapeHTML(stateNames[known])}</span>`;
  }
  function fileMarkup(file, detail = '') {
    return `<div class="file-info"><span class="file-type">${escapeHTML(file.kind || 'PDF')}</span><div class="file-copy"><div class="file-name">${escapeHTML(file.name)}</div><div class="file-meta">${escapeHTML(detail || file.path || '')}</div></div></div>`;
  }

  function switchPage(page) {
    if (!state.ready || !['new', 'tasks', 'result', 'settings'].includes(page)) return;
    state.page = page;
    $('main').classList.toggle('result-active', page === 'result');
    if ($('result-drawer').open) $('result-drawer').close();
    document.querySelectorAll('.page').forEach(element => { element.hidden = element.id !== `page-${page}`; });
    document.querySelectorAll('[data-page]').forEach(button => {
      if (!button.classList.contains('nav-button')) return;
      const active = button.dataset.page === page || (page === 'result' && button.dataset.page === 'tasks');
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    if (page === 'new') renderQueue();
    if (page === 'tasks') renderJobs();
    if (page === 'result') requestAnimationFrame(() => setSplit(splitPreference));
    $('main').scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }

  function receiveFiles(files) {
    if (!Array.isArray(files)) { toast('没有收到有效的文件列表。', true); return 0; }
    const existing = new Set(state.queue.map(file => file.path || file.id));
    let added = 0;
    for (const file of files) {
      if (!file?.id || !file.path || !file.name || !['PDF', 'DOCX'].includes(file.kind)) continue;
      const key = file.path || file.id;
      if (existing.has(key)) continue;
      state.queue.push({ ...file });
      state.selected.add(file.id);
      existing.add(key);
      added += 1;
    }
    if (state.ready) {
      switchPage('new');
      toast(added ? `已添加 ${added} 个文件` : '所选文件已经在导入列表中。');
    }
    return added;
  }

  // Native drop handlers can call these before bootstrap has completed.
  window.flipmd = {
    receiveFiles,
    showError(message) { toast(message, true); }
  };

  function renderQueue() {
    if (!state.task) return;
    const hasFiles = state.queue.length > 0;
    $('import-empty').hidden = hasFiles;
    $('import-ready').hidden = !hasFiles;
    $('queue-count').textContent = `已添加 ${state.queue.length} 个文件`;
    $('queue-list').innerHTML = state.queue.map(file => {
      const size = fileSize(file.size);
      return `<div class="file-row"><input type="checkbox" data-queue-id="${escapeHTML(file.id)}" aria-label="选择 ${escapeHTML(file.name)}" ${state.selected.has(file.id) ? 'checked' : ''}>${fileMarkup(file, size ? `${size} · ${file.path}` : file.path)}<button class="icon-button" data-action="remove-one" data-id="${escapeHTML(file.id)}" aria-label="移除 ${escapeHTML(file.name)}">${icon('close')}</button></div>`;
    }).join('');
    $('queue-selection').textContent = state.selected.size ? `已选择 ${state.selected.size} 个` : '可选择文件合并或提取大纲';
    $('queue-select-all').checked = hasFiles && state.selected.size === state.queue.length;
    $('queue-select-all').indeterminate = state.selected.size > 0 && state.selected.size < state.queue.length;
    $('task-format').value = state.task.format;
    renderOutputLocation('task');
    updateAvailability();
  }

  function updateAvailability() {
    const submitting = state.pending.has('start-job');
    $('start-convert').disabled = !state.ready || !state.queue.length || submitting;
    $('start-convert').textContent = submitting ? '正在提交…' : '开始转换';
    $('queue-merge').disabled = !state.ready || state.selected.size < 2 || submitting;
    $('queue-summary').disabled = !state.ready || !state.selected.size || submitting;
    $('queue-remove').disabled = !state.selected.size || submitting;
    $('merge-submit').disabled = submitting || state.mergeFiles.length < 2;
    $('history-merge').disabled = state.historySelected.size < 2 || submitting;
    document.querySelectorAll('[data-action="choose-files"], [data-action="choose-folder"]').forEach(button => {
      button.disabled = !state.ready || state.pending.has('choose-files') || submitting;
    });
  }

  function dateParts(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return { group: '其他记录', time: '', key: '' };
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const dayKey = d => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    let group;
    if (dayKey(date) === dayKey(today)) group = '今天';
    else if (dayKey(date) === dayKey(yesterday)) group = '昨天';
    else group = date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
    return { group, time: date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }), key: dayKey(date) };
  }

  function sortedJobs() {
    return [...state.jobs].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  }

  function findItem(id) {
    for (const job of state.jobs) {
      const item = (job.items || []).find(candidate => candidate.id === id);
      if (item) return { item, job };
    }
    return null;
  }

  function sourceFile(item) {
    return { id: item.source_id, path: item.path, name: item.name, kind: item.kind || 'PDF' };
  }

  function selectedHistoryFiles() {
    const seen = new Set();
    const files = [];
    for (const id of state.historySelected) {
      const found = findItem(id);
      if (!found?.item.source_id) continue;
      const file = sourceFile(found.item);
      if (!seen.has(file.id)) { files.push(file); seen.add(file.id); }
    }
    return files;
  }

  function renderRecents() {
    const items = sortedJobs().flatMap(job => (job.items || []).filter(item => item.state === 'completed')).slice(0, 6);
    $('recent-files').innerHTML = items.length ? items.map(item => `<button class="recent-button" data-action="open-result" data-id="${escapeHTML(item.id)}" title="${escapeHTML(item.name)}"><span class="recent-kind">${escapeHTML(item.kind || 'MD')}</span><span>${escapeHTML(item.name)}</span></button>`).join('') : '<p class="quiet small">还没有转换结果</p>';
    const active = state.jobs.filter(job => activeStates.has(job.state)).length;
    $('active-count').hidden = !active;
    $('active-count').textContent = String(active);
  }

  function renderJobs() {
    const query = state.query.trim().toLocaleLowerCase();
    const matches = sortedJobs().filter(job => {
      const statusMatches = state.filter === 'all' ||
        (state.filter === 'active' && activeStates.has(job.state)) ||
        (state.filter === 'completed' && job.state === 'completed') ||
        (state.filter === 'failed' && ['failed', 'partial', 'stopped', 'interrupted'].includes(job.state));
      return statusMatches && (!query || (job.items || []).some(item => String(item.name).toLocaleLowerCase().includes(query)) || String(job.title || '').toLocaleLowerCase().includes(query));
    });
    document.querySelectorAll('[data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === state.filter)));
    $('task-selection-bar').hidden = !state.historySelected.size;
    $('task-selection-label').textContent = `已选择 ${state.historySelected.size} 个文件`;
    if (!matches.length) {
      $('job-list').innerHTML = state.jobs.length
        ? '<div class="empty-state"><h2>没有符合条件的任务</h2><p>调整筛选条件或搜索其他文件名。</p></div>'
        : '<div class="empty-state"><h2>还没有转换任务</h2><p>添加 PDF 或 Word 文档，转换记录将保存在这里。</p><button class="button primary" data-page="new">新建转换</button></div>';
      updateAvailability();
      return;
    }
    let previousGroup = null;
    const parts = [];
    for (const job of matches) {
      const date = dateParts(job.created_at);
      if (date.key !== previousGroup) {
        parts.push(`<h2 class="date-heading">${escapeHTML(date.group)}</h2>`);
        previousGroup = date.key;
      }
      const items = job.items || [];
      const active = activeStates.has(job.state);
      const title = job.title || (job.mode === 'convert' && items.length === 1 ? items[0].name : `${modeNames[job.mode] || '文档转换'} · ${job.source_total ?? items.length} 个文件`);
      const controls = active
        ? `<button class="button" data-action="stop-job" data-id="${escapeHTML(job.id)}" ${job.stop_requested || state.pending.has(`stop-${job.id}`) ? 'disabled' : ''}>${job.stop_requested ? '等待当前文件结束' : '停止后续文件'}</button>`
        : `<button class="button ghost" data-action="delete-job" data-id="${escapeHTML(job.id)}">删除记录</button>`;
      const itemRows = items.map(item => {
        const selectable = Boolean(item.source_id) && job.mode !== 'merge';
        const itemActive = activeStates.has(item.state);
        const pageInfo = item.kind === 'PDF' && item.pages ? `${item.pages} 页` : item.kind === 'DOCX' ? 'Word 文档' : 'PDF 文档';
        const checkbox = selectable ? `<input type="checkbox" data-history-id="${escapeHTML(item.id)}" aria-label="选择 ${escapeHTML(item.name)}" ${state.historySelected.has(item.id) ? 'checked' : ''}>` : '<span aria-hidden="true"></span>';
        const label = item.state === 'failed' ? '查看原因' : itemActive ? '等待结果' : item.state === 'completed' ? '查看结果' : '查看详情';
        return `<div class="file-row">${checkbox}${fileMarkup(item, pageInfo)}<div class="file-actions">${statusMarkup(item.state)}<button class="button" data-action="open-result" data-id="${escapeHTML(item.id)}" ${itemActive ? 'disabled' : ''}>${label}</button></div></div>`;
      }).join('');
      let progress = '';
      if (active) {
        const total = Math.max(1, Number(job.source_total ?? job.total ?? items.length));
        const processed = Math.min(total, Math.max(0, Number(job.processed_sources ?? job.done ?? 0)));
        const current = items.find(item => item.state === 'running');
        const caption = job.stop_requested ? '已请求停止，将在当前文件处理完成后停止。' : current ? `正在处理：${current.name}` : '等待处理';
        progress = `<div class="job-progress"><div class="progress-track" role="progressbar" aria-label="文件处理进度" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${processed}"><div class="progress-fill" style="width:${processed / total * 100}%"></div></div><div class="progress-caption">已处理 ${processed} / ${total} 个源文件 · ${escapeHTML(caption)}</div></div>`;
      }
      parts.push(`<article class="job"><header class="job-header"><div class="min-zero"><h3>${escapeHTML(title)}</h3><span class="quiet">${escapeHTML(date.time)} · ${escapeHTML(modeNames[job.mode] || '文档转换')} · ${escapeHTML(job.format === 'html' ? 'HTML' : 'Markdown')}</span></div><div class="actions">${statusMarkup(job.state)}${controls}</div></header><div class="job-items">${itemRows}</div>${progress}</article>`);
    }
    $('job-list').innerHTML = parts.join('');
    updateAvailability();
  }

  function setJobs(jobs) {
    if (!Array.isArray(jobs)) throw new Error('无法读取任务列表。');
    const signature = JSON.stringify(jobs);
    if (signature === state.jobsSignature) return;
    state.jobs = jobs;
    state.jobsSignature = signature;
    for (const id of state.historySelected) if (!findItem(id)) state.historySelected.delete(id);
    renderRecents();
    if (state.page === 'tasks') renderJobs();
  }

  async function refreshJobs() { setJobs(await api('list_jobs')); }
  function schedulePoll() {
    clearTimeout(state.pollTimer);
    if (!state.ready) return;
    state.pollTimer = setTimeout(async () => {
      if (!state.polling) {
        state.polling = true;
        try { await refreshJobs(); state.pollFailureShown = false; }
        catch (error) {
          if (!state.pollFailureShown) { toast(`任务列表更新失败：${errorMessage(error)}`, true); state.pollFailureShown = true; }
        } finally { state.polling = false; }
      }
      schedulePoll();
    }, state.jobs.some(job => activeStates.has(job.state)) ? 1200 : 4000);
  }

  const optionGroups = [
    ['文本整理', [['remove_cjk_spaces', '去除中文间空格'], ['merge_broken_paragraphs', '合并断裂短行'], ['fix_headings', '修复章节标题'], ['merge_blank_lines', '压缩连续空行']]],
    ['表格与页面', [['merge_cross_page_tables', '合并跨页／连续表格'], ['filter_footer', '过滤 PDF 页脚']]],
    ['业务文档规则', [['business_mode', '启用业务模式'], ['fix_list_number_positions', '修复序号位置'], ['infer_empty_headers', '推断空表头']]],
    ['输出内容', [['extract_images', '提取文档图片'], ['add_front_matter', '添加 YAML 文档元数据']]]
  ];
  const optionHints = { business_mode: '同时启用下列两项业务规则，可再单独调整。', fix_list_number_positions: '修复特定业务文档中错位的序号及表代码。', infer_empty_headers: '当某列非空内容一致时，用该内容补全空表头。' };
  const optionKeys = optionGroups.flatMap(([, fields]) => fields.map(([key]) => key)).concat('enable_ocr');

  function optionFields(options, prefix) {
    const groups = optionGroups.map(([name, fields]) => `<fieldset class="option-group"><legend>${escapeHTML(name)}</legend><div class="option-grid">${fields.map(([key, label]) => `<label class="check"><input type="checkbox" name="${key}" ${options[key] ? 'checked' : ''}><span>${escapeHTML(label)}${optionHints[key] ? `<span class="option-hint">${escapeHTML(optionHints[key])}</span>` : ''}</span></label>`).join('')}</div>${name === '输出内容' ? '<p class="option-helper">图片与结果一同保存；文档元数据用于 Markdown 输出。</p>' : ''}</fieldset>`).join('');
    const range = Array.isArray(options.page_range) ? options.page_range.join('-') : '';
    return groups + `<fieldset class="option-group ocr-options" aria-describedby="${prefix}-ocr-status" ${!state.ocr.available ? 'disabled' : ''}><legend>扫描件识别</legend><p id="${prefix}-ocr-status" class="ocr-status ${state.ocr.available ? 'available' : ''}">${escapeHTML(state.ocr.available ? 'OCR 已就绪' : 'OCR 不可用')} · ${escapeHTML(state.ocr.message || (state.ocr.available ? '本地识别引擎可用' : '未安装 PaddleOCR'))}</p><label class="check"><input type="checkbox" name="enable_ocr" ${options.enable_ocr && state.ocr.available ? 'checked' : ''} ${!state.ocr.available ? 'disabled' : ''}>扫描型 PDF 自动 OCR</label><div class="option-inline"><label for="${prefix}-ocr-language">识别语言</label><select id="${prefix}-ocr-language" name="ocr_lang" ${!state.ocr.available ? 'disabled' : ''}><option value="ch" ${options.ocr_lang === 'ch' ? 'selected' : ''}>中文</option><option value="en" ${options.ocr_lang === 'en' ? 'selected' : ''}>英文</option><option value="ch_en" ${options.ocr_lang === 'ch_en' ? 'selected' : ''}>中英混合</option></select></div></fieldset><fieldset class="option-group"><legend>PDF 页码范围</legend><div class="option-inline"><label for="${prefix}-page-range">处理页码</label><input id="${prefix}-page-range" name="page_range" type="text" value="${escapeHTML(range)}" placeholder="全部页，例如 5-10" aria-describedby="${prefix}-range-help"></div><p id="${prefix}-range-help" class="option-helper">留空表示全部页面，仅对 PDF 生效。</p></fieldset>`;
  }

  function parsePageRange(value) {
    const text = value.trim();
    if (!text) return null;
    const match = text.match(/^(\d+)\s*-\s*(\d+)$/);
    const start = match ? Number(match[1]) : 0;
    const end = match ? Number(match[2]) : 0;
    if (!match || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start) {
      throw new Error('请输入有效页码范围，例如 5-10；页码应为正整数且结束页不小于开始页。');
    }
    return [start, end];
  }

  function readOptions(container, original) {
    const options = clone(original);
    for (const key of optionKeys) {
      const input = container.querySelector(`[name="${key}"]`);
      if (input) options[key] = Boolean(input.checked);
    }
    options.ocr_lang = container.querySelector('[name="ocr_lang"]').value;
    const rangeInput = container.querySelector('[name="page_range"]');
    rangeInput.setCustomValidity('');
    try { options.page_range = parsePageRange(rangeInput.value); }
    catch (error) {
      rangeInput.setCustomValidity(errorMessage(error));
      rangeInput.reportValidity();
      throw error;
    }
    return options;
  }

  function renderSettings() {
    const settings = state.settingsDraft;
    if (!settings) return;
    renderOutputLocation('settings');
    $('settings-format').value = settings.format;
    $('settings-theme').value = settings.theme || 'system';
    $('settings-options').innerHTML = optionFields(settings.options, 'defaults');
    const rangeError = document.createElement('p');
    rangeError.id = 'defaults-range-error';
    rangeError.className = 'form-error';
    rangeError.setAttribute('role', 'status');
    rangeError.hidden = true;
    $('defaults-range-help').after(rangeError);
    $('defaults-page-range').setAttribute('aria-describedby', 'defaults-range-help defaults-range-error');
    renderSettingsStatus();
  }

  function renderSettingsStatus() {
    const status = $('settings-save-status');
    const saving = settingsSave.running || settingsSave.savedRevision < settingsSave.revision;
    let message = settingsSave.revision ? '已自动保存' : '';
    let kind = 'saved';
    if (settingsSave.error) { message = `未保存：${settingsSave.error}`; kind = 'error'; }
    else if (saving) { message = '正在保存…'; kind = 'saving'; }
    else if (settingsSave.rangePending) { message = '等待页码输入完成…'; kind = 'saving'; }
    else if (settingsSave.rangeError) { message = '页码范围未保存，其他设置已保存'; kind = 'error'; }
    status.textContent = message;
    status.hidden = !message;
    status.dataset.state = kind;
    $('retry-settings').hidden = !settingsSave.error;
    $('retry-settings').disabled = settingsSave.running;
  }

  function settingsChanged() {
    settingsSave.revision += 1;
    settingsSave.error = '';
    if (!state.queue.length) state.task = clone(state.settingsDraft);
    persistSettings();
  }

  async function persistSettings() {
    if (!state.ready || settingsSave.running) return;
    settingsSave.running = true;
    settingsSave.error = '';
    renderSettingsStatus();
    try {
      // Only one write may run at a time. New changes are saved next, and an
      // older response must never replace the current form or theme.
      while (settingsSave.savedRevision < settingsSave.revision) {
        const revision = settingsSave.revision;
        const draft = clone(state.settingsDraft);
        try {
          state.settings = clone(await api('save_settings', draft));
          settingsSave.savedRevision = revision;
        } catch (error) {
          if (revision !== settingsSave.revision) continue;
          settingsSave.error = errorMessage(error);
          toast(`设置未保存：${settingsSave.error}。请在设置页重试。`, true);
          break;
        }
      }
    } finally {
      settingsSave.running = false;
      renderSettingsStatus();
    }
  }

  function saveSettingsRange() {
    clearTimeout(settingsSave.rangeTimer);
    settingsSave.rangePending = false;
    const input = $('defaults-page-range');
    const error = $('defaults-range-error');
    let range;
    try { range = parsePageRange(input.value); }
    catch (failure) {
      settingsSave.rangeError = errorMessage(failure);
      input.setCustomValidity(settingsSave.rangeError);
      input.setAttribute('aria-invalid', 'true');
      error.textContent = `${settingsSave.rangeError} 此项未保存，继续使用上次有效范围。`;
      error.hidden = false;
      renderSettingsStatus();
      return;
    }
    settingsSave.rangeError = '';
    input.setCustomValidity('');
    input.removeAttribute('aria-invalid');
    error.hidden = true;
    if (JSON.stringify(range) !== JSON.stringify(state.settingsDraft.options.page_range)) {
      state.settingsDraft.options.page_range = range;
      settingsChanged();
    }
    renderSettingsStatus();
  }

  function changeSetting(target) {
    if (!state.ready) return;
    if (target.name === 'page_range') { saveSettingsRange(); return; }
    const previous = JSON.stringify(state.settingsDraft);
    if (target.id === 'settings-theme') {
      state.settingsDraft.theme = target.value;
      applyTheme(target.value);
    } else if (target.id === 'settings-format') state.settingsDraft.format = target.value;
    else if (target.name === 'ocr_lang') state.settingsDraft.options.ocr_lang = target.value;
    else if (optionKeys.includes(target.name)) {
      state.settingsDraft.options[target.name] = target.checked;
      if (target.name === 'business_mode') {
        for (const name of ['fix_list_number_positions', 'infer_empty_headers']) state.settingsDraft.options[name] = target.checked;
      }
    }
    if (previous !== JSON.stringify(state.settingsDraft)) settingsChanged();
  }

  function openTaskOptions() {
    $('task-options-fields').innerHTML = optionFields(state.task.options, 'task');
    $('options-error').hidden = true;
    $('options-dialog').showModal();
  }

  function restoreConfirmationFocus(trigger) {
    const candidates = [trigger];
    if (trigger?.dataset.action) {
      // Polling may have replaced the original button while the dialog was open.
      candidates.push(...Array.from(document.querySelectorAll('[data-action]')).filter(button =>
        button.dataset.action === trigger.dataset.action && button.dataset.id === trigger.dataset.id));
    }
    if (state.page === 'tasks') candidates.push($('task-search'));
    if (state.page === 'new') candidates.push(document.querySelector('#import-empty [data-action="choose-files"]'));
    candidates.find(element => element?.isConnected && !element.disabled && element.getClientRects().length)?.focus({ preventScroll: true });
  }

  function confirmAction(title, message, label = '确认', trigger = document.activeElement) {
    if (state.confirmResolver) return Promise.resolve(false);
    return new Promise(resolve => {
      state.confirmResolver = resolve;
      state.confirmTrigger = trigger;
      $('confirm-title').textContent = title;
      $('confirm-message').textContent = message;
      $('confirm-submit').textContent = label;
      $('confirm-dialog').showModal();
      $('confirm-cancel').focus({ preventScroll: true });
    });
  }

  function closeConfirmation(confirmed = false) {
    const resolve = state.confirmResolver;
    const trigger = state.confirmTrigger;
    state.confirmResolver = null;
    state.confirmTrigger = null;
    $('confirm-dialog').close();
    restoreConfirmationFocus(trigger);
    resolve?.(confirmed);
  }

  function openMerge(files) {
    const seen = new Set();
    state.mergeFiles = files.filter(file => {
      if (!file?.id || seen.has(file.id)) return false;
      seen.add(file.id); return true;
    }).map(file => ({ ...file }));
    if (state.mergeFiles.length < 2) { toast('请至少选择两个不同的源文件。'); return; }
    $('merge-title').value = '合并文档';
    $('merge-output').textContent = `输出到${directoryName(state.task.output_dir)}`;
    renderMergeList();
    $('merge-dialog').showModal();
  }

  function renderMergeList() {
    $('merge-list').innerHTML = state.mergeFiles.map((file, index) => `<div class="merge-row"><span class="merge-order">${index + 1}</span><span class="merge-name">${escapeHTML(file.name)}</span><button type="button" class="icon-button" data-action="merge-up" data-index="${index}" aria-label="上移 ${escapeHTML(file.name)}" ${index === 0 ? 'disabled' : ''}>${icon('up')}</button><button type="button" class="icon-button" data-action="merge-down" data-index="${index}" aria-label="下移 ${escapeHTML(file.name)}" ${index === state.mergeFiles.length - 1 ? 'disabled' : ''}>${icon('down')}</button></div>`).join('');
    updateAvailability();
  }

  async function startJob(files, mode = 'convert', title = '') {
    if (!files.length) { toast('请先选择文件。'); return; }
    await perform('start-job', async () => {
      const task = clone(state.task);
      const jobTitle = mode === 'merge' ? (title || '合并文档') : mode === 'summary' ? '大纲与摘要' : files.length === 1 ? files[0].name : `批量转换 · ${files.length} 个文件`;
      const result = await api('start_job', files.map(file => file.id), task.options, task.output_dir, mode === 'merge' ? 'md' : task.format, mode, jobTitle);
      if (!result?.id) throw new Error('任务未能建立，请重试。');
      if ($('merge-dialog').open) $('merge-dialog').close();
      state.queue = [];
      state.selected.clear();
      state.historySelected.clear();
      state.task = clone(state.settingsDraft);
      state.filter = 'all';
      state.query = '';
      $('task-search').value = '';
      switchPage('tasks');
      await refreshJobs();
      schedulePoll();
      toast(mode === 'summary' ? '已开始提取大纲与摘要' : mode === 'merge' ? '合并任务已建立' : '转换任务已建立');
    });
  }

  function renderSummary(summary) {
    const stats = summary?.stats;
    $('summary-stats').innerHTML = stats ? `<span>${escapeHTML(stats.paragraphs ?? 0)} 段正文</span><span>${escapeHTML(stats.tables ?? 0)} 个表格</span><span>${escapeHTML(stats.table_rows ?? 0)} 行表格内容</span>` : '<span>暂无文档统计</span>';
    const outline = summary?.outline || [];
    $('summary-outline').innerHTML = outline.length ? outline.map(item => `<article class="outline-item" style="padding-left:${Math.min(4, Math.max(0, Number(item.level || 1) - 1)) * 12}px"><h3>${escapeHTML(item.heading)}</h3>${item.preview ? `<p>${escapeHTML(item.preview)}</p>` : ''}</article>`).join('') : '<p class="quiet small">未检测到标题结构。</p>';
  }

  function setResultView(view) {
    const previous = resultPanes.find(pane => !pane.hidden);
    const range = previous.scrollHeight - previous.clientHeight;
    const progress = range > 0 ? previous.scrollTop / range : 0;
    state.resultView = view;
    $('rendered-result').hidden = view !== 'rendered';
    $('markdown-result').hidden = view !== 'source';
    document.querySelectorAll('[data-result-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.resultView === view)));
    const current = resultPanes.find(pane => !pane.hidden);
    if (current !== previous) {
      syncing.add(current);
      current.scrollTop = progress * Math.max(0, current.scrollHeight - current.clientHeight);
      requestAnimationFrame(() => requestAnimationFrame(() => syncing.delete(current)));
    }
  }

  async function openResult(id) {
    const request = ++state.resultRequest;
    ++state.previewRequest;
    clearPDFPreview();
    state.resultId = id;
    state.result = null;
    state.syncSourceId = null;
    $('sync-scroll').checked = false;
    $('sync-scroll').disabled = true;
    for (const pane of resultPanes) pane.scrollTop = 0;
    state.logSelection = '';
    switchPage('result');
    const found = findItem(id);
    $('result-title').textContent = found?.item.name || '转换结果';
    $('result-subtitle').textContent = '';
    $('result-loading').hidden = false;
    $('result-content').hidden = true;
    $('result-error').hidden = true;
    $('export-result').disabled = true;
    try {
      const result = await api('get_result', id);
      if (request !== state.resultRequest) return;
      state.result = result;
      const item = result.item || found?.item || {};
      $('result-title').textContent = item.name || '转换结果';
      $('result-subtitle').textContent = item.output_path || item.path || '';
      $('result-subtitle').title = $('result-subtitle').textContent;
      $('result-title').title = $('result-title').textContent;
      $('result-state').className = `status ${Object.hasOwn(stateNames, item.state) ? item.state : 'completed'}`;
      $('result-state').textContent = stateNames[item.state] || '已完成';
      const hasContent = Boolean(result.markdown || result.html);
      $('export-result').disabled = !hasContent;
      $('copy-markdown').disabled = !result.markdown;
      $('reveal-result').disabled = !item.output_path;
      $('rendered-result').innerHTML = result.html || '<p class="quiet">没有可阅读的转换结果。可打开大纲与摘要或日志查看详情。</p>';
      $('markdown-result').textContent = result.markdown || '没有 Markdown 内容。';
      $('result-logs').textContent = result.logs || '没有处理日志。';
      renderSummary(result.summary);
      if (item.state === 'failed') openDrawer('log');
      if (item.error) {
        $('result-error').hidden = false;
        $('result-error').classList.toggle('warning-banner', item.state === 'completed');
        $('result-error').textContent = `${item.state === 'completed' ? '结果已生成，但有内容未处理：' : '处理未完成：'}${item.error}`;
      }
      const sources = result.sources || [];
      $('source-select').innerHTML = sources.map(source => `<option value="${escapeHTML(source.id)}">${escapeHTML(source.name)}${source.exists === false ? '（原文件缺失）' : ''}</option>`).join('');
      $('source-select-label').hidden = sources.length < 2;
      $('result-content').hidden = false;
      setResultView(state.resultView);
      requestAnimationFrame(() => setSplit(splitPreference));
      if (sources.length) {
        const source = sources.find(candidate => candidate.exists !== false) || sources[0];
        $('source-select').value = source.id;
        await loadSource(source.id);
      } else {
        $('source-kind').textContent = '原文';
        $('pdf-controls').hidden = true;
        $('source-note').hidden = true;
        $('source-preview').innerHTML = '<div class="empty-state">没有可预览的源文件。</div>';
      }
    } catch (error) {
      if (request !== state.resultRequest) return;
      $('result-error').classList.remove('warning-banner');
      $('result-error').textContent = errorMessage(error);
      $('result-error').hidden = false;
      toast(errorMessage(error), true);
    } finally {
      if (request === state.resultRequest) $('result-loading').hidden = true;
    }
  }

  function updatePDFControls(force = false) {
    if (force || !state.pdfPageEditing) $('pdf-page-number').value = state.sourcePage;
    $('pdf-page-number').max = state.sourceTotal;
    $('pdf-total').textContent = `/ ${state.sourceTotal}`;
    $('pdf-prev').disabled = state.sourceLoading || state.sourcePage <= 1;
    $('pdf-next').disabled = state.sourceLoading || state.sourcePage >= state.sourceTotal;
    $('pdf-page-number').disabled = state.sourceLoading;
  }

  function applyZoom() {
    const view = state.pdfView;
    if (!view || state.page !== 'result') return;
    const zoom = $('pdf-zoom').value;
    const pane = sourcePane;
    const style = getComputedStyle(pane);
    const width = pane.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const height = pane.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - 28;
    if (width <= 0 || height <= 0) return;
    const layout = `${width}:${height}:${zoom}`;
    if (view.layout === layout) return;
    const top = pane.scrollTop;
    const anchor = view.pages[pdfPageAtOffset(view, top - view.document.offsetTop)];
    const progress = (top - view.document.offsetTop - anchor.node.offsetTop) / anchor.node.offsetHeight;
    for (const slot of view.pages) {
      const fitted = zoom === 'page' ? Math.min(width, height * slot.width / slot.height) : width;
      slot.node.style.width = `${Math.max(1, zoom === 'fit' || zoom === 'page' ? fitted : slot.width * Number(zoom) / 100)}px`;
    }
    view.layout = layout;
    pane.scrollTop = top === 0 ? 0 : view.document.offsetTop + anchor.node.offsetTop + progress * anchor.node.offsetHeight;
    try { sessionStorage.setItem('flipmd-zoom', zoom); } catch { /* Storage may be unavailable. */ }
    schedulePDFViewport();
    syncScroll(sourcePane, resultPanes.find(pane => !pane.hidden));
  }

  function clearPDFPreview() {
    if (state.pdfView) cancelAnimationFrame(state.pdfView.frame);
    state.pdfView = null;
  }

  function pdfPageAtOffset(view, offset) {
    let low = 0, high = view.pages.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (view.pages[middle].node.offsetTop <= offset) low = middle;
      else high = middle - 1;
    }
    return low;
  }

  function pdfPagePlaceholder(slot) {
    slot.status = 'empty';
    slot.sheet.setAttribute('aria-busy', 'true');
    slot.sheet.innerHTML = `<div class="pdf-page-status quiet small">正在加载第 ${slot.page} 页…</div>`;
  }

  async function showPDFPage(view, slot, preview) {
    if (preview.kind !== 'PDF' || preview.page !== slot.page || preview.total !== view.pages.length) {
      throw new Error('原文页数已变化，请刷新结果后重试。');
    }
    if (!/^data:image\/(png|jpeg|webp);/i.test(preview.data_url || '')) throw new Error('原文预览图像格式无效。');
    const image = document.createElement('img');
    image.className = 'source-image';
    image.alt = `${view.name}，第 ${slot.page} 页`;
    image.src = preview.data_url;
    await image.decode();
    if (state.pdfView !== view) return;
    slot.sheet.replaceChildren(image);
    slot.sheet.setAttribute('aria-busy', 'false');
    slot.status = 'ready';
  }

  async function renderPDFPage(view, slot) {
    slot.status = 'loading';
    view.pending += 1;
    try {
      const preview = await api('preview_source', view.id, slot.page);
      if (state.pdfView !== view) return;
      await showPDFPage(view, slot, preview);
    } catch (error) {
      if (state.pdfView !== view) return;
      slot.status = 'error';
      slot.sheet.setAttribute('aria-busy', 'false');
      slot.sheet.innerHTML = `<div class="pdf-page-status small"><p>第 ${slot.page} 页加载失败</p><p class="quiet">${escapeHTML(errorMessage(error))}</p><button class="button" data-action="retry-pdf-page" data-page-number="${slot.page}">重试此页</button></div>`;
    } finally {
      view.pending -= 1;
      if (state.pdfView === view) schedulePDFViewport();
    }
  }

  function schedulePDFViewport() {
    const view = state.pdfView;
    if (!view || view.frame || state.page !== 'result') return;
    view.frame = requestAnimationFrame(() => {
      view.frame = null;
      if (state.pdfView !== view || !sourcePane.clientHeight) return;
      const top = sourcePane.scrollTop - view.document.offsetTop;
      const height = sourcePane.clientHeight;
      const atEnd = sourcePane.scrollTop > 0 && Math.ceil(sourcePane.scrollTop + height) >= sourcePane.scrollHeight - 1;
      const current = atEnd ? view.pages.length - 1 : pdfPageAtOffset(view, top + Math.min(120, height / 4));
      state.sourcePage = current + 1;
      updatePDFControls();
      // All page spaces remain in the document; rasterize the viewport and a
      // screen on either side. Keep a small nearby image cache when scrolling.
      const first = pdfPageAtOffset(view, top - height);
      const last = pdfPageAtOffset(view, top + height * 2);
      const nearby = view.pages.slice(first, last + 1);
      const cached = view.pages.filter(slot => slot.status === 'ready' && !nearby.includes(slot))
        .sort((a, b) => Math.abs(a.page - state.sourcePage) - Math.abs(b.page - state.sourcePage));
      for (const slot of cached.slice(Math.max(0, 10 - nearby.length))) pdfPagePlaceholder(slot);
      const waiting = nearby.filter(slot => slot.status === 'empty')
        .sort((a, b) => Math.abs(a.page - state.sourcePage) - Math.abs(b.page - state.sourcePage));
      while (view.pending < 2 && waiting.length) renderPDFPage(view, waiting.shift());
    });
  }

  function goToPDFPage(page) {
    const view = state.pdfView;
    if (!view || state.sourceLoading || !Number.isSafeInteger(page) || page < 1 || page > view.pages.length) return;
    state.sourcePage = page;
    state.pdfPageEditing = false;
    updatePDFControls(true);
    sourcePane.scrollTop = view.pages[page - 1].node.offsetTop;
    schedulePDFViewport();
    syncScroll(sourcePane, resultPanes.find(pane => !pane.hidden));
  }

  async function createPDFPreview(id, source, preview) {
    if (!Number.isSafeInteger(preview.total) || preview.total < 1 || !Array.isArray(preview.page_sizes) ||
        preview.page_sizes.length !== preview.total || preview.page_sizes.some(size =>
          !Number.isFinite(size.width) || size.width <= 0 || !Number.isFinite(size.height) || size.height <= 0)) {
      throw new Error('无法读取 PDF 页面尺寸，请重新打开文件。');
    }
    const documentNode = document.createElement('div');
    documentNode.className = 'pdf-document';
    const view = { id, name: source?.name || 'PDF', document: documentNode, pages: [], pending: 0, frame: null };
    for (const [index, size] of preview.page_sizes.entries()) {
      const node = document.createElement('figure');
      node.className = 'pdf-page';
      node.dataset.pageNumber = index + 1;
      const sheet = document.createElement('div');
      sheet.className = 'pdf-page-sheet';
      sheet.style.aspectRatio = `${size.width} / ${size.height}`;
      const label = document.createElement('figcaption');
      label.className = 'pdf-page-label quiet small';
      label.textContent = `第 ${index + 1} 页 / 共 ${preview.total} 页`;
      node.append(sheet, label);
      documentNode.append(node);
      const slot = { node, sheet, page: index + 1, ...size };
      pdfPagePlaceholder(slot);
      view.pages.push(slot);
    }
    state.sourceTotal = preview.total;
    state.pdfView = view;
    sourcePane.replaceChildren(documentNode);
    view.pages[0].status = 'loading';
    applyZoom();
    await showPDFPage(view, view.pages[0], preview);
  }

  async function loadSource(id, page = 1) {
    const request = ++state.previewRequest;
    clearPDFPreview();
    const resultId = state.resultId;
    const source = state.result?.sources?.find(candidate => candidate.id === id);
    state.sourceId = id;
    $('sync-scroll').disabled = true;
    state.sourcePage = page;
    state.pdfPageEditing = false;
    state.sourceTotal = 1;
    state.sourceLoading = true;
    $('source-preview').setAttribute('aria-busy', 'true');
    $('source-kind').textContent = source?.kind === 'DOCX' ? 'DOCX 内容预览' : 'PDF 原文';
    $('source-note').hidden = true;
    $('pdf-controls').hidden = source?.kind !== 'PDF';
    updatePDFControls();
    $('source-preview').innerHTML = '<div class="empty-state" role="status">正在读取原文…</div>';
    if (source?.exists === false) {
      $('source-preview').innerHTML = '<div class="empty-state"><h2>原文件已移动或删除</h2><p>已保存的转换结果仍可在右侧阅读与导出。</p></div>';
      $('pdf-controls').hidden = true;
      state.sourceLoading = false;
      $('source-preview').setAttribute('aria-busy', 'false');
      return;
    }
    try {
      const preview = await api('preview_source', id, 1);
      if (request !== state.previewRequest || resultId !== state.resultId) return;
      if (preview.kind === 'PDF') {
        await createPDFPreview(id, source, preview);
        if (request !== state.previewRequest || resultId !== state.resultId) return;
        $('pdf-controls').hidden = false;
      } else if (preview.kind === 'DOCX') {
        const content = document.createElement('div');
        content.className = 'docx-preview document-body';
        content.innerHTML = preview.html || '<p class="quiet">文档没有可预览的内容。</p>';
        $('source-preview').replaceChildren(content);
        $('pdf-controls').hidden = true;
      } else throw new Error('当前原文格式不支持预览。');
      if (state.syncSourceId !== id) {
        $('sync-scroll').checked = true;
        state.syncSourceId = id;
      }
      $('sync-scroll').disabled = false;
      $('sync-note').textContent = '按全文比例近似同步';
      const backendNote = String(preview.note || '').trim();
      const docxNote = preview.kind === 'DOCX' && !/不还原\s*Word\s*分页/i.test(backendNote)
        ? '源文件内容预览 · 不还原 Word 分页、字体及复杂版式。'
        : '';
      const note = [docxNote, backendNote].filter(Boolean).join(' ');
      $('source-note').textContent = note;
      $('source-note').hidden = !note;
      $('source-preview').scrollTop = 0;
      $('source-preview').scrollLeft = 0;
      for (const pane of resultPanes) pane.scrollTop = 0;
    } catch (error) {
      if (request !== state.previewRequest || resultId !== state.resultId) return;
      clearPDFPreview();
      $('source-preview').innerHTML = `<div class="empty-state"><h2>无法预览原文</h2><p>${escapeHTML(errorMessage(error))}</p><button class="button" data-action="retry-source">重试预览</button></div>`;
      $('pdf-controls').hidden = true;
    } finally {
      if (request === state.previewRequest) {
        state.sourceLoading = false;
        $('source-preview').setAttribute('aria-busy', 'false');
        updatePDFControls();
        goToPDFPage(Math.min(page, state.sourceTotal));
      }
    }
  }

  function currentLogSelection() {
    const selection = window.getSelection();
    const logs = $('result-logs');
    return selection && logs.contains(selection.anchorNode) && logs.contains(selection.focusNode) ? selection.toString() : '';
  }

  async function handleAction(action, button) {
    const id = button.dataset.id;
    switch (action) {
      case 'choose-files':
      case 'choose-folder':
        await perform('choose-files', async () => {
          const files = await api('choose_files', action === 'choose-folder');
          if (files?.length) receiveFiles(files);
        }, button); break;
      case 'task-options': openTaskOptions(); break;
      case 'clear-queue':
        if (await confirmAction('清空导入列表？', '只移除当前导入的文件，不会删除磁盘上的源文件。', '清空列表', button)) {
          state.queue = []; state.selected.clear(); state.task = clone(state.settingsDraft); renderQueue();
          restoreConfirmationFocus(button);
        } break;
      case 'remove-queue':
        state.queue = state.queue.filter(file => !state.selected.has(file.id)); state.selected.clear();
        if (!state.queue.length) state.task = clone(state.settingsDraft);
        renderQueue(); break;
      case 'remove-one':
        state.queue = state.queue.filter(file => file.id !== id); state.selected.delete(id);
        if (!state.queue.length) state.task = clone(state.settingsDraft);
        renderQueue(); break;
      case 'choose-task-output':
      case 'choose-default-output':
        await perform('choose-output', async () => {
          const path = await api('choose_output');
          if (typeof path !== 'string' || !path) return;
          const scope = action === 'choose-task-output' ? 'task' : 'settings';
          const config = scope === 'task' ? state.task : state.settingsDraft;
          config.output_dir = path;
          renderOutputLocation(scope);
          if (scope === 'settings') settingsChanged();
        }, button); break;
      case 'reset-task-output': state.task.output_dir = ''; renderOutputLocation('task'); break;
      case 'reset-default-output': state.settingsDraft.output_dir = ''; renderOutputLocation('settings'); settingsChanged(); break;
      case 'retry-settings': await persistSettings(); break;
      case 'start-convert': await startJob(state.queue); break;
      case 'summary-queue': await startJob(state.queue.filter(file => state.selected.has(file.id)), 'summary'); break;
      case 'merge-queue': openMerge(state.queue.filter(file => state.selected.has(file.id))); break;
      case 'merge-history': openMerge(selectedHistoryFiles()); break;
      case 'clear-history-selection': state.historySelected.clear(); renderJobs(); break;
      case 'merge-up':
      case 'merge-down': {
        const index = Number(button.dataset.index);
        const destination = index + (action === 'merge-up' ? -1 : 1);
        if (destination >= 0 && destination < state.mergeFiles.length) {
          [state.mergeFiles[index], state.mergeFiles[destination]] = [state.mergeFiles[destination], state.mergeFiles[index]];
          renderMergeList();
        } break;
      }
      case 'stop-job':
        await perform(`stop-${id}`, async () => {
          const accepted = await api('stop_job', id);
          await refreshJobs();
          toast(accepted ? '已请求停止，将在当前文件处理完成后停止。' : '任务已经结束，无需停止。');
        }, button); break;
      case 'delete-job': {
        const job = state.jobs.find(candidate => candidate.id === id);
        if (!job || activeStates.has(job.state)) { toast('处理中和等待中的任务不能删除。'); break; }
        const position = Array.from(document.querySelectorAll('[data-action="delete-job"]')).indexOf(button);
        if (await confirmAction('删除这条任务记录？', '仅删除历史记录。源文件和导出文件都会保留。', '删除记录', button)) {
          const deleted = await perform(`delete-${id}`, async () => {
            await api('delete_job', id);
            await refreshJobs();
            toast('任务记录已删除，磁盘文件仍然保留。');
            return true;
          });
          // The deleted record's button no longer exists. Keep the same place
          // in the list without stealing focus if the user has moved elsewhere.
          if (deleted && state.page === 'tasks' && document.activeElement === document.body) {
            const buttons = document.querySelectorAll('[data-action="delete-job"]');
            const next = buttons[Math.max(0, Math.min(position, buttons.length - 1))];
            (next || $('task-search')).focus({ preventScroll: true });
          }
        } break;
      }
      case 'open-result': await openResult(id); break;
      case 'refresh-result': if (state.resultId) await openResult(state.resultId); break;
      case 'toggle-summary':
        if (state.result) openDrawer('summary'); break;
      case 'toggle-log': if (state.result) openDrawer('log'); break;
      case 'pdf-prev': goToPDFPage(state.sourcePage - 1); break;
      case 'pdf-next': goToPDFPage(state.sourcePage + 1); break;
      case 'retry-pdf-page': {
        const slot = state.pdfView?.pages[Number(button.dataset.pageNumber) - 1];
        if (slot?.status === 'error') { pdfPagePlaceholder(slot); schedulePDFViewport(); }
        break;
      }
      case 'retry-source': if (state.sourceId) await loadSource(state.sourceId, state.sourcePage); break;
      case 'copy-markdown':
        if (state.result?.markdown) await perform('copy', async () => { await api('copy_text', state.result.markdown); toast('Markdown 已复制。'); }, button); break;
      case 'copy-log-all':
        await perform('copy', async () => { await api('copy_text', state.result?.logs || ''); toast('日志已复制。'); }, button); break;
      case 'copy-log-selection': {
        const text = currentLogSelection() || state.logSelection;
        if (!text) { toast('请先在日志中选择要复制的文字。'); break; }
        await perform('copy', async () => { await api('copy_text', text); toast('选中的日志已复制。'); }, button); break;
      }
      case 'export-log':
        await perform('export-log', async () => { const path = await api('export_log', state.resultId); if (path) toast(`日志已导出到 ${path}`); }, button); break;
      case 'export-result': $('export-dialog').showModal(); break;
      case 'reveal-result':
        await perform('reveal', async () => { await api('reveal_result', state.resultId); }, button); break;
      default: break;
    }
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (link && (link.closest('#rendered-result') || link.closest('#source-preview'))) {
      event.preventDefault();
      const href = link.getAttribute('href');
      if (href) perform('copy-link', async () => { await api('copy_text', href); toast('链接地址已复制。'); });
      return;
    }
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (button.hasAttribute('data-close-dialog')) {
      const dialog = button.closest('dialog');
      if (dialog === $('confirm-dialog')) closeConfirmation();
      else dialog?.close();
      return;
    }
    if (button.dataset.page) { switchPage(button.dataset.page); return; }
    if (button.dataset.filter) { state.filter = button.dataset.filter; renderJobs(); return; }
    if (button.dataset.resultView) { setResultView(button.dataset.resultView); return; }
    if (button.dataset.action && state.ready) handleAction(button.dataset.action, button).catch(error => toast(errorMessage(error), true));
  });

  document.addEventListener('change', event => {
    const target = event.target;
    if (target.dataset.queueId) {
      if (target.checked) state.selected.add(target.dataset.queueId); else state.selected.delete(target.dataset.queueId);
      renderQueue();
    } else if (target.dataset.historyId) {
      if (target.checked) state.historySelected.add(target.dataset.historyId); else state.historySelected.delete(target.dataset.historyId);
      renderJobs();
    } else if (target.id === 'queue-select-all') {
      state.selected = target.checked ? new Set(state.queue.map(file => file.id)) : new Set(); renderQueue();
    } else if (target.id === 'task-format') { state.task.format = target.value; renderOutputLocation('task'); }
    else if (target.id === 'source-select') loadSource(target.value, 1);
    else if (target.id === 'pdf-zoom') applyZoom();
    else if (target.id === 'sync-scroll' && target.checked) syncScroll(sourcePane, resultPanes.find(pane => !pane.hidden));
    else if (target.name === 'business_mode') {
      const form = target.closest('form');
      for (const name of ['fix_list_number_positions', 'infer_empty_headers']) form.querySelector(`[name="${name}"]`).checked = target.checked;
    }
    if (target.closest('#settings-form')) changeSetting(target);
  });

  $('task-search').addEventListener('input', event => { state.query = event.target.value; renderJobs(); });
  document.addEventListener('input', event => {
    if (event.target.name !== 'page_range') return;
    event.target.setCustomValidity('');
    if (event.target.id !== 'defaults-page-range') return;
    clearTimeout(settingsSave.rangeTimer);
    settingsSave.rangePending = true;
    settingsSave.rangeError = '';
    event.target.removeAttribute('aria-invalid');
    $('defaults-range-error').hidden = true;
    renderSettingsStatus();
    settingsSave.rangeTimer = setTimeout(saveSettingsRange, 350);
  });
  document.addEventListener('selectionchange', () => { const selection = currentLogSelection(); if (selection) state.logSelection = selection; });

  $('options-form').addEventListener('submit', event => {
    event.preventDefault();
    try {
      state.task.options = readOptions($('task-options-fields'), state.task.options);
      $('options-dialog').close();
      toast('本次转换设置已更新。');
    } catch (error) { $('options-error').textContent = errorMessage(error); $('options-error').hidden = false; }
  });
  $('merge-form').addEventListener('submit', event => {
    event.preventDefault();
    startJob(state.mergeFiles, 'merge', $('merge-title').value.trim() || '合并文档');
  });
  $('confirm-form').addEventListener('submit', event => {
    event.preventDefault();
    closeConfirmation(true);
  });
  $('confirm-dialog').addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const buttons = Array.from($('confirm-dialog').querySelectorAll('button:not(:disabled)'));
    const index = buttons.indexOf(document.activeElement);
    event.preventDefault();
    const next = (index + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  });
  $('confirm-dialog').addEventListener('cancel', event => {
    event.preventDefault();
    closeConfirmation();
  });
  $('export-form').addEventListener('submit', event => {
    event.preventDefault();
    perform('export', async () => {
      const path = await api('export_result', state.resultId, $('export-format').value);
      if (path) { $('export-dialog').close(); toast(`结果已导出到 ${path}`); }
    }, $('export-submit'));
  });
  $('pdf-page-number').addEventListener('input', () => { state.pdfPageEditing = true; });
  $('pdf-page-number').addEventListener('blur', () => { state.pdfPageEditing = false; updatePDFControls(); });
  $('pdf-page-form').addEventListener('submit', event => {
    event.preventDefault();
    const page = Number($('pdf-page-number').value);
    state.pdfPageEditing = false;
    if (Number.isSafeInteger(page) && page >= 1 && page <= state.sourceTotal) goToPDFPage(page);
    else { toast(`页码应在 1 到 ${state.sourceTotal} 之间。`, true); updatePDFControls(); }
  });
  $('settings-form').addEventListener('submit', event => {
    event.preventDefault();
    saveSettingsRange();
    persistSettings();
  });

  for (const eventName of ['dragenter', 'dragover']) {
    document.addEventListener(eventName, event => {
      if (!event.dataTransfer?.types?.includes('Files')) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
      if (state.ready) $('app').classList.add('drag-over');
    });
  }
  document.addEventListener('dragleave', event => { if (!event.relatedTarget) $('app').classList.remove('drag-over'); });
  document.addEventListener('drop', event => {
    event.preventDefault();
    $('app').classList.remove('drag-over');
    // The native handler owns file paths and calls flipmd.receiveFiles.
  });
  window.addEventListener('beforeunload', () => clearTimeout(state.pollTimer));

  async function initialize() {
    if (state.booting || state.ready) return;
    state.booting = true;
    $('connection-title').textContent = '正在连接 FlipMD';
    $('connection-message').textContent = '正在读取设置与任务记录。';
    $('launch-command').hidden = true;
    $('retry-bootstrap').hidden = true;
    try {
      const data = await api('bootstrap');
      if (!data?.settings?.options) throw new Error('默认设置读取失败。');
      const version = String(data.brand?.version || '').trim();
      $('app-version').textContent = version ? `v${version}` : '';
      $('app-version').hidden = !version;
      $('app-version').setAttribute('aria-label', `FlipMD 版本 ${version}`);
      state.settings = clone(data.settings);
      state.settingsDraft = clone(data.settings);
      state.task = clone(data.settings);
      state.ocr = data.ocr || { available: false, message: '无法检测 OCR 引擎' };
      state.ready = true;
      applyTheme(data.settings.theme);
      document.querySelectorAll('.nav-button').forEach(button => { button.disabled = false; });
      $('connection-panel').hidden = true;
      $('app').setAttribute('aria-busy', 'false');
      setJobs(data.jobs || []);
      renderRecents();
      renderSettings();
      switchPage('new');
      schedulePoll();
    } catch (error) {
      $('connection-title').textContent = '无法连接桌面服务';
      $('connection-message').textContent = errorMessage(error);
      $('launch-command').hidden = false;
      $('retry-bootstrap').hidden = !window.pywebview?.api;
      $('app').setAttribute('aria-busy', 'false');
    } finally { state.booting = false; }
  }

  $('retry-bootstrap').addEventListener('click', initialize);
  window.addEventListener('pywebviewready', initialize);
  setTimeout(() => {
    if (state.ready || state.booting) return;
    if (window.pywebview?.api) { initialize(); return; }
    $('connection-title').textContent = '请在 FlipMD 桌面窗口中打开';
    $('connection-message').textContent = '浏览器页面无法访问本地转换服务。请在项目文件夹运行下方命令。';
    $('launch-command').hidden = false;
    $('app').setAttribute('aria-busy', 'false');
  }, 1800);
})();
