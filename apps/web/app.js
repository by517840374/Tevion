/* Tevion 前端工作台 - 连接真实后端 API
 * 后端地址如有变化，只需修改 API_BASE。
 */
const defaultApiBase = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
  ? 'http://127.0.0.1:8010/api/v1'
  : window.location.protocol + '//' + window.location.hostname + ':8010/api/v1';
const API_BASE = window.TEVION_API_BASE || defaultApiBase;

const OIDC_CONFIG = window.TEVION_OIDC_CONFIG || null;
const TOKEN_KEY = 'tevion_token';
const PROJECT_KEY = 'tevion_project_id';
const OIDC_TRANSACTION_KEY = 'tevion_oidc_transaction';

/* ---------- 小工具 ---------- */
const $ = id => document.getElementById(id);
let busy = false;
let currentTask = null;   // { task_id, request, mode, aspect_ratio, output_count }
let chosenId = null;      // 当前高亮的候选图 id
let lastFeedbackIntent = null;
let elapsedTimer = null;
let genStartedAt = 0;
let historyProjects = [];
let historySessions = [];
let memoryExpanded = false;
let selectedProjectId = sessionStorage.getItem(PROJECT_KEY) || '';
let uploadedParentVersionId = null;
let uploadedReferenceImages = [];
let referenceUploadInFlight = false;
let projectTasks = [];
let generationRounds = [];
let taskPage = 1;
let taskExpanded = false;
const TASK_PAGE_SIZE = 6;
const GENERATION_POLL_INTERVAL_MS = 3000;
const GENERATION_POLL_TIMEOUT_MS = 300000;

function toast(msg, type = 'info', ms = 5000) {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast toast-' + type;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, ms);
}

function setBusy(b) {
  busy = b;
  $('generate').disabled = b;
  const regen = document.querySelector('.regen-button');
  if (regen) regen.disabled = b;
}
function setGenerateLabel(text) {
  const button = $('generate');
  if (button) button.innerHTML = escapeHtml(text) + ' <span aria-hidden="true">→</span>';
}

