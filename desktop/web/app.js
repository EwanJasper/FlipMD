/* FlipMD desktop client. All document operations use the local pywebview API. */
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));
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
    result: null, resultId: null, resultView: 'rendered', sourceId: null,
    sourcePage: 1, sourceTotal: 1, sourceLoading: false, resultRequest: 0,
    previewRequest: 0, mergeFiles: [], pending: new Set(), jobsSignature: '',
    pollTimer: null, polling: false, logSelection: '', confirmResolver: null
  };
  let toastTimer;

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

  function directoryName(path) { return path || '原文件所在目录'; }
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
    document.querySelectorAll('.page').forEach(element => { element.hidden = element.id !== `page-${page}`; });
    document.querySelectorAll('[data-page]').forEach(button => {
      if (!button.classList.contains('nav-button')) return;
      const active = button.dataset.page === page || (page === 'result' && button.dataset.page === 'tasks');
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    if (page === 'new') renderQueue();
    if (page === 'tasks') renderJobs();
    window.scrollTo({ top: 0, behavior: 'instant' });
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
      return `<div class="file-row"><input type="checkbox" data-queue-id="${escapeHTML(file.id)}" aria-label="选择 ${escapeHTML(file.name)}" ${state.selected.has(file.id) ? 'checked' : ''}>${fileMarkup(file, size ? `${size} · ${file.path}` : file.path)}<button class="icon-button" data-action="remove-one" data-id="${escapeHTML(file.id)}" aria-label="移除 ${escapeHTML(file.name)}">×</button></div>`;
    }).join('');
    $('queue-selection').textContent = state.selected.size ? `已选择 ${state.selected.size} 个` : '可选择文件合并或提取大纲';
    $('queue-select-all').checked = hasFiles && state.selected.size === state.queue.length;
    $('queue-select-all').indeterminate = state.selected.size > 0 && state.selected.size < state.queue.length;
    $('task-format').value = state.task.format;
    $('task-output').textContent = directoryName(state.task.output_dir);
    $('empty-output-label').textContent = `输出到${directoryName(state.task.output_dir)}`;
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
    $('save-settings').disabled = !state.ready || state.pending.has('save-settings');
    document.querySelectorAll('[data-action="choose-files"], [data-action="choose-folder"]').forEach(button => {
      button.disabled = !state.ready || state.pending.has('choose-files') || submitting;
    });
    document.querySelectorAll('[data-action="summary-history"]').forEach(button => {
      button.disabled = !state.historySelected.size || submitting;
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
  const optionKeys = optionGroups.flatMap(([, fields]) => fields.map(([key]) => key)).concat('enable_ocr');

  function optionFields(options, prefix) {
    const groups = optionGroups.map(([name, fields]) => `<fieldset class="option-group"><legend>${escapeHTML(name)}</legend><div class="option-grid">${fields.map(([key, label]) => `<label class="check"><input type="checkbox" name="${key}" ${options[key] ? 'checked' : ''}><span>${escapeHTML(label)}</span></label>`).join('')}</div>${name === '输出内容' ? '<p class="option-helper">图片与结果一同保存；文档元数据用于 Markdown 输出。</p>' : ''}</fieldset>`).join('');
    const range = Array.isArray(options.page_range) ? options.page_range.join('-') : '';
    return groups + `<fieldset class="option-group"><legend>扫描件识别</legend><p class="ocr-status ${state.ocr.available ? 'available' : ''}">${escapeHTML(state.ocr.available ? 'OCR 已就绪' : 'OCR 不可用')} · ${escapeHTML(state.ocr.message || (state.ocr.available ? '本地识别引擎可用' : '未安装 PaddleOCR'))}</p><label class="check"><input type="checkbox" name="enable_ocr" ${options.enable_ocr && state.ocr.available ? 'checked' : ''} ${!state.ocr.available ? 'disabled' : ''}>扫描型 PDF 自动 OCR</label><div class="option-inline"><label for="${prefix}-ocr-language">识别语言</label><select id="${prefix}-ocr-language" name="ocr_lang" ${!state.ocr.available ? 'disabled' : ''}><option value="ch" ${options.ocr_lang === 'ch' ? 'selected' : ''}>中文</option><option value="en" ${options.ocr_lang === 'en' ? 'selected' : ''}>英文</option><option value="ch_en" ${options.ocr_lang === 'ch_en' ? 'selected' : ''}>中英混合</option></select></div></fieldset><fieldset class="option-group"><legend>PDF 页码范围</legend><div class="option-inline"><label for="${prefix}-page-range">处理页码</label><input id="${prefix}-page-range" name="page_range" type="text" value="${escapeHTML(range)}" placeholder="全部页，例如 5-10" aria-describedby="${prefix}-range-help"></div><p id="${prefix}-range-help" class="option-helper">留空表示全部页面，仅对 PDF 生效。</p></fieldset>`;
  }

  function readOptions(container, original) {
    const options = clone(original);
    for (const key of optionKeys) {
      const input = container.querySelector(`[name="${key}"]`);
      if (input) options[key] = Boolean(input.checked);
    }
    options.ocr_lang = container.querySelector('[name="ocr_lang"]').value;
    const rangeInput = container.querySelector('[name="page_range"]');
    const text = rangeInput.value.trim();
    rangeInput.setCustomValidity('');
    if (!text) options.page_range = null;
    else {
      const match = text.match(/^(\d+)\s*-\s*(\d+)$/);
      const start = match ? Number(match[1]) : 0;
      const end = match ? Number(match[2]) : 0;
      if (!match || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start) {
        rangeInput.setCustomValidity('请输入有效页码范围，例如 5-10；页码应为正整数且结束页不小于开始页。');
        rangeInput.reportValidity();
        throw new Error('页码范围无效，请使用 5-10 这样的格式。');
      }
      options.page_range = [start, end];
    }
    return options;
  }

  function renderSettings() {
    const settings = state.settingsDraft;
    if (!settings) return;
    $('settings-output').textContent = directoryName(settings.output_dir);
    $('settings-format').value = settings.format;
    $('settings-theme').value = settings.theme || 'system';
    $('settings-options').innerHTML = optionFields(settings.options, 'defaults');
  }

  function openTaskOptions() {
    $('task-options-fields').innerHTML = optionFields(state.task.options, 'task');
    $('options-error').hidden = true;
    $('options-dialog').showModal();
  }

  function confirmAction(title, message, label = '确认') {
    return new Promise(resolve => {
      state.confirmResolver?.(false);
      state.confirmResolver = resolve;
      $('confirm-title').textContent = title;
      $('confirm-message').textContent = message;
      $('confirm-submit').textContent = label;
      $('confirm-dialog').showModal();
    });
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
    $('merge-list').innerHTML = state.mergeFiles.map((file, index) => `<div class="merge-row"><span class="merge-order">${index + 1}</span><span class="merge-name">${escapeHTML(file.name)}</span><button type="button" class="icon-button" data-action="merge-up" data-index="${index}" aria-label="上移 ${escapeHTML(file.name)}" ${index === 0 ? 'disabled' : ''}>↑</button><button type="button" class="icon-button" data-action="merge-down" data-index="${index}" aria-label="下移 ${escapeHTML(file.name)}" ${index === state.mergeFiles.length - 1 ? 'disabled' : ''}>↓</button></div>`).join('');
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
      state.task = clone(state.settings);
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
    state.resultView = view;
    $('rendered-result').hidden = view !== 'rendered';
    $('markdown-result').hidden = view !== 'source';
    document.querySelectorAll('[data-result-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.resultView === view)));
  }

  async function openResult(id) {
    const request = ++state.resultRequest;
    ++state.previewRequest;
    state.resultId = id;
    state.result = null;
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
      $('result-state').className = `status ${Object.hasOwn(stateNames, item.state) ? item.state : 'completed'}`;
      $('result-state').textContent = stateNames[item.state] || '已完成';
      const hasContent = Boolean(result.markdown || result.html);
      $('export-result').disabled = !hasContent;
      $('copy-markdown').disabled = !result.markdown;
      $('reveal-result').disabled = !item.output_path;
      $('rendered-result').innerHTML = result.html || '<p class="quiet">没有可阅读的转换结果。可展开下方大纲与处理日志。</p>';
      $('markdown-result').textContent = result.markdown || '没有 Markdown 内容。';
      $('result-logs').textContent = result.logs || '没有处理日志。';
      renderSummary(result.summary);
      $('summary-details').open = found?.job.mode === 'summary';
      $('log-details').open = Boolean(item.error) || ['failed', 'partial', 'interrupted'].includes(item.state);
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
      if (sources.length) {
        const source = sources.find(candidate => candidate.exists !== false) || sources[0];
        $('source-select').value = source.id;
        await loadSource(source.id, 1);
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

  function updatePDFControls() {
    $('pdf-page-number').value = state.sourcePage;
    $('pdf-page-number').max = state.sourceTotal;
    $('pdf-total').textContent = `/ ${state.sourceTotal}`;
    $('pdf-prev').disabled = state.sourceLoading || state.sourcePage <= 1;
    $('pdf-next').disabled = state.sourceLoading || state.sourcePage >= state.sourceTotal;
    $('pdf-page-number').disabled = state.sourceLoading;
  }

  function applyZoom() {
    const image = $('source-preview').querySelector('img.source-image');
    if (!image) return;
    const zoom = $('pdf-zoom').value;
    image.style.width = zoom === 'fit' ? '100%' : `${(image.naturalWidth || 800) * Number(zoom) / 100}px`;
  }

  async function loadSource(id, page = 1) {
    const request = ++state.previewRequest;
    const resultId = state.resultId;
    const source = state.result?.sources?.find(candidate => candidate.id === id);
    state.sourceId = id;
    state.sourcePage = page;
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
      const preview = await api('preview_source', id, page);
      if (request !== state.previewRequest || resultId !== state.resultId) return;
      if (preview.kind === 'PDF') {
        if (!/^data:image\/(png|jpeg|webp);/i.test(preview.data_url || '')) throw new Error('原文预览图像格式无效。');
        state.sourcePage = Number(preview.page) || 1;
        state.sourceTotal = Number(preview.total) || 1;
        const image = document.createElement('img');
        image.className = 'source-image';
        image.alt = `${source?.name || 'PDF'}，第 ${state.sourcePage} 页`;
        image.addEventListener('load', applyZoom, { once: true });
        image.src = preview.data_url;
        $('source-preview').replaceChildren(image);
        $('pdf-controls').hidden = false;
      } else if (preview.kind === 'DOCX') {
        const content = document.createElement('div');
        content.className = 'docx-preview document-body';
        content.innerHTML = preview.html || '<p class="quiet">文档没有可预览的内容。</p>';
        $('source-preview').replaceChildren(content);
        $('pdf-controls').hidden = true;
      } else throw new Error('当前原文格式不支持预览。');
      const backendNote = String(preview.note || '').trim();
      const docxNote = preview.kind === 'DOCX' && !/不还原\s*Word\s*分页/i.test(backendNote)
        ? '源文件内容预览 · 不还原 Word 分页、字体及复杂版式。'
        : '';
      const note = [docxNote, backendNote].filter(Boolean).join(' ');
      $('source-note').textContent = note;
      $('source-note').hidden = !note;
      $('source-preview').scrollTop = 0;
      $('source-preview').scrollLeft = 0;
    } catch (error) {
      if (request !== state.previewRequest || resultId !== state.resultId) return;
      $('source-preview').innerHTML = `<div class="empty-state"><h2>无法预览原文</h2><p>${escapeHTML(errorMessage(error))}</p><button class="button" data-action="retry-source">重试预览</button></div>`;
      $('pdf-controls').hidden = true;
    } finally {
      if (request === state.previewRequest) {
        state.sourceLoading = false;
        $('source-preview').setAttribute('aria-busy', 'false');
        updatePDFControls();
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
        if (await confirmAction('清空导入列表？', '只移除当前导入的文件，不会删除磁盘上的源文件。', '清空列表')) {
          state.queue = []; state.selected.clear(); renderQueue();
        } break;
      case 'remove-queue':
        state.queue = state.queue.filter(file => !state.selected.has(file.id)); state.selected.clear(); renderQueue(); break;
      case 'remove-one':
        state.queue = state.queue.filter(file => file.id !== id); state.selected.delete(id); renderQueue(); break;
      case 'choose-task-output':
      case 'choose-default-output':
        await perform('choose-output', async () => {
          const path = await api('choose_output');
          if (path === null || path === undefined) return;
          if (action === 'choose-task-output') { state.task.output_dir = path; renderQueue(); }
          else { state.settingsDraft.output_dir = path; $('settings-output').textContent = directoryName(path); }
        }, button); break;
      case 'reset-task-output': state.task.output_dir = ''; renderQueue(); break;
      case 'reset-default-output': state.settingsDraft.output_dir = ''; $('settings-output').textContent = directoryName(''); break;
      case 'start-convert': await startJob(state.queue); break;
      case 'summary-queue': await startJob(state.queue.filter(file => state.selected.has(file.id)), 'summary'); break;
      case 'merge-queue': openMerge(state.queue.filter(file => state.selected.has(file.id))); break;
      case 'summary-history': await startJob(selectedHistoryFiles(), 'summary'); break;
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
        if (await confirmAction('删除这条任务记录？', '仅删除历史记录。源文件和导出文件都会保留。', '删除记录')) {
          await perform(`delete-${id}`, async () => { await api('delete_job', id); await refreshJobs(); toast('任务记录已删除，磁盘文件仍然保留。'); });
        } break;
      }
      case 'open-result': await openResult(id); break;
      case 'refresh-result': if (state.resultId) await openResult(state.resultId); break;
      case 'toggle-summary':
        if (state.result) { $('summary-details').open = !$('summary-details').open; if ($('summary-details').open) $('summary-details').scrollIntoView({ block: 'nearest' }); } break;
      case 'pdf-prev': if (!state.sourceLoading && state.sourcePage > 1) await loadSource(state.sourceId, state.sourcePage - 1); break;
      case 'pdf-next': if (!state.sourceLoading && state.sourcePage < state.sourceTotal) await loadSource(state.sourceId, state.sourcePage + 1); break;
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
    if (button.hasAttribute('data-close-dialog')) { button.closest('dialog')?.close(); return; }
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
    } else if (target.id === 'task-format') state.task.format = target.value;
    else if (target.id === 'settings-format') state.settingsDraft.format = target.value;
    else if (target.id === 'source-select') loadSource(target.value, 1);
    else if (target.id === 'pdf-zoom') applyZoom();
    else if (target.name === 'business_mode') {
      const form = target.closest('form');
      for (const name of ['fix_list_number_positions', 'infer_empty_headers']) form.querySelector(`[name="${name}"]`).checked = target.checked;
    }
  });

  $('task-search').addEventListener('input', event => { state.query = event.target.value; renderJobs(); });
  document.addEventListener('input', event => { if (event.target.name === 'page_range') event.target.setCustomValidity(''); });
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
    const resolve = state.confirmResolver;
    state.confirmResolver = null;
    $('confirm-dialog').close();
    resolve?.(true);
  });
  $('confirm-dialog').addEventListener('close', () => {
    state.confirmResolver?.(false); state.confirmResolver = null;
  });
  $('export-form').addEventListener('submit', event => {
    event.preventDefault();
    perform('export', async () => {
      const path = await api('export_result', state.resultId, $('export-format').value);
      if (path) { $('export-dialog').close(); toast(`结果已导出到 ${path}`); }
    }, $('export-submit'));
  });
  $('pdf-page-form').addEventListener('submit', event => {
    event.preventDefault();
    const page = Number($('pdf-page-number').value);
    if (Number.isSafeInteger(page) && page >= 1 && page <= state.sourceTotal) loadSource(state.sourceId, page);
    else { toast(`页码应在 1 到 ${state.sourceTotal} 之间。`, true); updatePDFControls(); }
  });
  $('settings-form').addEventListener('submit', event => {
    event.preventDefault();
    perform('save-settings', async () => {
      const draft = clone(state.settingsDraft);
      draft.options = readOptions($('settings-options'), draft.options);
      draft.format = $('settings-format').value;
      draft.theme = $('settings-theme').value;
      const saved = await api('save_settings', draft);
      state.settings = clone(saved);
      state.settingsDraft = clone(saved);
      if (!state.queue.length) state.task = clone(saved);
      applyTheme(saved.theme);
      renderSettings();
      toast('默认设置已保存，将应用于之后建立的任务。');
    }, $('save-settings'));
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
    $('connection-message').textContent = '浏览器页面无法访问本地转换服务。请在项目目录运行下方命令。';
    $('launch-command').hidden = false;
    $('app').setAttribute('aria-busy', 'false');
  }, 1800);
})();
