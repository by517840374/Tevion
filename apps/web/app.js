/* Tevion 前端工作台 — 连接真实后端 API
 * 后端地址如有变化，只需修改 API_BASE。
 */
const API_BASE = window.TEVION_API_BASE || 'http://127.0.0.1:8010/api/v1';
const TOKEN_KEY = 'tevion_token';

/* ---------- 小工具 ---------- */
const $ = id => document.getElementById(id);
let busy = false;
let currentTask = null;   // { task_id, request, mode, aspect_ratio, output_count }
let chosenId = null;      // 当前高亮的候选图 id
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
function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

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
    '<p class="result-hint">选择不是考试。你的选择会告诉 Agent：这张图的脸、光影、气质或构图，哪一部分更接近你。</p>';

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
  setCheckpoint('候选已生成：选择一张作为你的方向，或点击「重新生成」继续探索。');
}

/* ---------- 候选选择（事件委托） ---------- */
function selectCandidate(id) {
  if (busy || chosenId === id) return;
  chosenId = id;
  document.querySelectorAll('#results .candidate').forEach(card => {
    const flag = card.querySelector('.chosen-flag');
    if (card.dataset.id === id) {
      card.classList.add('chosen');
      const btn = card.querySelector('.select-candidate');
      if (btn) btn.textContent = '已选择 ✓';
      if (!flag) {
        const wrap = card.querySelector('.img-wrap');
        const f = document.createElement('div');
        f.className = 'chosen-flag';
        f.textContent = '已选择 ✓';
        wrap.appendChild(f);
      }
    } else {
      card.classList.remove('chosen');
      const btn = card.querySelector('.select-candidate');
      if (btn) btn.textContent = '选择';
      if (flag) flag.remove();
    }
  });
  $('selectionNote').textContent = '已选择 ' + id + ' · 可换一张或重新生成';
  toast('已选择候选：' + id, 'success', 3000);
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
  }
  if (!currentTask || !currentTask.task_id && !reuse && !currentTask.request) return;

  setBusy(true);
  chosenId = null;

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
        aspect_ratio: currentTask.aspect_ratio
      }});
      currentTask.task_id = created.task_id;
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
  if (sel) selectCandidate(sel.dataset.select);
});

/* 图片加载失败的全局兜底（个别候选图加载超时） */
$('memoryBtn').addEventListener('click', () => toast('视觉记忆管理将在后续版本开放。', 'info'));
$('profileBtn').addEventListener('click', () => toast('审美画像功能将在后续版本开放。', 'info'));

refreshLoginUI();