async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (auth && token) headers['Authorization'] = 'Bearer ' + token;
  let res;
  try {
    res = await fetch(API_BASE + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (err) {
    const e = new Error('无法连接后端服务（' + API_BASE + '）。请确认后端 uvicorn 已在 8010 端口启动，并已开启跨域(CORS)支持。');
    e.network = true;
    throw e;
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
  }
  if (!res.ok) {
    if (res.status === 401) clearToken();
    const detail = (data && (data.detail || data.message)) || '';
    const msg = friendlyHttpError(res.status) + (detail ? '（' + String(detail).slice(0, 200) + '）' : '');
    const e = new Error(msg);
    e.status = res.status;
    e.detail = detail;
    throw e;
  }
  return data;
}

function resolveImageUrl(value) {
  const url = String(value || '');
  if (!url || /^(https?:|data:|blob:)/i.test(url)) return url;
  try { return new URL(url, API_BASE.replace(/\/$/, '') + '/').href; } catch { return url; }
}

function friendlyHttpError(status) {
  if (status === 401 || status === 403) return '登录已失效或无权限，请重新「演示登录」。';
  if (status === 404) return '接口不存在（HTTP 404）：后端该端点尚未实现或路径不符，请等待后端联调。';
  if (status >= 500) return '后端服务异常（HTTP ' + status + '）。';
  return '请求被拒绝（HTTP ' + status + '）。';
}

/* ---------- 登录态 ---------- */
function getToken() { return sessionStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { sessionStorage.setItem(TOKEN_KEY, t); }
function clearToken() { sessionStorage.removeItem(TOKEN_KEY); }
function getProjectId() { return selectedProjectId || sessionStorage.getItem(PROJECT_KEY) || ''; }
function setProjectId(id) { selectedProjectId = id || ''; if (selectedProjectId) sessionStorage.setItem(PROJECT_KEY, selectedProjectId); else sessionStorage.removeItem(PROJECT_KEY); }

/* ---------- 产品入口路由与账号认证 ---------- */
let authMode = 'login';
function routeName() {
  const value = window.location.hash.replace(/^#/, '').toLowerCase();
  return ['login', 'register', 'projects', 'new-project', 'provider-settings', 'workbench', 'admin'].includes(value) ? value : (getToken() ? 'projects' : 'landing');
}
function routeTo(name) {
  const route = ['landing', 'login', 'register', 'projects', 'new-project', 'provider-settings', 'workbench', 'admin'].includes(name) ? name : 'landing';
  if (window.location.hash !== '#' + route) window.location.hash = route === 'landing' ? '' : route;
  renderRoute(route);
}
function reloadPage() {
  const url = new URL(window.location.href);
  url.searchParams.set('_refresh', Date.now().toString());
  window.location.replace(url.href);
}
function renderRoute(route = routeName()) {
  document.body.dataset.route = route;
  $('landingView').hidden = route !== 'landing';
  $('authView').hidden = !['login', 'register'].includes(route);
  $('projectsView').hidden = route !== 'projects';
  $('newProjectView').hidden = route !== 'new-project';
  $('providerSettingsView').hidden = route !== 'provider-settings';
  $('workbenchView').hidden = route !== 'workbench';
  $('adminView').hidden = route !== 'admin';
  document.querySelector('.topbar-meta').textContent = route === 'workbench' ? '项目执行 / 实时后端联调模式' : ['projects', 'new-project'].includes(route) ? '项目管理 / 独立工作空间' : '从意图到视觉方向';
  if (['projects', 'new-project', 'provider-settings', 'workbench', 'admin'].includes(route) && !getToken()) return routeTo('login');
  if (route === 'admin') loadAdminPage();
  if (['login', 'register'].includes(route)) setupAuthForm(route);
  document.title = route === 'landing' ? 'Tevion - 从感觉到画面' : route === 'register' ? '注册 Tevion' : route === 'login' ? '登录 Tevion' : route === 'projects' ? 'Tevion - 项目管理' : route === 'new-project' ? 'Tevion - 新建项目' : route === 'provider-settings' ? 'Tevion - 图片接口设置' : route === 'admin' ? 'Tevion - 后台管理' : 'Tevion - 项目执行';
}
function setupAuthForm(route) {
  authMode = route;
  const register = route === 'register';
  $('authTitle').textContent = register ? '创建你的 Tevion' : '欢迎回来';
  $('authIntro').textContent = register ? '建立账号，保存你的视觉探索与偏好。' : '登录后继续你的视觉探索。';
  $('authSubmit').textContent = register ? '创建账号' : '登录';
  $('authSwitchText').textContent = register ? '已经有账号？' : '还没有账号？';
  $('authSwitch').textContent = register ? '立即登录' : '创建账号';
  $('authSwitch').href = register ? '#login' : '#register';
  $('authConfirmLabel').hidden = !register; $('authConfirm').hidden = !register; $('authConfirm').required = register;
  $('authPassword').autocomplete = register ? 'new-password' : 'current-password';
  $('authMessage').textContent = '';
  ['authEmailError','authPasswordError','authConfirmError'].forEach(id => $(id).textContent = '');
}
function validateAuth(email, password, confirm) {
  const errors = {};
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = '请输入有效的邮箱地址。';
  if (!password || password.length < 8) errors.password = '密码至少需要 8 个字符。';
  if (authMode === 'register' && password !== confirm) errors.confirm = '两次输入的密码不一致。';
  return errors;
}
async function submitAuth(event) {
  event.preventDefault();
  const email = $('authEmail').value.trim().toLowerCase(), password = $('authPassword').value, confirm = $('authConfirm').value;
  const errors = validateAuth(email, password, confirm);
  $('authEmailError').textContent = errors.email || ''; $('authPasswordError').textContent = errors.password || ''; $('authConfirmError').textContent = errors.confirm || '';
  if (Object.keys(errors).length) return;
  const submit = $('authSubmit'); submit.disabled = true; $('authMessage').textContent = authMode === 'register' ? '正在创建账号…' : '正在登录…';
  try {
    const data = await api('/auth/' + authMode, { method: 'POST', body: { email, password }, auth: false });
    if (!data?.access_token) throw new Error('认证接口未返回有效凭证。');
    setToken(data.access_token);
    $('authMessage').textContent = authMode === 'register' ? '账号创建成功，正在进入工作台…' : '登录成功，正在进入工作台…';
    $('authMessage').className = 'auth-message success';
    window.setTimeout(() => routeTo('projects'), 120);
  } catch (err) {
    $('authMessage').className = 'auth-message';
    $('authMessage').textContent = authMode === 'register' && err.status === 409 ? '该邮箱账号已存在，请直接登录。' : authMode === 'login' ? '登录失败，请检查邮箱和密码。' : '注册失败，请检查输入后重试。';
  } finally { submit.disabled = false; }
}

function listPayload(data) {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.items)) return data.items;
  if (data && Array.isArray(data.projects)) return data.projects;
  if (data && Array.isArray(data.sessions)) return data.sessions;
  if (data && Array.isArray(data.versions)) return data.versions;
  return [];
}

function historyLabel(item, fallback) {
  return item.name || item.title || item.raw_request || item.request || item.id || fallback;
}

function renderProjectOptions(items) {
  const select = $('projectSelect');
  if (!select) return;
  select.innerHTML = '';
  if (!items.length) {
    select.appendChild(new Option('暂无项目，请先新建', ''));
    select.disabled = true;
    setProjectId('');
    if ($('projectStatus')) $('projectStatus').textContent = '请新建';
    return;
  }
  const selected = items.some(item => item.id === getProjectId()) ? getProjectId() : items[0].id;
  items.forEach(item => select.appendChild(new Option(historyLabel(item, '未命名项目'), item.id)));
  select.value = selected;
  select.disabled = false;
  setProjectId(selected);
  if ($('projectStatus')) $('projectStatus').textContent = items.length + ' 个可用项目';
}

function renderProjectManagement(items) {
  const target = $('projectManagementList');
  const status = $('projectManagementStatus');
  if (!target) return;
  if (!items.length) {
    if (status) status.textContent = '还没有项目，先创建一个独立工作空间。';
    target.innerHTML = '<div class="empty-management panel"><div class="empty-orbit"></div><h2>暂无项目</h2><p>创建项目后，再进入项目执行页上传参考图、创建任务和查看结果。</p><button class="primary-button" data-new-project type="button">新建第一个项目 →</button></div>';
    return;
  }
  if (status) status.textContent = '共 ' + items.length + ' 个项目。选择一个项目进入执行页。';
  target.innerHTML = items.map(item => '<article class="project-management-card panel"><div><div class="eyebrow">PROJECT</div><h2>' + escapeHtml(historyLabel(item, '未命名项目')) + '</h2><p>' + escapeHtml(item.description || '暂无项目描述') + '</p></div><div class="project-card-actions"><span class="muted">项目 ID：' + escapeHtml(item.id || '未提供') + '</span><button class="primary-button" data-open-project="' + escapeHtml(item.id || '') + '" type="button">进入执行 →</button></div></article>').join('');
}

async function loadProjects() {
  if (!getToken()) return;
  try {
    const data = await api('/projects');
    historyProjects = listPayload(data);
    renderProjectOptions(historyProjects);
    renderProjectManagement(historyProjects);
    renderHistoryOptions($('historyProject'), historyProjects, '暂无项目');
    if (historyProjects.length) {
      $('historyProject').value = getProjectId();
      await loadHistorySessions(getProjectId());
      await loadProjectTasks(getProjectId());
      await loadMetrics();
    }
  } catch (err) {
    renderProjectOptions([]);
    if ($('projectStatus')) $('projectStatus').textContent = '加载失败';
    renderHistoryMessage('项目读取失败：' + err.message + ' 可重试。', true);
  }
}

function taskStatusLabel(status) {
  return ({ created: '已创建', generating: '生成中', completed: '已完成', failed: '失败', unknown: '状态未知', needs_user_review: '需要确认' })[status] || status || '未知状态';
}
function taskDate(value) {
  if (!value) return '时间未提供';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
}
function taskImageMarkup(item) {
  return (Array.isArray(item.images) ? item.images : []).map((image, index) => {
    const value = typeof image === 'string' ? { url: image } : (image || {});
    const imageUrl = resolveImageUrl(value.url);
    return imageUrl ? '<a class="task-image-preview" href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noopener" data-lightbox="' + escapeHtml(imageUrl) + '" aria-label="打开任务结果 ' + (index + 1) + ' 大图预览"><img loading="lazy" alt="任务结果 ' + (index + 1) + '" src="' + escapeHtml(imageUrl) + '"></a>' : '';
  }).join('');
}
function taskDataset(item) {
  return escapeHtml(JSON.stringify({ task_id: item.task_id, run_id: item.run_id, project_id: item.project_id, session_id: item.session_id, request: item.request, mode: item.mode, output_count: item.requested_output_count, images: item.images || [] }));
}
function renderTaskList(items) {
  const target = $('taskList');
  if (!target) return;
  const pagination = $('taskPagination');
  if (!items.length) {
    target.innerHTML = '<p class="muted">当前项目暂无任务。</p>';
    if (pagination) pagination.hidden = true;
    return;
  }
  const pageCount = Math.max(1, Math.ceil(items.length / TASK_PAGE_SIZE));
  taskPage = Math.min(Math.max(taskPage, 1), pageCount);
  const visibleItems = taskExpanded
    ? items.slice((taskPage - 1) * TASK_PAGE_SIZE, taskPage * TASK_PAGE_SIZE)
    : items.slice(0, 1);
  target.innerHTML = visibleItems.map(item => {
    const status = String(item.status || 'unknown').toLowerCase();
    const images = Array.isArray(item.images) ? item.images : [];
    const count = item.actual_output_count ?? images.length;
    const requested = item.requested_output_count ?? '-';
    const data = taskDataset(item);
    let actions = '';
    if (['created', 'generating', 'unknown'].includes(status)) actions += '<button type="button" class="small-button" data-task-continue="' + data + '">继续查询</button>';
    if (status === 'failed' && item.retryable !== false) actions += '<button type="button" class="small-button" data-task-retry="' + data + '">重试生成</button>';
    if (status === 'completed' && images.length) actions += '<button type="button" class="small-button" data-task-view="' + data + '">查看结果</button><button type="button" class="secondary-button" data-task-refine="' + data + '">进入 Refine</button>';
    return '<article class="task-card task-status-' + escapeHtml(status) + '" data-task-id="' + escapeHtml(item.task_id || '') + '"><div class="task-card-heading"><div><span class="task-status-badge">' + escapeHtml(taskStatusLabel(status)) + '</span><h3>' + escapeHtml(String(item.request || '未提供请求')) + '</h3></div><time>' + escapeHtml(taskDate(item.created_at)) + '</time></div><div class="task-card-meta"><span>' + escapeHtml(item.mode === 'refine' ? 'Refine' : 'Explore') + '</span><span>结果 ' + escapeHtml(String(count)) + ' / ' + escapeHtml(String(requested)) + '</span><span>run_id: ' + escapeHtml(item.run_id || '未提供') + '</span></div>' + (taskImageMarkup(item) ? '<div class="task-card-images">' + taskImageMarkup(item) + '</div>' : '') + (item.error_code ? '<p class="task-error">' + escapeHtml(String(item.error_code)) + '</p>' : '') + ((item.parent_run_id || item.parent_image_id) ? '<p class="task-lineage">parent：' + escapeHtml(item.parent_run_id || item.parent_image_id) + '</p>' : '') + (actions ? '<div class="task-actions">' + actions + '</div>' : '') + '</article>';
  }).join('');
  if (pagination) {
    pagination.hidden = items.length <= 1;
    pagination.innerHTML = taskExpanded
      ? '<button type="button" class="text-button task-more-button" data-task-more="collapse">收起任务</button><span>第 ' + taskPage + ' / ' + pageCount + ' 页 · 共 ' + items.length + ' 条</span><button type="button" class="small-button" data-task-page="prev"' + (taskPage <= 1 ? ' disabled' : '') + '>上一页</button><button type="button" class="small-button" data-task-page="next"' + (taskPage >= pageCount ? ' disabled' : '') + '>下一页</button>'
      : '<button type="button" class="text-button task-more-button" data-task-more="expand">查看更多任务（共 ' + items.length + ' 条） →</button>';
  }
  bindLightboxLinks(target);
}
function renderTaskCenterMessage(message, error = false) {
  const status = $('taskCenterStatus');
  const retry = $('taskCenterRetry');
  if (status) { status.textContent = message; status.className = 'muted intro' + (error ? ' history-error' : ''); }
  if (retry) retry.hidden = !error;
}
async function loadProjectTasks(projectId = getProjectId()) {
  const center = $('taskCenter');
  if (!center || !projectId || !getToken()) return renderTaskCenterMessage('选择项目后加载任务历史。');
  center.setAttribute('aria-busy', 'true');
  renderTaskCenterMessage('正在加载任务历史…');
  try {
    projectTasks = listPayload(await api('/projects/' + encodeURIComponent(projectId) + '/tasks'));
    taskPage = 1;
    taskExpanded = false;
    renderTaskList(projectTasks);
    renderTaskCenterMessage(projectTasks.length ? '已加载 ' + projectTasks.length + ' 个任务。' : '当前项目暂无任务。');
  } catch (err) {
    projectTasks = [];
    renderTaskList([]);
    renderTaskCenterMessage('任务列表读取失败：' + err.message + ' 可重试。', true);
  } finally { center.setAttribute('aria-busy', 'false'); }
}
function parseTaskData(value) { try { return JSON.parse(value); } catch { return null; } }
function continueTaskFromCenter(task) { if (task?.task_id) { currentTask = { ...task, run_id: task.run_id }; resumeTaskQuery(); } }
function retryTaskFromCenter(task) { if (task?.task_id) { currentTask = task; handleGenerate({ reuse: true }); } }
function viewTaskFromCenter(task, refine = false) {
  if (!task?.task_id) return;
  currentTask = task; showEcho(task.request || '任务中心历史任务'); renderResults(task.images || [], task);
  if (refine) { chosenId = task.images?.[0]?.id || task.images?.[0]; document.querySelector('.mode[data-mode="refine"]')?.click(); renderSelectedParent(); renderRefineContext(); }
}
function handleProjectChange(projectId) {
  setProjectId(projectId); if ($('historyProject')) $('historyProject').value = projectId;
  loadHistorySessions(projectId); loadProjectTasks(projectId); loadMetrics();
}

async function createProject(event) {
  event.preventDefault();
  const name = $('projectName').value.trim();
  const message = $('projectFormMessage');
  if (!name) { message.textContent = '请输入项目名称。'; $('projectName').focus(); return; }
  const button = $('createProject'); button.disabled = true; message.textContent = '正在创建项目…';
  try {
    const project = await api('/projects', { method: 'POST', body: { name, description: $('projectDescription').value.trim() || null } });
    $('projectName').value = ''; $('projectDescription').value = '';
    await loadProjects();
    setProjectId(project.id); $('projectSelect').value = project.id; $('historyProject').value = project.id;
    message.textContent = '项目已创建并设为当前项目。'; toast('项目创建成功。', 'success');
    routeTo('workbench');
  } catch (err) { message.textContent = '创建失败：' + err.message; }
  finally { button.disabled = false; }
}

async function loadProviderSettings() {
  const message = $('providerSettingsMessage');
  try {
    const data = await api('/settings/image-provider');
    $('providerBaseUrl').value = data?.base_url || '';
    $('providerModel').value = data?.model || 'gpt-image-2';
    $('providerApiKey').value = '';
    if (message) message.textContent = data?.configured ? '已配置：' + data.base_url + '（Key 已隐藏）' : '尚未配置图片接口。';
  } catch (err) { if (message) message.textContent = '读取设置失败：' + err.message; }
}

async function saveProviderSettings(event) {
  event.preventDefault();
  const message = $('providerSettingsMessage');
  const apiKey = $('providerApiKey').value.trim();
  if (!apiKey) { if (message) message.textContent = '请输入 API Key（不会保存到浏览器）。'; return; }
  if (message) message.textContent = '正在保存…';
  try {
    const data = await api('/settings/image-provider', { method: 'PUT', body: { base_url: $('providerBaseUrl').value.trim(), api_key: apiKey, model: $('providerModel').value.trim() || 'gpt-image-2' } });
    $('providerApiKey').value = '';
    if (message) message.textContent = '已保存并启用：' + data.base_url + '（Key 已隐藏）';
    toast('图片接口配置已生效。', 'success');
  } catch (err) { if (message) message.textContent = '保存失败：' + err.message; }
}

async function clearProviderSettings() {
  if (!window.confirm('确认清除后端保存的图片接口配置？')) return;
  try { await api('/settings/image-provider', { method: 'DELETE' }); $('providerApiKey').value = ''; $('providerBaseUrl').value = ''; if ($('providerSettingsMessage')) $('providerSettingsMessage').textContent = '配置已清除。'; toast('图片接口配置已清除。', 'success'); }
  catch (err) { if ($('providerSettingsMessage')) $('providerSettingsMessage').textContent = '清除失败：' + err.message; }
}

function renderHistoryMessage(message, error = false) {
  const status = $('historyStatus');
  if (status) {
    status.textContent = message;
    status.className = 'muted intro' + (error ? ' history-error' : '');
    if (!error) document.getElementById('historyRetry')?.remove();
  }
}

function renderHistoryRetry() {
  const status = $('historyStatus');
  if (!status || $('historyRetry')) return;
  const retry = document.createElement('button');
  retry.id = 'historyRetry';
  retry.className = 'text-button history-retry';
  retry.type = 'button';
  retry.textContent = '重新加载历史 →';
  retry.addEventListener('click', loadProjectHistory);
  status.insertAdjacentElement('afterend', retry);
}

function renderHistoryOptions(select, items, emptyText) {
  if (!select) return;
  select.innerHTML = '';
  if (!items.length) {
    select.appendChild(new Option(emptyText, ''));
    select.disabled = true;
    return;
  }
  items.forEach((item, index) => select.appendChild(new Option(historyLabel(item, '记录 ' + (index + 1)), item.id)));
  select.disabled = false;
}

function renderHistoryVersions(versions) {
  const target = $('historyVersions');
  if (!target) return;
  if (!versions.length) {
    target.innerHTML = '<p class="muted">当前会话暂无历史版本。</p>';
    return;
  }
  target.innerHTML = versions.map((version, index) => {
    const parent = version.parent_image_id ? '<span class="history-parent">parent_image_id: ' + escapeHtml(version.parent_image_id) + '</span>' : '<span class="history-parent">无 parent_image_id（根版本）</span>';
    const image = resolveImageUrl(version.url || version.asset_uri);
    const preview = image ? '<button type="button" class="history-image-preview" data-lightbox="' + escapeHtml(image) + '" aria-label="打开历史版本 ' + (index + 1) + ' 大图预览"><img loading="lazy" alt="历史版本 ' + (index + 1) + '" src="' + escapeHtml(image) + '"></button>' : '';
    return '<article class="history-version"><div class="history-thumb">' + preview + '</div><div><strong>' + escapeHtml(version.id || '版本 ' + (index + 1)) + '</strong><small>run_id: ' + escapeHtml(version.run_id || '未提供') + '</small>' + parent + '</div></article>';
  }).join('');
  bindLightboxLinks(target);
}

async function loadHistoryVersions(sessionId) {
  if (!sessionId) return renderHistoryVersions([]);
  renderHistoryMessage('正在加载会话版本…');
  try {
    const data = await api('/sessions/' + encodeURIComponent(sessionId) + '/versions');
    const versions = listPayload(data);
    renderHistoryVersions(versions);
    renderHistoryMessage('已加载 ' + versions.length + ' 个历史版本。');
  } catch (err) {
    renderHistoryVersions([]);
    renderHistoryMessage('历史版本读取失败：' + err.message + ' 可重新选择会话重试。', true);
    renderHistoryRetry();
  }
}

async function loadHistorySessions(projectId) {
  const sessionSelect = $('historySession');
  if (!sessionSelect || !projectId) return;
  sessionSelect.disabled = true;
  renderHistoryVersions([]);
  renderHistoryMessage('正在加载项目会话…');
  try {
    const data = await api('/projects/' + encodeURIComponent(projectId) + '/sessions');
    historySessions = listPayload(data);
    renderHistoryOptions(sessionSelect, historySessions, '暂无会话');
    renderHistoryMessage(historySessions.length ? '已加载项目会话，请选择查看版本。' : '当前项目暂无会话。');
    if (historySessions.length) {
      await loadHistoryVersions(historySessions[0].id);
      await refreshVisualMemory(historySessions[0].id);
    } else {
      await refreshVisualMemory(null);
    }
  } catch (err) {
    historySessions = [];
    renderHistoryOptions(sessionSelect, [], '暂无会话');
    renderHistoryMessage('会话读取失败：' + err.message + ' 可重新选择项目重试。', true);
    renderHistoryRetry();
  }
}

async function loadProjectHistory() {
  const projectSelect = $('historyProject');
  if (!projectSelect || !getToken()) return;
  projectSelect.disabled = true;
  renderHistoryMessage('正在加载项目历史…');
  try {
    const data = await api('/projects');
    historyProjects = listPayload(data);
    renderHistoryOptions(projectSelect, historyProjects, '暂无项目');
    if (!historyProjects.length) {
      renderHistoryMessage('当前账号暂无项目。创建项目后可在此查看历史。');
      renderHistoryVersions([]);
      return;
    }
    await loadHistorySessions(historyProjects[0].id);
  } catch (err) {
    historyProjects = [];
    renderHistoryOptions(projectSelect, [], '暂无项目');
    renderHistoryVersions([]);
    renderHistoryMessage('项目历史读取失败：' + err.message + ' 后端接口就绪后可重试。', true);
    renderHistoryRetry();
  }
}

function formatMetricPercent(value) { return (Number(value || 0) * 100).toFixed(1) + '%'; }
function formatMetricNumber(value) { return Number(value || 0).toFixed(1); }

function updateCreditEstimate() {
  const target = $('creditEstimate');
  if (!target) return;
  const count = Number($('count')?.value || 1);
  const refine = document.querySelector('.mode.active')?.dataset.mode === 'refine';
  target.textContent = '本次预计消耗 ' + (count * (refine ? 15 : 10)) + ' 点，生成失败会自动释放。';
}

async function loadCredits() {
  const target = $('creditBalance');
  const accountPoints = $('authPoints');
  if (!getToken()) { if (target) target.hidden = true; if (accountPoints) accountPoints.textContent = '余额 -- 点'; return; }
  try {
    const data = await api('/credits');
    const label = '余额 ' + Number(data?.balance_points || 0) + ' 点';
    if (target) { target.textContent = label; target.hidden = false; }
    if (accountPoints) accountPoints.textContent = label;
  } catch (_) { if (target) target.hidden = true; if (accountPoints) accountPoints.textContent = '余额暂不可用'; }
}

async function loadAccountSummary() {
  if (!getToken()) return;
  try {
    const user = await api('/auth/me');
    const name = user.display_name || user.email || user.provider_subject || 'Tevion 用户';
    $('authName').textContent = name;
    $('authAvatar').textContent = name.trim().charAt(0).toUpperCase() || 'T';
  } catch (_) {
    $('authName').textContent = 'Tevion 用户';
    $('authAvatar').textContent = 'T';
  }
}

async function loadAdminAccess() {
  const button = $('adminBtn');
  if (!button || !getToken()) { if (button) button.hidden = true; return false; }
  try {
    const data = await api('/admin/access');
    button.hidden = !data?.allowed;
    return !!data?.allowed;
  } catch (_) { button.hidden = true; return false; }
}

async function loadAdminPage() {
  const status = $('adminStatus'), form = $('adminCreditForm'), list = $('adminUserList');
  if (!status || !form) return;
  status.textContent = '正在检查管理员权限…'; form.hidden = true;
  try {
    const allowed = await loadAdminAccess();
    if (!allowed) { status.textContent = '当前账号没有管理员权限。'; return; }
    status.textContent = '权限已确认。所有调整都会写入点数账本。';
    form.hidden = false;
    const users = await api('/admin/users');
    if (list) list.innerHTML = users.map(user => '<tr><td><strong>' + escapeHtml(user.email || user.provider_subject) + '</strong><small>' + escapeHtml(user.id) + '</small></td><td><span class="admin-balance">' + Number(user.balance_points || 0) + ' 点</span></td><td><span class="admin-role ' + (user.is_super_admin ? 'active' : '') + '">' + (user.is_super_admin ? 'super admin' : '普通用户') + '</span></td><td><button type="button" class="small-button" data-admin-select="' + escapeHtml(user.id) + '" data-admin-user="' + escapeHtml(user.id) + '">分配点数</button><button type="button" class="text-button" data-admin-password="' + escapeHtml(user.id) + '" data-admin-name="' + escapeHtml(user.email || user.provider_subject) + '">改密码</button><button type="button" class="text-button" data-admin-ledger="' + escapeHtml(user.id) + '" data-admin-name="' + escapeHtml(user.email || user.provider_subject) + '">查看流水</button><button type="button" class="text-button" data-admin-user="' + escapeHtml(user.id) + '" data-admin-role="' + (user.is_super_admin ? 'false' : 'true') + '">' + (user.is_super_admin ? '收回权限' : '设为管理员') + '</button></td></tr>').join('') || '<tr><td colspan="4" class="muted">暂无用户。</td></tr>';
  } catch (_) { status.textContent = '权限检查失败，请稍后重试。'; }
}

function renderMetrics(data) {
  const summary = $('metricsSummary'), status = $('metricsStatus'), grid = $('metricsGrid');
  if (!summary || !status || !grid) return;
  summary.setAttribute('aria-busy', 'false');
  const latency = data.latency_ms || { count: 0, average: 0 };
  const cost = data.cost || { count: 0, average: 0, total: 0 };
  const hasData = Number(latency.count || 0) > 0 || Number(cost.count || 0) > 0 || Number(data.average_generation_rounds || 0) > 0 ||
    [data.generation_completion_rate, data.candidate_selection_rate, data.feedback_completion_rate, data.explore_to_refine_rate].some(value => Number(value || 0) > 0);
  const scopeLabel = data.scope === 'project' ? '当前项目的真实使用摘要。' : '当前账号的真实使用摘要。';
  status.textContent = hasData ? scopeLabel : (data.scope === 'project' ? '当前项目暂无可用产品指标，完成一次生成后这里会显示摘要。' : '暂无可用产品指标，完成一次生成后这里会显示摘要。');
  grid.innerHTML = [
    ['生成完成率', formatMetricPercent(data.generation_completion_rate)], ['候选选择率', formatMetricPercent(data.candidate_selection_rate)],
    ['反馈完成率', formatMetricPercent(data.feedback_completion_rate)], ['Explore → Refine', formatMetricPercent(data.explore_to_refine_rate)],
    ['平均生成轮数', formatMetricNumber(data.average_generation_rounds)], ['平均延迟', Math.round(Number(latency.average || 0)) + ' ms'],
    ['平均成本', '$' + Number(cost.average || 0).toFixed(4)], ['累计成本', '$' + Number(cost.total || 0).toFixed(4)],
  ].map(([label, value]) => '<div class="metric-card"><span>' + label + '</span><strong>' + value + '</strong></div>').join('');
}

function renderMetricsMessage(message, error = false) {
  const summary = $('metricsSummary'), status = $('metricsStatus'), grid = $('metricsGrid');
  if (!summary || !status || !grid) return;
  summary.setAttribute('aria-busy', 'false'); status.textContent = message;
  status.className = 'muted intro' + (error ? ' metrics-error' : ''); grid.innerHTML = '';
}

async function loadMetrics() {
  if (!$('metricsSummary')) return;
  if (!getToken()) return renderMetricsMessage('登录后加载当前账号指标。');
  const summary = $('metricsSummary'); summary.setAttribute('aria-busy', 'true');
  $('metricsStatus').textContent = '正在加载产品指标…'; $('metricsStatus').className = 'muted intro';
  const projectId = getProjectId();
  const endpoint = projectId ? '/metrics?project_id=' + encodeURIComponent(projectId) : '/metrics';
  try { renderMetrics((await api(endpoint)) || {}); }
  catch (err) { renderMetricsMessage(err.status === 401 ? '登录已失效，请重新「演示登录」后重试。' : '产品指标读取失败：' + err.message + ' 可重新登录后重试。', true); }
}

function randomString(bytes = 32) {
  const values = new Uint8Array(bytes);
  crypto.getRandomValues(values);
  return btoa(String.fromCharCode(...values)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function pkceChallenge(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function startOidcLogin() {
  if (!OIDC_CONFIG || !OIDC_CONFIG.authorization_endpoint || !OIDC_CONFIG.client_id) return false;
  const state = randomString();
  const codeVerifier = randomString(48);
  const codeChallenge = await pkceChallenge(codeVerifier);
  sessionStorage.setItem(OIDC_TRANSACTION_KEY, JSON.stringify({ state, codeVerifier }));
  const params = new URLSearchParams({
    response_type: 'code', client_id: OIDC_CONFIG.client_id,
    redirect_uri: OIDC_CONFIG.redirect_uri || window.location.href.split('?')[0],
    scope: OIDC_CONFIG.scope || 'openid profile email', state,
    code_challenge: codeChallenge, code_challenge_method: 'S256',
  });
  window.location.assign(OIDC_CONFIG.authorization_endpoint + '?' + params);
  return true;
}

function sanitizeOidcCallbackUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete('code');
  url.searchParams.delete('state');
  url.searchParams.delete('error');
  url.searchParams.delete('error_description');
  url.searchParams.delete('error_uri');
  window.history.replaceState({}, document.title, url.pathname + (url.search ? '?' + url.searchParams : '') + url.hash);
}

async function handleOidcCallback() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const callbackError = params.get('error');
  if (!code && !callbackError) return false;

  // Remove credentials and authorization response parameters before returning or throwing.
  // The transaction remains available until a token exchange has completed successfully.
  try {
    if (callbackError) throw new Error('OIDC 登录被取消或拒绝，请重新点击登录。');

    let transaction;
    try {
      transaction = JSON.parse(sessionStorage.getItem(OIDC_TRANSACTION_KEY) || 'null');
    } catch {
      transaction = null;
    }
    if (!transaction || typeof transaction.state !== 'string' || typeof transaction.codeVerifier !== 'string' ||
        params.get('state') !== transaction.state) {
      throw new Error('OIDC state 校验失败，请重新点击登录。');
    }
    if (!OIDC_CONFIG || !OIDC_CONFIG.token_endpoint || !OIDC_CONFIG.client_id) {
      throw new Error('OIDC token endpoint 未配置，请重新点击登录。');
    }
    const body = new URLSearchParams({ grant_type: 'authorization_code', code,
      redirect_uri: OIDC_CONFIG.redirect_uri || window.location.href.split('?')[0],
      client_id: OIDC_CONFIG.client_id, code_verifier: transaction.codeVerifier });
    let response;
    try {
      response = await fetch(OIDC_CONFIG.token_endpoint, { method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body });
    } catch {
      throw new Error('OIDC token endpoint 无法连接，请重新点击登录。');
    }
    if (!response.ok) throw new Error('OIDC token exchange 失败，请重新点击登录。');
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error('OIDC token exchange 返回无效响应，请重新点击登录。');
    }
    if (!data.access_token || typeof data.access_token !== 'string') {
      throw new Error('OIDC token exchange 未返回 access_token，请重新点击登录。');
    }
    setToken(data.access_token);
    sessionStorage.removeItem(OIDC_TRANSACTION_KEY);
    return true;
  } finally {
    sanitizeOidcCallbackUrl();
  }
}
function refreshLoginUI() {
  const has = !!getToken();
  $('loginBtn').hidden = has;
  $('authChip').hidden = !has;
  $('loginHint').textContent = has ? '已登录：可直接生成，每次生成会调用真实后端。' : '未登录：生成前请先完成「演示登录」。';
  $('loginHint').className = has ? 'privacy-note on' : 'privacy-note';
  // 空状态里的登录引导
  const cta = $('loginCta');
  const results = $('results');
  if (cta) cta.hidden = has || results.classList.contains('results') || results.querySelector('.error-box');
  loadMetrics();
  loadCredits();
  loadAccountSummary();
  loadAdminAccess();
  if (has) loadProjects();
}

async function handleLogin() {
  if (busy) return;
  if (await startOidcLogin()) return;
  const btn = $('loginBtn');
  btn.disabled = true;
  btn.textContent = '登录中…';
  try {
    const data = await api('/auth/dev-token', { method: 'POST', body: { sub: 'demo' }, auth: false });
    if (!data || !data.access_token) throw new Error('登录接口未返回 access_token。');
    setToken(data.access_token);
    toast('演示登录成功，可以开始生成了。', 'success');
    await loadProjectHistory();
    routeTo('projects');
  } catch (err) {
    toast('登录失败：' + err.message, 'error', 8000);
  } finally {
    btn.disabled = false;
    btn.textContent = '演示登录';
    refreshLoginUI();
  }
}

function handleLogout() {
  clearToken();
  currentTask = null;
  chosenId = null;
  stopElapsed();
  resetResults('已退出登录。重新演示登录后即可继续生成。');
  setAgentPill('已准备', '');
  setCheckpoint('填写左侧需求后点击「生成视觉方案」，Agent 会创建任务并真实生成候选图片。');
  hideEcho();
  setBusy(false);
  refreshLoginUI();
  renderHistoryMessage('登录后加载项目、会话与版本。');
  renderHistoryOptions($('historyProject'), [], '暂无项目');
  renderHistoryOptions($('historySession'), [], '暂无会话');
  renderHistoryVersions([]);
  toast('已退出演示登录。', 'info');
  routeTo('landing');
}

/* ---------- 中间列状态 ---------- */
function setAgentPill(text, cls) {
  const pill = $('agentState');
  pill.className = 'live-pill' + (cls ? ' ' + cls : '');
  pill.innerHTML = '<span class="status-dot"></span> ' + text;
}
function setCheckpoint(text) {
  $('checkpointText').textContent = text;
}
function showEcho(requestText) {
  const el = $('requestEcho');
  el.hidden = false;
  el.innerHTML = '<span class="echo-label">本次需求 · REQUEST</span>' + escapeHtml(requestText);
}
function hideEcho() { $('requestEcho').hidden = true; }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderRefineContext() {
  const context = $('refineContext');
  const status = $('refineParentStatus');
  const uploadNote = $('refineContextNote');
  if (!context || !status) return;
  const refine = document.querySelector('.mode.active')?.dataset.mode === 'refine';
  context.hidden = !refine;
  if (!refine) return;
  if (uploadNote) uploadNote.textContent = '上传入口始终可用；上传成功后可作为 Refine parent 使用。';
  status.innerHTML = chosenId
    ? '<strong>selected parent</strong>：' + escapeHtml(chosenId) + '（下一次生成将携带 parent_version_id）'
    : '<strong>尚未选择 selected parent</strong>：请先在 Explore 结果区选择一张候选图，才能进行图生图精修。';
}

function setRefineUploadStatus(message, error = false) {
  const status = $('refineUploadStatus');
  if (!status) return;
  status.textContent = message;
  status.className = 'field-hint' + (error ? ' upload-error' : '');
}

function renderReferencePreview(images = []) {
  const target = $('referencePreview');
  if (!target) return;
  target.hidden = !images.length;
  target.innerHTML = images.map((item, index) => {
    const url = resolveImageUrl(item.url || item.previewUrl);
    const alt = item.name || ('参考图 ' + (index + 1));
    const selected = item.parent_version_id && item.parent_version_id === uploadedParentVersionId;
    return '<article class="reference-card' + (selected ? ' selected' : '') + '">' +
      '<a class="reference-preview-button" href="' + escapeHtml(url) + '" target="_blank" rel="noopener" data-lightbox="' + escapeHtml(url) + '" aria-label="打开' + escapeHtml(alt) + '大图预览"><img src="' + escapeHtml(url) + '" alt="' + escapeHtml(alt) + '"><span>点击查看大图</span></a>' +
      '<div class="reference-card-footer"><button type="button" class="text-button reference-zoom-button" data-lightbox="' + escapeHtml(url) + '">放大预览</button><div class="reference-card-actions"><button type="button" class="small-button reference-parent-button" data-reference-parent="' + escapeHtml(item.parent_version_id || '') + '"' + (item.parent_version_id ? '' : ' disabled') + '>' + (selected ? '当前精修图' : '设为精修图') + '</button><button type="button" class="text-button reference-delete-button" data-reference-delete="' + String(index) + '">删除</button></div></div>' +
      '</article>';
  }).join('');
  bindLightboxLinks(target);
}

async function uploadReferenceImage(projectId, file) {
  const form = new FormData();
  form.append('file', file, file.name);
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = 'Bearer ' + token;
  let response;
  try {
    response = await fetch(API_BASE + '/projects/' + encodeURIComponent(projectId) + '/reference-images', {
      method: 'POST', headers, body: form
    });
  } catch (err) {
    const error = new Error('无法连接后端服务，上传未完成。');
    error.network = true;
    throw error;
  }
  const text = await response.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = { raw: text }; } }
  if (!response.ok) {
    const error = new Error(response.status === 404
      ? '本地图片上传接口尚未提供（HTTP 404），请等待后端实现 /projects/{project_id}/reference-images。'
      : response.status === 413
        ? '图片超过后端允许的大小（HTTP 413），请选择更小的图片。'
        : response.status === 415
          ? '图片格式不受支持（HTTP 415），请使用 PNG、JPEG 或 WebP。'
          : friendlyHttpError(response.status));
    error.status = response.status;
    error.detail = data?.detail || data?.message || '';
    throw error;
  }
  if (!data?.parent_version_id) throw new Error('上传响应缺少 parent_version_id，无法绑定 Refine parent。');
  return data;
}

