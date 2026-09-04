/* Tevion 前端工作台 — 连接真实后端 API
 * 后端地址如有变化，只需修改 API_BASE。
 */
const API_BASE = window.TEVION_API_BASE || 'http://127.0.0.1:8010/api/v1';

const OIDC_CONFIG = window.TEVION_OIDC_CONFIG || null;
const TOKEN_KEY = 'tevion_token';
const OIDC_TRANSACTION_KEY = 'tevion_oidc_transaction';

/* ---------- 小工具 ---------- */
const $ = id => document.getElementById(id);
let busy = false;
let currentTask = null;   // { task_id, request, mode, aspect_ratio, output_count }
let chosenId = null;      // 当前高亮的候选图 id
let lastFeedbackIntent = null;
let elapsedTimer = null;
let genStartedAt = 0;

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
  toast('已退出演示登录。', 'info');
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

/* ---------- 结果区渲染 ---------- */
function resetResults(msg) {
  stopElapsed();
  const r = $('results');
  r.className = 'empty-results panel';
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
  r.className = 'results panel';
  const steps = ['创建任务', '生成候选'];
  r.innerHTML =
    '<div class="loading-block">' +
      '<div class="spinner"></div>' +
      '<h3>' + escapeHtml(mainText) + '</h3>' +
      '<p>' + escapeHtml(subText || '') + '</p>' +
      '<div class="gen-steps">' +
        steps.map((s, i) => '<span class="step ' + (i < stepIdx ? 'done' : i === stepIdx ? 'active' : '') + '">' + (i < stepIdx ? '✓ ' : '') + s + '</span>').join('') +
      '</div>' +
    '</div>';
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

function renderResults(images) {
  stopElapsed();
  chosenId = null;
  const r = $('results');
  r.className = 'results panel';
  $('resultsTitle').textContent = '你的视觉候选已就绪，选一张最接近你感觉的';
  $('resultsMeta').textContent = images.length + ' 张候选 · 已就绪';

  const cards = images.map((img, i) => {
    const w = img.width || 1, h = img.height || 1;
    const dims = (img.width && img.height) ? img.width + '×' + img.height : '';
    return (
      '<article class="candidate" data-id="' + escapeHtml(img.id) + '" data-url="' + escapeHtml(img.url) + '">' +
        '<div class="img-wrap" style="aspect-ratio:' + w + '/' + h + '">' +
          '<div class="img-loader">加载图片 ' + (i + 1) + '</div>' +
          '<img loading="lazy" alt="候选 ' + (i + 1) + '" src="' + escapeHtml(img.url) + '">' +
        '</div>' +
        '<div class="candidate-meta">' +
          '<div class="card-info">' +
            '<span class="card-no">CANDIDATE ' + String(i + 1).padStart(2, '0') + '</span>' +
            (dims ? '<span class="card-dims">' + dims + '</span>' : '') +
          '</div>' +
          '<button class="select-candidate" data-select="' + escapeHtml(img.id) + '">选择</button>' +
          '<button class="reject-candidate" data-reject="' + escapeHtml(img.id) + '">拒绝</button>' +
        '</div>' +
      '</article>'
    );
  }).join('');

  r.innerHTML =
    '<div class="result-top">' +
      '<div><div class="eyebrow">EXPLORATION ROUND</div><h3>这组候选由真实生成管线产出</h3></div>' +
      '<div class="result-actions"><span class="muted" id="selectionNote"></span><button class="regen-button" id="regenerate">重新生成 ↻</button><span class="live-pill"><span class="status-dot"></span> 已完成</span></div>' +
    '</div>' +
    '<div class="candidate-grid">' + cards + '</div>' +
    '<p class="result-hint">选择、拒绝和继续当前方向都会提交为反馈事件，帮助 Agent 更快收敛。</p>';

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

  $('regenerate').addEventListener('click', () => handleGenerate({ reuse: true }));
  setBusy(false);
  setAgentPill('已生成 ' + images.length + ' 张候选', 'done');
  setCheckpoint('候选已生成：选择、拒绝或重新生成都将留下反馈记录。');
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

async function refreshVisualMemory() {
  if (!currentTask || !currentTask.task_id) return;
  const right = document.querySelector('.right-column');
  if (!right) return;
  try {
    const data = await api(`/preferences?scope=project&task_id=${encodeURIComponent(currentTask.task_id)}`);
    const items = Array.isArray(data && data.items) ? data.items : [];
    const grouped = items.reduce((acc, item) => {
      const scope = item.scope || 'project';
      (acc[scope] ||= []).push(item);
      return acc;
    }, {});
    const makeTags = list => list.length
      ? '<div class="memory-tags">' + list.map(item => '<span>' + escapeHtml(item.key + ': ' + item.value) + '</span>').join('') + '</div>'
      : '<p class="muted">暂无可见记忆。</p>';
    right.innerHTML =
      '<div class="eyebrow">VISUAL MEMORY</div>' +
      '<h2>Agent 对你的理解</h2>' +
      '<p class="muted intro">来自偏好查询端点的项目记忆</p>' +
      '<div class="memory-block"><div class="memory-title"><span>项目偏好</span><span class="confidence">' + items.length + ' 条</span></div>' +
      makeTags(grouped.project || []) + '</div>' +
      '<div class="memory-block dim"><div class="memory-title"><span>会话偏好</span><span class="confidence low">' + (grouped.session ? grouped.session.length : 0) + ' 条</span></div>' +
      makeTags(grouped.session || []) + '</div>' +
      '<div class="memory-footer"><span class="memory-pulse"></span><p>反馈后会从后端读取最新偏好。<br><button class="text-button" id="memoryBtn">刷新记忆 →</button></p></div>';
    right.querySelector('#memoryBtn').addEventListener('click', refreshVisualMemory);
  } catch (err) {
    right.querySelector('.intro').textContent = '记忆读取失败：' + err.message;
  }
}

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
      $('selectionNote').textContent = '已选择 ' + id + ' · 反馈已提交';
      toast('已提交选择反馈：' + id, 'success', 3000);
    }
    renderFeedbackStatus('反馈已提交。', false);
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
    if (mode === 'refine' && !reuse) {
      if (!chosenId) {
        toast('精修前请先选择一张候选图。', 'error');
        return;
      }
      currentTask.parent_version_id = chosenId;
    }
  }
  if (!currentTask || !currentTask.task_id && !reuse && !currentTask.request) return;

  setBusy(true);
  if (reuse) chosenId = null;

  try {
    // 1) 建任务（未复用旧任务时）
    if (!currentTask.task_id) {
      setAgentPill('正在创建任务', 'busy');
      renderLoading(0, 'Agent 正在理解你的需求…', '正在把文字与标签整理成任务，请稍候。');
      setCheckpoint('正在创建任务并登记你的本次需求…');
      const created = await api('/tasks', { method: 'POST', body: {
        request: currentTask.request,
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

    // 2) 同步等待真实生成（约 30–120 秒）
    renderLoading(1, '生成中，约需 1–2 分钟', '图片由真实后端管线生成，请保持本页打开，耐心等待。');
    startElapsed();
    setAgentPill('正在生成 ' + (currentTask.output_count || 4) + ' 张候选', 'busy');

    let resp = await api('/tasks/' + currentTask.task_id + '/generate', { method: 'POST' });
    let images = resp && Array.isArray(resp.images) ? resp.images : null;

    // 兼容：generate 若未直接返回图片，则回查任务详情
    if (!images) {
      const detail = await api('/tasks/' + currentTask.task_id);
      images = detail && Array.isArray(detail.images) ? detail.images : null;
    }
    if (!images || !images.length) {
      const status = (resp && resp.status) || '';
      throw new Error('生成接口未返回图片（status=' + status + '）。请确认后端 generate 已返回 images 数组。');
    }
    currentTask.run_id = resp.run_id || currentTask.run_id;
    renderResults(images);
    toast('生成完成：' + images.length + ' 张候选已就绪。', 'success', 4000);
  } catch (err) {
    stopElapsed();
    setBusy(false);
    const msg = err.message || String(err);
    toast('生成失败：' + msg, 'error', 9000);
    const r = $('results');
    r.className = 'results panel';
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
  }
}

/* ---------- 事件绑定 ---------- */
document.querySelectorAll('.chip').forEach(chip =>
  chip.addEventListener('click', () => chip.classList.toggle('active')));
document.querySelectorAll('.mode').forEach(mode =>
  mode.addEventListener('click', () => {
    document.querySelectorAll('.mode').forEach(m => m.classList.remove('active'));
    mode.classList.add('active');
  }));
$('generate').addEventListener('click', () => handleGenerate());
$('loginBtn').addEventListener('click', handleLogin);
$('logoutBtn').addEventListener('click', handleLogout);
$('results').addEventListener('click', e => {
  const sel = e.target.closest('[data-select]');
  if (sel) {
    selectCandidate(sel.dataset.select);
    return;
  }
  const reject = e.target.closest('[data-reject]');
  if (reject) rejectCandidate(reject.dataset.reject);
});

/* 图片加载失败的全局兜底（个别候选图加载超时） */
$('memoryBtn').addEventListener('click', () => toast('视觉记忆管理将在后续版本开放。', 'info'));
$('profileBtn').addEventListener('click', () => toast('审美画像功能将在后续版本开放。', 'info'));

handleOidcCallback().catch(err => toast('登录回调失败：' + err.message, 'error', 8000)).finally(refreshLoginUI);
refreshLoginUI();