async function handleReferenceImageUpload() {
  const input = $('refineImageFile');
  const button = $('refineUploadButton');
  const files = Array.from(input?.files || []);
  const projectId = getProjectId();
  if (!files.length) return setRefineUploadStatus('请先选择至少一张本地图片。', true);
  if (!projectId) return setRefineUploadStatus('请先在项目历史中选择项目，再上传本地图片。', true);
  const invalid = files.find(file => !['image/png', 'image/jpeg', 'image/webp'].includes(file.type));
  if (invalid) return setRefineUploadStatus('文件“' + invalid.name + '”格式不受支持，仅支持 PNG、JPEG 或 WebP。', true);
  if (referenceUploadInFlight) return;
  referenceUploadInFlight = true;
  button.disabled = true;
  setRefineUploadStatus('正在上传 ' + files.length + ' 张参考图…');
  try {
    for (const file of files) {
      const preview = { name: file.name, previewUrl: URL.createObjectURL(file) };
      uploadedReferenceImages.push(preview);
      renderReferencePreview(uploadedReferenceImages);
      const result = await uploadReferenceImage(projectId, file);
      Object.assign(preview, result, { name: file.name });
      uploadedParentVersionId = result.parent_version_id;
      chosenId = uploadedParentVersionId;
      currentTask = { ...(currentTask || {}), project_id: projectId, parent_version_id: uploadedParentVersionId };
      renderReferencePreview(uploadedReferenceImages);
      setRefineUploadStatus('已上传 ' + uploadedReferenceImages.length + '/' + files.length + ' 张，当前已选最后一张作为 Refine parent。');
    }
    renderSelectedParent();
    renderRefineContext();
    input.value = '';
    toast('本地参考图已上传 ' + files.length + ' 张，可点击放大或切换精修图。', 'success');
  } catch (err) {
    setRefineUploadStatus(err.message, true);
    toast('本地图片上传失败：' + err.message, 'error', 9000);
  } finally {
    referenceUploadInFlight = false;
    button.disabled = true;
  }
}

function removeReferenceImage(index) {
  const item = uploadedReferenceImages[index];
  if (!item) return;
  if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
  const removedParentId = item.parent_version_id;
  uploadedReferenceImages.splice(index, 1);
  if (removedParentId && removedParentId === uploadedParentVersionId) {
    uploadedParentVersionId = null;
    if (chosenId === removedParentId) chosenId = null;
    if (currentTask) delete currentTask.parent_version_id;
    renderSelectedParent();
    renderRefineContext();
  }
  renderReferencePreview(uploadedReferenceImages);
  setRefineUploadStatus(uploadedReferenceImages.length
    ? '已保留 ' + uploadedReferenceImages.length + ' 张参考图。'
    : '已移除全部参考图。');
}

function syncRefineControls() {
  const refine = document.querySelector('.mode.active')?.dataset.mode === 'refine';
  const count = $('count');
  const hint = $('countHint');
  if (refine && count) count.value = '1';
  if (hint) hint.textContent = refine
    ? '精修默认生成 1 张，便于确认这次修改；仍可按需调整。'
    : '探索模式可比较多张候选；切换到精修会默认 1 张。';
  renderRefineContext();
}

function renderSelectedParent() {
  document.getElementById('selectedParent')?.remove();
  if (!chosenId) return;
  const top = document.querySelector('.result-top');
  if (!top || !top.parentNode) return;
  const box = document.createElement('div');
  box.id = 'selectedParent';
  box.className = 'selected-parent';
  box.innerHTML = '<strong>selected parent</strong>：' + escapeHtml(chosenId) +
    '<span class="parent-detail">切换到 Refine 后将保留这张候选的主体与当前方向；本轮修改项来自左侧需求和视觉标签。</span>';
  top.insertAdjacentElement('afterend', box);
}

/* ---------- 结果区渲染 ---------- */
function resetResults(msg) {
  stopElapsed();
  chosenId = null;
  generationRounds = [];
  renderRefineContext();
  const r = $('results');
  r.className = 'empty-results panel';
  r.setAttribute('aria-busy', 'false');
  r.innerHTML = '<div class="empty-orbit"></div><h3>你的视觉候选会出现在这里</h3><p>' + (msg || '点击「生成视觉方案」，Agent 将创建任务并真实生成候选图片。') + '</p>';
  const cta = document.createElement('button');
  cta.className = 'secondary-button';
  cta.id = 'loginCta';
  cta.textContent = '先演示登录，再开始生成';
  r.appendChild(cta);
  cta.addEventListener('click', handleLogin);
  cta.hidden = !!getToken();
  $('resultsTitle').textContent = '先从几种感觉里选一个方向';
  $('resultsMeta').textContent = '等待生成';
}

function renderLoading(stepIdx, mainText, subText) {
  const r = $('results');
  // 每次状态更新只保留一条当前轮次状态，避免“创建任务”和“生成候选”叠成两块。
  r.querySelectorAll('.compact-loading, .generation-placeholders').forEach(element => element.remove());
  const previousResults = generationRounds.length ? r.innerHTML : '';
  r.className = 'results panel';
  r.setAttribute('aria-live', 'polite');
  r.setAttribute('aria-busy', 'true');
  const steps = ['创建任务', '生成候选'];
  const count = Math.max(1, Number(currentTask?.output_count) || 1);
  const placeholders = stepIdx === 1
    ? '<div class="candidate-grid generation-placeholders" aria-label="真实生成结果等待区">' +
      Array.from({ length: count }, (_, i) => '<article class="candidate candidate-placeholder" data-generation-placeholder="true" aria-label="候选 ' + (i + 1) + ' 正在等待真实图片"><div class="img-wrap placeholder-wrap" style="aspect-ratio:4/5;background:linear-gradient(110deg,#1c211e 30%,#303a31 45%,#1c211e 60%);background-size:200% 100%;animation:placeholder-shimmer 2.4s ease-in-out infinite"><div class="placeholder-label">候选 ' + String(i + 1).padStart(2, '0') + '<br><span>等待真实图片</span></div></div><div class="candidate-meta"><span class="card-no">CANDIDATE ' + String(i + 1).padStart(2, '0') + '</span><span class="muted">后端返回后显示</span></div></article>').join('') +
      '</div>'
    : '';
  r.innerHTML = previousResults +
    '<div class="loading-block compact-loading" aria-label="生成任务处理中">' +
      '<div class="spinner"></div>' +
      '<div class="loading-copy"><strong>生成任务处理中</strong><span>后台轮询中 · 最长 5 分钟</span></div>' +
      '<div class="gen-steps">' +
        steps.map((s, i) => '<span class="step ' + (i < stepIdx ? 'done' : i === stepIdx ? 'active' : '') + '">' + (i < stepIdx ? '✓ ' : '') + s + '</span>').join('') +
      '</div>' +
    '</div>' + placeholders;
  if (previousResults) {
    const regenerate = r.querySelector('#regenerate');
    if (regenerate) regenerate.addEventListener('click', startNewGeneration);
    bindCandidateImages(r);
  }
}

function startElapsed() {
  stopElapsed();
  genStartedAt = Date.now();
  elapsedTimer = setInterval(() => {
    const s = Math.round((Date.now() - genStartedAt) / 1000);
    const label = s < 60 ? s + ' 秒' : Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒';
    $('resultsMeta').textContent = '生成中 · 已等待 ' + label;
  }, 1000);
  $('resultsMeta').textContent = '生成中 · 已等待 0 秒';
}
function stopElapsed() {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
}

function openLightbox(url, alt) {
  url = resolveImageUrl(url);
  if (!url) return;
  let overlay = $('lightbox');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'lightbox';
    overlay.className = 'lightbox-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', '候选图片大图预览');
    overlay.innerHTML = '<button type="button" class="lightbox-close" aria-label="关闭大图预览">×</button><img class="lightbox-image" alt=""><a class="lightbox-download" target="_blank" rel="noopener" download>下载原图 ↗</a>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', event => { if (event.target === overlay || event.target.closest('.lightbox-close')) closeLightbox(); });
    const closeButton = overlay.querySelector('.lightbox-close');
    const close = event => { event.preventDefault(); event.stopPropagation(); closeLightbox(); };
    closeButton.addEventListener('click', close, true);
    closeButton.addEventListener('pointerup', close, true);
  }
  const image = overlay.querySelector('.lightbox-image');
  image.src = url;
  image.alt = alt || '候选图片大图';
  const download = overlay.querySelector('.lightbox-download');
  download.href = url;
  download.download = (alt || 'tevion-image').replace(/[^\w\u4e00-\u9fff-]+/g, '-').slice(0, 80) + '.png';
  overlay.hidden = false;
  document.body.classList.add('lightbox-open');
  overlay.querySelector('.lightbox-close').focus();
}

function closeLightbox() {
  const overlay = $('lightbox');
  if (!overlay) return;
  overlay.hidden = true;
  document.body.classList.remove('lightbox-open');
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeLightbox();
});

// 动态结果、任务历史和参考图统一走捕获阶段，避免容器重渲染后丢失预览事件。
document.addEventListener('click', event => {
  const target = event.target;
  const preview = target instanceof Element
    ? target.closest('[data-lightbox]')
    : event.composedPath?.().find(item => item instanceof Element && item.matches('[data-lightbox]'));
  if (!preview) return;
  event.preventDefault();
  event.stopPropagation();
  openLightbox(preview.getAttribute('data-lightbox'), preview.querySelector('img')?.alt || '图片大图');
}, true);

function bindLightboxLinks(root) {
  root?.querySelectorAll('[data-lightbox]').forEach(link => {
    link.onclick = event => {
      event.preventDefault();
      event.stopPropagation();
      openLightbox(link.getAttribute('data-lightbox'), link.querySelector('img')?.alt || '图片大图');
      return false;
    };
  });
}

function candidateRoundMarkup(images, roundIndex) {
  const cards = images.map((img, i) => {
    const imageUrl = resolveImageUrl(img.url);
    const w = img.width || 1, h = img.height || 1;
    const dims = (img.width && img.height) ? img.width + '×' + img.height : '';
    return (
      '<article class="candidate" data-id="' + escapeHtml(img.id) + '" data-url="' + escapeHtml(imageUrl) + '">' +
        '<div class="img-wrap" style="aspect-ratio:' + w + '/' + h + '">' +
          '<div class="img-loader">加载图片 ' + (i + 1) + '</div>' +
          '<a class="image-preview" href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noopener" data-lightbox="' + escapeHtml(imageUrl) + '" aria-label="打开第 ' + (roundIndex + 1) + ' 轮候选 ' + (i + 1) + ' 大图预览"><img loading="lazy" alt="第 ' + (roundIndex + 1) + ' 轮候选 ' + (i + 1) + '" src="' + escapeHtml(imageUrl) + '"></a>' +
        '</div>' +
        '<div class="candidate-meta">' +
          '<div class="card-info"><span class="card-no">CANDIDATE ' + String(i + 1).padStart(2, '0') + '</span>' + (dims ? '<span class="card-dims">' + dims + '</span>' : '') + '</div>' +
          '<a class="text-button candidate-download" href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noopener" download="tevion-round-' + String(roundIndex + 1) + '-candidate-' + String(i + 1) + '.png" aria-label="下载第 ' + (roundIndex + 1) + ' 轮候选 ' + (i + 1) + '">下载</a>' +
          '<button type="button" class="select-candidate" aria-label="选择第 ' + (roundIndex + 1) + ' 轮候选 ' + (i + 1) + '" data-select="' + escapeHtml(img.id) + '">选择</button>' +
          '<button type="button" class="reject-candidate" aria-label="拒绝第 ' + (roundIndex + 1) + ' 轮候选 ' + (i + 1) + '" data-reject="' + escapeHtml(img.id) + '">拒绝</button>' +
        '</div>' +
      '</article>'
    );
  }).join('');
  const taskId = generationRounds[roundIndex]?.taskId || '';
  return '<section class="generation-round" data-round="' + String(roundIndex + 1) + '"><div class="round-heading"><strong>第 ' + String(roundIndex + 1) + ' 轮</strong>' + (taskId ? '<span>task_id: ' + escapeHtml(taskId) + '</span>' : '') + '</div><div class="candidate-grid">' + cards + '</div></section>';
}

function renderResults(images, outputMeta = {}, { append = false, useState = false } = {}) {
  stopElapsed();
  chosenId = null;
  renderRefineContext();
  const round = { images: Array.isArray(images) ? images : [], meta: outputMeta, taskId: currentTask?.task_id || outputMeta.task_id || '' };
  if (!useState) {
    if (append) generationRounds.push(round);
    else generationRounds = [round];
  }
  const r = $('results');
  r.className = 'results panel';
  r.setAttribute('aria-busy', 'false');
  $('resultsTitle').textContent = '你的视觉候选已就绪，选一张最接近你感觉的';
  const requested = Number(outputMeta.requested_output_count ?? currentTask?.output_count ?? images.length);
  const actual = Number(outputMeta.actual_output_count ?? images.length);
  const shortfall = Number(outputMeta.output_shortfall ?? Math.max(0, requested - actual));
  const completeness = outputMeta.output_completeness;
  const quantityNote = actual === requested && !shortfall
    ? '请求 ' + requested + ' 张 · 实际 ' + actual + ' 张'
    : '请求 ' + requested + ' 张 · 实际 ' + actual + ' 张 · 少 ' + shortfall + ' 张' + (completeness ? '（' + escapeHtml(String(completeness)) + '）' : '');
  $('resultsMeta').textContent = quantityNote + ' · 已就绪';

  // 新轮次优先展示，用户无需滚到结果区底部查找刚生成的内容。
  const cards = generationRounds
    .map((item, index) => ({ item, index }))
    .reverse()
    .map(({ item, index }) => candidateRoundMarkup(item.images, index))
    .join('');

  r.innerHTML =
    '<div class="result-top">' +
      '<div><div class="eyebrow">EXPLORATION ROUND</div><h3>这组候选由真实生成管线产出</h3></div>' +
      '<div class="result-actions"><span class="muted" id="selectionNote"></span><button class="regen-button" id="regenerate">新建一轮 ↻</button><span class="live-pill"><span class="status-dot"></span> 已完成</span></div>' +
    '</div>' +
    '<div class="candidate-count" role="status">' + quantityNote + '。' + (shortfall ? '本次以实际返回为准，拼图内容仍算一张候选图。' : '') + '</div>' +
    cards +
    '<p class="result-hint">' + quantityNote + '。选择、拒绝和继续当前方向都会提交为反馈事件，帮助 Agent 更快收敛。</p>';

  // 图片加载完成 → 淡入（灰底占位 → 真实图）
  r.querySelectorAll('.img-wrap').forEach(wrap => {
    const img = wrap.querySelector('img');
    if (img.complete && img.naturalWidth > 0) wrap.classList.add('loaded');
    else img.addEventListener('load', () => wrap.classList.add('loaded'), { once: true });
    img.addEventListener('error', () => {
      wrap.classList.add('loaded');
      wrap.querySelector('.img-loader').textContent = '图片加载失败';
      toast('候选图加载失败，可尝试「重新生成」。', 'error');
    }, { once: true });
  });
  $('regenerate').addEventListener('click', startNewGeneration);
  bindLightboxLinks(r);
  setBusy(false);
  setGenerateLabel('再次生成视觉方案');
  setAgentPill('已生成 ' + images.length + ' 张候选', 'done');
  setCheckpoint('候选已生成：选择、拒绝或重新生成都将留下反馈记录。');
}

function candidateCardMarkup(img, i) {
  const imageUrl = resolveImageUrl(img.url);
  const w = img.width || 1, h = img.height || 1;
  const dims = (img.width && img.height) ? img.width + '×' + img.height : '';
  return '<article class="candidate" data-id="' + escapeHtml(img.id) + '" data-url="' + escapeHtml(imageUrl) + '">' +
    '<div class="img-wrap" style="aspect-ratio:' + w + '/' + h + '">' +
      '<div class="img-loader">加载图片 ' + (i + 1) + '</div>' +
      '<a class="image-preview" href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noopener" data-lightbox="' + escapeHtml(imageUrl) + '" aria-label="打开候选 ' + (i + 1) + ' 大图预览"><img loading="lazy" alt="候选 ' + (i + 1) + '" src="' + escapeHtml(imageUrl) + '"></a>' +
    '</div><div class="candidate-meta"><div class="card-info"><span class="card-no">CANDIDATE ' + String(i + 1).padStart(2, '0') + '</span>' +
    (dims ? '<span class="card-dims">' + dims + '</span>' : '') +
    '</div><a class="text-button candidate-download" href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noopener" download="tevion-candidate-' + String(i + 1) + '.png" aria-label="下载候选 ' + (i + 1) + '">下载</a><button type="button" class="select-candidate" aria-label="选择候选 ' + (i + 1) + '" data-select="' + escapeHtml(img.id) + '">选择</button>' +
    '<button type="button" class="reject-candidate" aria-label="拒绝候选 ' + (i + 1) + '" data-reject="' + escapeHtml(img.id) + '">拒绝</button></div></article>';
}

function bindCandidateImages(root = $('results')) {
  root.querySelectorAll('.img-wrap').forEach(wrap => {
    const img = wrap.querySelector('img');
    if (!img) return;
    if (img.complete && img.naturalWidth > 0) wrap.classList.add('loaded');
    else img.addEventListener('load', () => wrap.classList.add('loaded'), { once: true });
    img.addEventListener('error', () => {
      wrap.classList.add('loaded');
      wrap.querySelector('.img-loader').textContent = '图片加载失败';
      toast('候选图加载失败，可尝试「重新生成」。', 'error');
    }, { once: true });
  });
  bindLightboxLinks(root);
}

// 只把后端实际返回的图片替换进等待卡，不模拟进度或生成虚假 URL。
function updateGenerationPlaceholders(images, taskId) {
  if (taskId && currentTask?.task_id !== taskId) return;
  const placeholders = Array.from(document.querySelectorAll('[data-generation-placeholder="true"]'));
  if (!placeholders.length || !images.length) return;
  images.forEach((image, index) => {
    const card = placeholders[index];
    if (card && image?.url) card.outerHTML = candidateCardMarkup(image, index);
  });
  bindCandidateImages($('results'));
}

function renderRecoverableTask(message) {
  stopElapsed();
  setBusy(false);
  const r = $('results');
  r.className = 'results panel';
  r.setAttribute('aria-busy', 'false');
  r.innerHTML = '<div class="error-box"><div class="error-title">生成仍可继续查询</div><p>' + escapeHtml(message) + '</p><div class="actions"><button class="small-button" id="continueTaskQuery">继续查询/恢复任务</button><button class="secondary-button" id="errBack">修改需求重来</button></div></div>';
  $('continueTaskQuery').addEventListener('click', () => resumeTaskQuery());
  $('errBack').addEventListener('click', () => { currentTask = null; resetResults(); });
  setAgentPill('等待继续查询', 'busy');
  setCheckpoint('后端任务仍可通过任务详情查询；本页不声明 durable worker。');
}

async function pollTaskUntilComplete(task = currentTask) {
  const taskId = task?.task_id;
  if (!taskId) throw new Error('缺少任务 ID，无法恢复查询。');
  const deadline = Date.now() + GENERATION_POLL_TIMEOUT_MS;
  let lastDetail = null;
  while (Date.now() < deadline) {
    lastDetail = await api('/tasks/' + encodeURIComponent(taskId));
    const runId = lastDetail?.run_id;
    if (runId && ['generating', 'unknown'].includes(String(lastDetail?.status || '').toLowerCase())) {
      try {
        const reconciled = await api('/tasks/' + encodeURIComponent(taskId) + '/generations/' + encodeURIComponent(runId) + '/reconcile', {
          method: 'POST', body: { reason: 'frontend recovery poll' }
        });
        lastDetail = { ...lastDetail, ...reconciled, task_id: taskId, run_id: runId };
      } catch (reconcileError) {
        if (reconcileError.status !== 409 && reconcileError.status !== 404) throw reconcileError;
      }
    }
    const images = Array.isArray(lastDetail?.images) ? lastDetail.images : [];
    if (images.length) updateGenerationPlaceholders(images, taskId);
    const status = String(lastDetail?.status || '').toLowerCase();
    if (status === 'completed' && images.length) return lastDetail;
    if (status === 'failed' || status === 'cancelled' || status === 'needs_user_review') throw new Error(lastDetail.error_message || '任务已结束但未返回图片（status=' + status + '）。');
    await new Promise(resolve => setTimeout(resolve, GENERATION_POLL_INTERVAL_MS));
  }
  const timeout = new Error('查询已等待 300 秒，任务状态仍为 ' + String(lastDetail?.status || 'unknown') + '。');
  timeout.recoveryRequired = true;
  throw timeout;
}

async function trackAsyncGeneration(task) {
  try {
    const detail = await pollTaskUntilComplete(task);
    if (currentTask?.task_id === task.task_id) {
      currentTask.pending = false;
      currentTask.run_id = detail.run_id || currentTask.run_id;
      currentTask.output_meta = detail;
      renderResults(detail.images, detail, { append: true });
      refreshVisualMemory(task.task_id).catch(() => {});
      loadCredits();
      toast('任务已完成：' + detail.images.length + ' 张候选已就绪。', 'success', 4000);
    } else {
      generationRounds.push({
        images: Array.isArray(detail?.images) ? detail.images : [],
        meta: detail,
        taskId: task.task_id,
      });
      // 另一轮可能先完成；先把它补进页面，当前轮次的 loading 状态再接回去。
      if (currentTask?.pending) {
        renderResults([], detail, { useState: true });
        renderLoading(1, '生成中，最长等待 5 分钟', '当前轮次仍在后台生成，已完成的轮次不会被覆盖。');
      }
      toast('后台任务 ' + task.task_id + ' 已完成，可在任务中心查看结果。', 'success', 5000);
      loadProjectTasks().catch(() => {});
    }
  } catch (err) {
    if (currentTask?.task_id !== task.task_id) return;
    if (err.network || err.recoveryRequired) renderRecoverableTask(err.message || '暂时无法查询任务状态。');
    else {
      renderRecoverableTask(err.message || '任务查询未完成。');
      toast('后台任务未完成：' + err.message, 'error', 9000);
    }
  }
}

async function resumeTaskQuery() {
  if (busy || !currentTask?.task_id) return;
  const task = currentTask;
  setBusy(true);
  setGenerateLabel('生成中…');
  renderLoading(1, '继续查询生成任务', '只查询已创建的任务详情，不会重复提交生成。');
  startElapsed();
  try {
    const detail = await pollTaskUntilComplete(task);
    currentTask.pending = false;
    currentTask.run_id = detail.run_id || currentTask.run_id;
    currentTask.output_meta = detail;
    renderResults(detail.images, detail);
    refreshVisualMemory(task.task_id).catch(() => {});
    loadCredits();
    toast('任务已恢复：' + detail.images.length + ' 张候选已就绪。', 'success', 4000);
  } catch (err) {
    if (err.network || err.recoveryRequired) renderRecoverableTask(err.message || '暂时无法查询任务状态。');
    else {
      renderRecoverableTask(err.message || '任务查询未完成。');
      toast('任务查询未完成：' + err.message, 'error', 9000);
    }
  } finally {
    setBusy(false);
    setGenerateLabel('再次生成视觉方案');
  }
}

/* ---------- 候选选择（事件委托） ---------- */
async function submitFeedback(action, targetId, extra = {}) {
  if (!currentTask || !currentTask.task_id) {
    toast('当前没有可提交反馈的任务。', 'error');
    return null;
  }
  const payload = {
    version_id: targetId,
    selected: action === 'select' ? true : action === 'reject' ? false : null,
    rejected: action === 'reject' ? true : action === 'select' ? false : null,
    continue_direction: extra.continue_direction || (action === 'continue' ? 'continue current direction' : null),
    rejection_reason: extra.rejection_reason || (action === 'reject' ? '不符合当前方向' : null),
  };
  return await api(`/tasks/${currentTask.task_id}/feedback`, { method: 'POST', body: payload });
}

function renderFeedbackStatus(text, canRetry = false) {
  let box = document.getElementById('feedbackStatus');
  if (!box) {
    box = document.createElement('div');
    box.id = 'feedbackStatus';
    box.className = 'memory-block';
    const top = document.querySelector('.result-top');
    if (top && top.parentNode) top.parentNode.insertBefore(box, top.nextSibling);
  }
  box.textContent = text;
  let retry = document.getElementById('feedbackRetry');
  if (!retry) {
    retry = document.createElement('button');
    retry.id = 'feedbackRetry';
    retry.className = 'secondary-button';
    retry.textContent = '重试提交反馈';
    retry.addEventListener('click', () => {
      if (lastFeedbackIntent) handleCandidateAction(lastFeedbackIntent.action, lastFeedbackIntent.id);
    });
    box.appendChild(document.createElement('br'));
    box.appendChild(retry);
  }
  retry.hidden = !canRetry;
}

function setMemoryStatus(text, type = '') {
  const status = $('memoryStatus');
  if (status) { status.textContent = text; status.className = 'memory-status' + (type ? ' ' + type : ''); }
}

function preferenceId(item) { return item.id || ''; }

const memoryLabels = {
  scope: { project: '项目记忆', session: '当前会话', user: '个人偏好' },
  source: {
    selection: '候选选择', explicit_feedback: '明确反馈', tagged_feedback: '标签反馈',
    user_edit: '手动编辑', usage: '使用行为', inference: '系统推断'
  },
  key: { image_version_id: '选中的候选图', direction: '视觉方向', rejection_reason: '拒绝原因' },
  status: { active: '生效中', disabled: '已停用', deleted: '已删除' }
};
function memoryLabel(group, value) { return memoryLabels[group]?.[value] || value || '未提供'; }

function renderMemoryItems(items) {
  const target = $('memoryList');
  if (!target) return;
  if (!items.length) {
    target.innerHTML = '<p class="muted">暂无可见记忆。</p>';
    const adopted = $('adoptedMemory');
    if (adopted) { adopted.hidden = true; adopted.innerHTML = ''; }
    return;
  }
  renderAdoptedMemory(items);
  const visibleItems = memoryExpanded ? items : items.slice(0, 1);
  target.innerHTML = visibleItems.map(item => {
    const evidence = Array.isArray(item.evidence_ids) ? item.evidence_ids : [];
    const id = preferenceId(item);
    return '<article class="memory-card" data-preference-id="' + escapeHtml(id) + '">' +
      '<div class="memory-title"><strong>' + escapeHtml(memoryLabel('key', item.key)) + '</strong><span class="memory-status-badge ' + escapeHtml(item.status || 'active') + '">' + escapeHtml(memoryLabel('status', item.status || 'active')) + '</span></div>' +
      '<p class="memory-value">' + escapeHtml(item.value) + '</p>' +
      '<dl class="memory-evidence"><div><dt>记忆范围</dt><dd>' + escapeHtml(memoryLabel('scope', item.scope)) + '</dd></div><div><dt>来源</dt><dd>' + escapeHtml(memoryLabel('source', item.source)) + '</dd></div><div><dt>可信度</dt><dd>' + escapeHtml(String(item.confidence ?? '-')) + '</dd></div><div><dt>证据数量</dt><dd>' + escapeHtml(String(item.evidence_count ?? evidence.length)) + '</dd></div><div class="evidence-ids"><dt>证据记录</dt><dd>' + escapeHtml(evidence.join(', ') || '-') + '</dd></div></dl>' +
      (id && item.status !== 'deleted' ? '<div class="memory-actions"><button type="button" class="memory-edit" data-edit="' + escapeHtml(id) + '">编辑</button><button type="button" class="memory-disable" data-disable="' + escapeHtml(id) + '"' + (item.status === 'disabled' ? ' disabled' : '') + '>停用</button><button type="button" class="memory-delete" data-delete="' + escapeHtml(id) + '">删除</button></div>' : '') +
      '</article>';
  }).join('');
  if (items.length > 1) {
    target.insertAdjacentHTML('beforeend', '<button type="button" class="text-button memory-more" data-memory-more>' + (memoryExpanded ? '收起其他记忆 ↑' : '查看更多（' + items.length + ' 条） →') + '</button>');
  }
}

function renderAdoptedMemory(items) {
  const target = $('adoptedMemory');
  if (!target) return;
  const adopted = items.filter(item => item.key !== 'image_version_id').slice(0, 3);
  if (!adopted.length) { target.hidden = true; target.innerHTML = ''; return; }
  target.hidden = false;
  target.innerHTML = '<div class="adopted-memory-heading"><span class="eyebrow">PROJECT MEMORY</span><span>本轮采用的项目记忆</span></div>' +
    '<div class="adopted-memory-items">' + adopted.map(item => '<span class="adopted-memory-chip"><strong>' + escapeHtml(memoryLabel('key', item.key)) + '</strong><span>' + escapeHtml(item.value) + '</span></span>').join('') + '</div>' +
    '<button type="button" class="text-button adopted-memory-detail" data-adopted-detail>查看来源与证据 →</button>';
}

async function refreshVisualMemory(taskId = currentTask && currentTask.task_id) {
  taskId = taskId || historySessions[0]?.id;
  if (!taskId) { setMemoryStatus('生成任务后加载你的可解释视觉记忆。'); return; }
  const target = $('memoryList');
  setMemoryStatus('正在加载视觉记忆…');
  if (target) target.setAttribute('aria-busy', 'true');
  try {
    const data = await api(`/preferences?scope=project&task_id=${encodeURIComponent(taskId)}`);
    const items = Array.isArray(data && data.items) ? data.items : [];
    renderMemoryItems(items);
    setMemoryStatus('已读取 ' + items.length + ' 条记忆。');
  } catch (err) {
    if (target) target.innerHTML = '<p class="memory-error">记忆读取失败：' + escapeHtml(err.message) + '</p>';
    setMemoryStatus(err.status === 401 || err.status === 403 ? '无权限读取视觉记忆，请重新登录。' : '记忆读取失败，可重试。', 'error');
  } finally { if (target) target.setAttribute('aria-busy', 'false'); }
}

async function mutatePreference(id, action, value) {
  const method = action === 'delete' ? 'DELETE' : action === 'disable' ? 'POST' : 'PATCH';
  const path = action === 'disable' ? `/preferences/${encodeURIComponent(id)}/disable` : `/preferences/${encodeURIComponent(id)}`;
  const body = action === 'edit' ? { value } : undefined;
  setMemoryStatus('正在保存记忆变更…');
  try {
    await api(path, { method, ...(body ? { body } : {}) });
    await refreshVisualMemory();
    setMemoryStatus('记忆已更新，已完成 stale readback 校验。');
    toast(action === 'delete' ? '记忆已删除。' : action === 'disable' ? '记忆已停用。' : '记忆已编辑。', 'success');
  } catch (err) {
    setMemoryStatus(err.status === 401 || err.status === 403 ? '无权限修改这条记忆。' : '记忆变更失败：' + err.message, 'error');
  }
}

$('memoryList')?.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.memoryMore !== undefined) {
    memoryExpanded = !memoryExpanded;
    refreshVisualMemory();
    return;
  }
  const id = button.dataset.edit || button.dataset.disable || button.dataset.delete;
  if (!id) return;
  if (button.dataset.edit) {
    const card = button.closest('.memory-card');
    const value = window.prompt('编辑偏好内容', card?.querySelector('.memory-value')?.textContent || '');
    if (value && value.trim()) mutatePreference(id, 'edit', value.trim());
  } else if (button.dataset.disable) {
    mutatePreference(id, 'disable');
  } else if (button.dataset.delete && window.confirm('确认删除这条记忆？')) {
    mutatePreference(id, 'delete');
  }
});

$('adoptedMemory')?.addEventListener('click', event => {
  if (event.target.closest('[data-adopted-detail]')) {
    $('contextPrimary')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    $('memoryBtn')?.focus();
  }
});

async function handleCandidateAction(action, id) {
  if (!id) return;
  lastFeedbackIntent = { action, id };
  renderFeedbackStatus(action === 'reject' ? '正在提交“拒绝”反馈…' : action === 'continue' ? '正在提交“继续当前方向”反馈…' : '正在提交“选择候选”反馈…', false);
  try {
    const payload = action === 'reject'
      ? { rejection_reason: '不符合当前方向' }
      : { continue_direction: 'continue current direction' };
    const resp = await submitFeedback(action === 'continue' ? 'select' : action, id, payload);
    if (action === 'reject') {
      setCardState(id, '已拒绝');
      $('selectionNote').textContent = '已拒绝 ' + id + ' · 反馈已提交';
      toast('已提交拒绝反馈：' + id, 'success', 3000);
    } else if (action === 'continue') {
      $('selectionNote').textContent = '继续当前方向 · 反馈已提交';
      toast('已提交继续当前方向反馈', 'success', 3000);
    } else {
      chosenId = id;
      setCardState(id, '已选择 ✓');
      renderSelectedParent();
      renderRefineContext();
      $('selectionNote').textContent = '已选择 ' + id + ' · 反馈已提交';
      toast('已提交选择反馈：' + id, 'success', 3000);
    }
    const memoryStatus = resp?.memory_status;
    const memoryMessage = memoryStatus === 'updated'
      ? '反馈已保存，项目记忆已更新。右侧可查看。'
      : memoryStatus === 'disabled'
        ? '反馈已保存，项目记忆总结未启用。'
        : memoryStatus === 'failed'
          ? '反馈已保存，但项目记忆更新失败；当前反馈不会丢失。'
          : '反馈已保存，正在刷新项目记忆…';
    renderFeedbackStatus(memoryMessage, false);
    toast(memoryMessage, memoryStatus === 'failed' ? 'info' : 'success', 5000);
    if (resp) await refreshVisualMemory();
  } catch (err) {
    renderFeedbackStatus('反馈提交失败：' + err.message, true);
    toast('反馈提交失败：' + err.message, 'error', 9000);
    $('selectionNote').textContent = '反馈提交失败，可重试';
  }
}

function setCardState(id, label) {
  const card = Array.from(document.querySelectorAll('#results .candidate')).find(item => item.dataset.id === id);
  if (!card) return;
  const selected = label.includes('选择');
  card.classList.toggle('chosen', selected);
  card.classList.toggle('rejected', !selected);
  const selectButton = card.querySelector('.select-candidate');
  const rejectButton = card.querySelector('.reject-candidate');
  if (selectButton) selectButton.textContent = selected ? '已选择 ✓' : '选择';
  if (rejectButton) rejectButton.textContent = selected ? '拒绝' : '已拒绝';
  card.querySelector('.chosen-flag')?.remove();
  card.querySelector('.rejected-flag')?.remove();
  const flag = document.createElement('div');
  flag.className = selected ? 'chosen-flag' : 'rejected-flag';
  flag.textContent = label;
  card.querySelector('.img-wrap')?.appendChild(flag);
}

function selectCandidate(id) {
  if (busy) return;
  chosenId = id;
  document.querySelectorAll('#results .candidate').forEach(card => {
    if (card.dataset.id !== id) {
      card.classList.remove('chosen');
      const btn = card.querySelector('.select-candidate');
      if (btn) btn.textContent = '选择';
      card.querySelector('.chosen-flag')?.remove();
    }
  });
  setCardState(id, '已选择 ✓');
  renderSelectedParent();
  renderRefineContext();
  $('selectionNote').textContent = '已选择 ' + id + ' · 正在提交到反馈 API…';
  renderFeedbackStatus('正在提交“选择候选”反馈…', false);
  handleCandidateAction('select', id);
}

function rejectCandidate(id) {
  if (busy) return;
  const card = Array.from(document.querySelectorAll('#results .candidate')).find(item => item.dataset.id === id);
  if (card) {
    card.classList.add('rejected');
    const btn = card.querySelector('.reject-candidate');
    if (btn) btn.textContent = '已拒绝';
    if (!card.querySelector('.rejected-flag')) {
      const wrap = card.querySelector('.img-wrap');
      const f = document.createElement('div');
      f.className = 'rejected-flag';
      f.textContent = '已拒绝';
      wrap.appendChild(f);
    }
  }
  $('selectionNote').textContent = '已拒绝 ' + id + ' · 正在提交到反馈 API…';
  handleCandidateAction('reject', id);
}

/* ---------- 主流程：创建任务 → 生成 ---------- */
function readRequestText() {
  const raw = $('request').value.trim();
  if (!raw) { toast('请先描述你想创作的内容。', 'error'); $('request').focus(); return null; }
  const tags = Array.from(document.querySelectorAll('.chip.active')).map(c => c.textContent.trim());
  return tags.length ? raw + '（视觉方向：' + tags.join('、') + '）' : raw;
}

function startNewGeneration() {
  if (busy) return;
  currentTask = null;
  handleGenerate();
}

async function handleGenerate({ reuse = false } = {}) {
  if (busy) return;
  if (!getToken()) {
    toast('请先点击右上角「演示登录」。', 'error');
    const cta = $('loginCta');
    if (cta) cta.hidden = false;
    $('loginBtn').scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }

  if (!reuse) {
    const request = readRequestText();
    if (!request) return;
    const mode = document.querySelector('.mode.active').dataset.mode;
    currentTask = { request, mode, aspect_ratio: $('ratio').value, output_count: Number($('count').value) };
    const parentVersionId = uploadedParentVersionId || (mode === 'refine' ? chosenId : null);
    if (mode === 'refine' && !parentVersionId) {
        toast('精修前请先选择一张候选图。', 'error');
        return;
    }
    if (parentVersionId) currentTask.parent_version_id = parentVersionId;
  }
  if (!currentTask || !currentTask.task_id && !reuse && !currentTask.request) return;

  setBusy(true);
  setGenerateLabel('生成中…');
  if (reuse) chosenId = null;

  try {
    // 1) 建任务（未复用旧任务时）
    if (!currentTask.task_id) {
      setAgentPill('正在创建任务', 'busy');
      renderLoading(0, 'Agent 正在理解你的需求…', '正在把文字与标签整理成任务，请稍候。');
      setCheckpoint('正在创建任务并登记你的本次需求…');
      const created = await api('/tasks', { method: 'POST', body: {
        request: currentTask.request,
        project_id: getProjectId() || null,
        mode: currentTask.mode,
        output_count: currentTask.output_count,
        aspect_ratio: currentTask.aspect_ratio,
        ...(currentTask.parent_version_id ? { parent_version_id: currentTask.parent_version_id } : {})
      }});
      currentTask.task_id = created.task_id;
      currentTask.run_id = created.run_id;
      showEcho(currentTask.request);
      setCheckpoint('需求已记录（任务 ' + currentTask.task_id + '），开始生成候选…');
      setAgentPill('需求已记录，开始生成', 'busy');
    } else {
      showEcho(currentTask.request);
      setCheckpoint('复用任务 ' + currentTask.task_id + '，重新生成候选…');
    }

    // 2) 提交生成；若 Provider 异步，后续由后台按 task ID 查询
    renderLoading(1, '生成中，最长等待 5 分钟', '图片由真实后端管线生成，请保持本页打开，耐心等待。');
    startElapsed();
    setAgentPill('正在生成 ' + (currentTask.output_count || 4) + ' 张候选', 'busy');

    const submittedTask = { ...currentTask };
    let resp = await api('/tasks/' + currentTask.task_id + '/generate', { method: 'POST' });
    let images = resp && Array.isArray(resp.images) ? resp.images : null;

    // 异步接口只负责提交；后续查询在后台进行，用户可以立即创建下一轮。
    if (!images || !images.length) {
      if (resp && ['generating', 'unknown'].includes(String(resp.status || '').toLowerCase())) {
        stopElapsed();
        setAgentPill('已提交，后台生成中', 'busy');
        setCheckpoint('任务 ' + submittedTask.task_id + ' 已提交，后台会通过 task ID 查询结果；现在可以创建新一轮。');
        currentTask.pending = true;
        submittedTask.pending = true;
        trackAsyncGeneration(submittedTask);
        return;
      } else {
        const detail = await api('/tasks/' + currentTask.task_id);
        resp = { ...resp, ...detail };
      }
      images = resp && Array.isArray(resp.images) ? resp.images : null;
    }
    if (!images || !images.length) {
      const status = (resp && resp.status) || '';
      throw new Error('生成接口未返回图片（status=' + status + '）。请确认后端 generate 已返回 images 数组。');
    }
    currentTask.run_id = resp.run_id || currentTask.run_id;
    currentTask.pending = false;
    currentTask.output_meta = resp;
    renderResults(images, resp, { append: true });
    refreshVisualMemory(currentTask.task_id).catch(() => {});
    loadCredits();
    toast('生成完成：' + images.length + ' 张候选已就绪。', 'success', 4000);
  } catch (err) {
    stopElapsed();
    if (err.network || err.recoveryRequired) {
      renderRecoverableTask(err.message || '暂时无法查询任务状态。');
      return;
    }
    setBusy(false);
    const msg = err.message || String(err);
    toast('生成失败：' + msg, 'error', 9000);
    const r = $('results');
    r.className = 'results panel';
    r.setAttribute('aria-busy', 'false');
    const taskId = currentTask && currentTask.task_id;
    r.innerHTML =
      '<div class="error-box">' +
        '<div class="error-title">这次生成没有成功</div>' +
        (err.status ? '<span class="err-code">HTTP ' + err.status + '</span><br>' : '') +
        '<p>' + escapeHtml(msg) + '</p>' +
        '<div class="actions">' +
          (taskId ? '<button class="small-button" id="errRetry">重试生成</button>' : '') +
          '<button class="secondary-button" id="errBack">修改需求重来</button>' +
        '</div>' +
      '</div>';
    if (taskId) r.querySelector('#errRetry').addEventListener('click', () => handleGenerate({ reuse: true }));
    r.querySelector('#errBack').addEventListener('click', () => { currentTask = null; resetResults(); });
    setAgentPill('出错了', 'busy');
    setCheckpoint('生成未完成。可按上方按钮重试，或检查后端日志。');
  } finally {
    setBusy(false);
    if (!busy) setGenerateLabel('再次生成视觉方案');
  }
}

/* ---------- 事件绑定 ---------- */
document.querySelectorAll('.chip').forEach(chip =>
  chip.addEventListener('click', () => { chip.classList.toggle('active'); syncStyleSummary(); }));
function syncStyleSummary() {
  const summary = $('styleSummary');
  if (!summary) return;
  const values = Array.from(document.querySelectorAll('.chip.active')).map(chip => chip.textContent.trim());
  summary.textContent = values.length ? values.join('、') : '未选择，将由文字描述主导';
}
syncStyleSummary();
document.querySelectorAll('.mode').forEach(mode =>
  mode.addEventListener('click', () => {
    document.querySelectorAll('.mode').forEach(m => m.classList.remove('active'));
    mode.classList.add('active');
    syncRefineControls();
    updateCreditEstimate();
  }));
$('count')?.addEventListener('change', updateCreditEstimate);
$('generate').addEventListener('click', startNewGeneration);
$('refreshPageBtn')?.addEventListener('click', reloadPage);
$('loginBtn').addEventListener('click', () => routeTo('login'));
$('projectsBtn')?.addEventListener('click', () => routeTo('projects'));
$('newProjectBtn')?.addEventListener('click', () => routeTo('new-project'));
$('providerSettingsBtn')?.addEventListener('click', () => { routeTo('provider-settings'); loadProviderSettings(); });
$('backFromProviderSettingsBtn')?.addEventListener('click', () => routeTo('projects'));
$('providerSettingsForm')?.addEventListener('submit', saveProviderSettings);
$('adminBtn')?.addEventListener('click', () => routeTo('admin'));
$('backFromAdminBtn')?.addEventListener('click', () => routeTo('projects'));
$('adminCreditForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const message = $('adminCreditMessage');
  if (message) message.textContent = '正在写入账本…';
  try {
    const data = await api('/admin/credits/adjust', { method: 'POST', body: {
      user_id: $('adminUserId').value.trim(), points: Number($('adminPoints').value), reason: $('adminReason').value.trim()
    }});
    if (message) message.textContent = '调整成功，当前余额：' + data.balance_points + ' 点。账本记录：' + data.ledger_entry_id;
    toast('点数账本调整成功。', 'success');
  } catch (err) {
    if (message) message.textContent = '调整失败：' + err.message;
    toast('点数调整失败：' + err.message, 'error');
  }
});
$('closeCreditModal')?.addEventListener('click', () => $('creditModal').close());
$('cancelCreditModal')?.addEventListener('click', () => $('creditModal').close());
$('closeLedgerModal')?.addEventListener('click', () => $('ledgerModal').close());
$('newAdminUserBtn')?.addEventListener('click', () => {
  $('newUserForm')?.reset();
  $('newUserMessage').textContent = '';
  $('newUserModal')?.showModal();
});
$('closeNewUserModal')?.addEventListener('click', () => $('newUserModal').close());
$('cancelNewUserModal')?.addEventListener('click', () => $('newUserModal').close());
$('closePasswordModal')?.addEventListener('click', () => $('passwordModal').close());
$('cancelPasswordModal')?.addEventListener('click', () => $('passwordModal').close());
$('passwordForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const message = $('passwordMessage');
  message.textContent = '正在修改密码…';
  try {
    const body = {};
    if ($('adminNewPassword').value) {
      body.password = $('adminNewPassword').value;
      body.confirm_password = $('adminConfirmPassword').value;
    }
    const data = await api('/admin/users/' + encodeURIComponent($('passwordUserId').value) + '/password', { method: 'PUT', body });
    message.textContent = data.temporary_password ? '密码已修改。新密码（仅显示这一次）：' + data.temporary_password : '密码已修改并安全保存。';
    toast('用户密码已修改。', 'success');
  } catch (err) { message.textContent = '修改失败：' + err.message; }
});
$('newUserForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const message = $('newUserMessage');
  message.textContent = '正在创建用户…';
  try {
    const body = { email: $('newUserEmail').value.trim(), is_super_admin: $('newUserAdmin').checked };
    if ($('newUserPassword').value) body.password = $('newUserPassword').value;
    const data = await api('/admin/users', { method: 'POST', body });
    message.textContent = data.temporary_password
      ? '用户已创建。系统生成的初始密码（仅显示这一次）：' + data.temporary_password
      : '用户已创建，密码已安全保存。';
    await loadAdminPage();
    toast('用户创建成功。', 'success');
  } catch (err) { message.textContent = '创建失败：' + err.message; }
});
$('adminUserList')?.addEventListener('click', async event => {
  const button = event.target.closest('[data-admin-user], [data-admin-ledger], [data-admin-password]');
  if (!button) return;
  if (button.dataset.adminSelect) {
    $('adminUserId').value = button.dataset.adminSelect;
    $('adminSelectedUser').textContent = '已选择 ' + button.dataset.adminSelect;
    $('adminCreditForm').reset();
    $('adminUserId').value = button.dataset.adminSelect;
    $('adminSelectedUser').textContent = '已选择 ' + button.dataset.adminSelect;
    $('creditModal').showModal();
    $('adminPoints').focus();
    return;
  }
  if (button.dataset.adminLedger) {
    try {
      const entries = await api('/admin/users/' + encodeURIComponent(button.dataset.adminLedger) + '/credits/ledger');
      $('ledgerModalUser').textContent = button.dataset.adminName || button.dataset.adminLedger;
      $('ledgerList').innerHTML = entries.map(entry => '<tr><td>' + escapeHtml(taskDate(entry.created_at)) + '</td><td class="' + (entry.delta_points >= 0 ? 'ledger-positive' : 'ledger-negative') + '">' + (entry.delta_points >= 0 ? '+' : '') + entry.delta_points + ' 点</td><td>' + escapeHtml(entry.entry_type) + '</td><td>' + escapeHtml(entry.reason) + '</td></tr>').join('') || '<tr><td colspan="4" class="muted">暂无流水记录。</td></tr>';
      $('ledgerModal').showModal();
    } catch (err) { toast('流水读取失败：' + err.message, 'error'); }
    return;
  }
  if (button.dataset.adminPassword) {
    $('passwordForm').reset();
    $('passwordUserId').value = button.dataset.adminPassword;
    $('passwordUser').textContent = button.dataset.adminName || button.dataset.adminPassword;
    $('passwordMessage').textContent = '';
    $('passwordModal').showModal();
    $('adminNewPassword').focus();
    return;
  }
  try {
    await api('/admin/users/' + encodeURIComponent(button.dataset.adminUser) + '/role', { method: 'PUT', body: { is_super_admin: button.dataset.adminRole === 'true' } });
    await loadAdminPage();
    toast('管理员权限已更新。', 'success');
  } catch (err) { toast('权限更新失败：' + err.message, 'error'); }
});
$('clearProviderSettingsBtn')?.addEventListener('click', clearProviderSettings);
$('manageProjectsBtn')?.addEventListener('click', () => routeTo('projects'));
$('workbenchNewProjectBtn')?.addEventListener('click', () => routeTo('new-project'));
$('backToProjectsBtn')?.addEventListener('click', () => routeTo('projects'));
$('cancelProjectBtn')?.addEventListener('click', () => routeTo('projects'));
$('logoutBtn').addEventListener('click', handleLogout);
$('aestheticProfileBtn')?.addEventListener('click', () => {
  $('authChip').open = false;
  routeTo('workbench');
  window.setTimeout(() => {
    $('contextPrimary')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    refreshVisualMemory();
  }, 150);
});
$('authChip')?.addEventListener('click', event => {
  if (event.target.closest('.account-menu-button')) $('authChip').open = false;
});
document.addEventListener('click', event => {
  const menu = $('authChip');
  if (menu?.open && !menu.contains(event.target)) menu.open = false;
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && $('authChip')?.open) $('authChip').open = false;
});
$('authForm')?.addEventListener('submit', submitAuth);
$('devTokenBtn')?.addEventListener('click', handleLogin);
$('oidcBtn')?.addEventListener('click', async () => { if (!(await startOidcLogin())) $('authMessage').textContent = 'OIDC 尚未配置，请使用邮箱登录或本地 dev-token。'; });
window.addEventListener('hashchange', () => renderRoute());
$('refineUploadButton')?.addEventListener('click', handleReferenceImageUpload);
$('refineImageFile')?.addEventListener('change', event => {
  const files = Array.from(event.target.files || []);
  const button = $('refineUploadButton');
  if (button) button.disabled = !files.length;
  if (!files.length) return setRefineUploadStatus('');
  if (getProjectId()) {
    setRefineUploadStatus('已选择 ' + files.length + ' 张图片，正在自动上传并绑定…');
    handleReferenceImageUpload();
  } else {
    setRefineUploadStatus('请先选择项目；随后点击“重新上传所选图片”完成上传。', true);
  }
});
$('referencePreview')?.addEventListener('click', event => {
  const preview = event.target.closest('[data-lightbox]');
  if (preview) {
    const image = preview.querySelector('img') || preview.closest('.reference-card')?.querySelector('img');
    event.preventDefault();
    openLightbox(preview.getAttribute('data-lightbox'), image?.alt || '参考图');
    return;
  }
  const remove = event.target.closest('[data-reference-delete]');
  if (remove) {
    removeReferenceImage(Number(remove.dataset.referenceDelete));
    return;
  }
  const parent = event.target.closest('[data-reference-parent]');
  if (!parent?.dataset.referenceParent) return;
  uploadedParentVersionId = parent.dataset.referenceParent;
  chosenId = uploadedParentVersionId;
  currentTask = { ...(currentTask || {}), project_id: getProjectId(), parent_version_id: uploadedParentVersionId };
  renderReferencePreview(uploadedReferenceImages);
  renderSelectedParent();
  renderRefineContext();
  setRefineUploadStatus('已切换当前 Refine parent：' + uploadedParentVersionId);
});
$('historyProject')?.addEventListener('change', event => {
  setProjectId(event.target.value);
  loadHistorySessions(event.target.value);
});
$('historySession')?.addEventListener('change', event => loadHistoryVersions(event.target.value));
$('projectSelect')?.addEventListener('change', event => handleProjectChange(event.target.value));
$('taskCenterRetry')?.addEventListener('click', () => loadProjectTasks());
$('taskPagination')?.addEventListener('click', event => {
  const button = event.target.closest('[data-task-page]');
  const more = event.target.closest('[data-task-more]');
  if (more) {
    taskExpanded = more.dataset.taskMore === 'expand';
    taskPage = 1;
    renderTaskList(projectTasks);
    return;
  }
  if (!button || button.disabled) return;
  taskExpanded = true;
  taskPage += button.dataset.taskPage === 'next' ? 1 : -1;
  renderTaskList(projectTasks);
});
$('taskList')?.addEventListener('click', event => {
  const preview = event.target.closest('[data-lightbox]');
  if (preview) {
    event.preventDefault();
    openLightbox(preview.getAttribute('data-lightbox'), preview.querySelector('img')?.alt || '任务结果');
    return;
  }
  const button = event.target.closest('button');
  if (!button) return;
  const task = parseTaskData(button.dataset.taskContinue || button.dataset.taskRetry || button.dataset.taskView || button.dataset.taskRefine);
  if (button.dataset.taskContinue) continueTaskFromCenter(task);
  else if (button.dataset.taskRetry) retryTaskFromCenter(task);
  else if (button.dataset.taskView) viewTaskFromCenter(task);
  else if (button.dataset.taskRefine) viewTaskFromCenter(task, true);
});
$('projectForm')?.addEventListener('submit', createProject);
$('projectManagementList')?.addEventListener('click', event => {
  const button = event.target.closest('[data-open-project], [data-new-project]');
  if (!button) return;
  if (button.dataset.newProject !== undefined) return routeTo('new-project');
  setProjectId(button.dataset.openProject);
  routeTo('workbench');
  loadProjects();
});
$('results').addEventListener('click', e => {
  const preview = e.target.closest('[data-lightbox]');
  if (preview) {
    e.preventDefault();
    openLightbox(preview.getAttribute('data-lightbox'), preview.querySelector('img')?.alt || '候选图片');
    return;
  }
  const sel = e.target.closest('[data-select]');
  if (sel) {
    selectCandidate(sel.dataset.select);
    return;
  }
  const reject = e.target.closest('[data-reject]');
  if (reject) rejectCandidate(reject.dataset.reject);
});

/* 图片加载失败的全局兜底（个别候选图加载超时） */
$('memoryBtn').addEventListener('click', () => refreshVisualMemory());
$('profileBtn').addEventListener('click', async () => {
  try {
    const user = await api('/auth/me');
    const credits = await api('/credits');
    $('profileEmail').value = user.email || user.provider_subject || '';
    $('profileCredits').textContent = Number(credits?.balance_points || 0) + ' 点';
    $('profileDisplayName').value = user.display_name || '';
    $('profileMessage').textContent = '';
    $('profileModal').showModal();
  } catch (err) { toast('个人信息读取失败：' + err.message, 'error'); }
});
$('closeProfileModal')?.addEventListener('click', () => $('profileModal').close());
$('cancelProfileModal')?.addEventListener('click', () => $('profileModal').close());
$('profileForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await api('/auth/me', { method: 'PATCH', body: { display_name: $('profileDisplayName').value.trim() || null } });
    $('profileMessage').textContent = '个人信息已保存。';
    toast('个人信息已更新。', 'success');
  } catch (err) { $('profileMessage').textContent = '保存失败：' + err.message; }
});

handleOidcCallback().catch(err => toast('登录回调失败：' + err.message, 'error', 8000)).finally(() => {
  refreshLoginUI();
  if (getToken()) loadProjectHistory();
});
refreshLoginUI();
renderRefineContext();
syncRefineControls();
updateCreditEstimate();
renderRoute();
