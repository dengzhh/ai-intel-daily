/* ==========================================================================
   AI 情报站 · 前端渲染
   注意：所有条目均来自外部 RSS / API，属于不可信输入，
   因此统一使用 DOM API + textContent 构建，绝不拼接 innerHTML。
   ========================================================================== */

'use strict';

const JSON_URL = 'data/latest.json';
const JS_FALLBACK = 'data/latest.js';

// 历史归档：索引 + 按月分片（懒加载，点开哪个月才请求哪个文件）
const HIST_INDEX_URL = 'data/history/index.json';
const HIST_INDEX_JS = 'data/history/index.js';
const HIST_MONTH_URL = (ym) => 'data/history/' + ym + '.json';

const LANG_COLORS = {
  JavaScript: '#f1e05a', TypeScript: '#3178c6', Python: '#3572A5', Rust: '#dea584',
  Go: '#00ADD8', Java: '#b07219', Kotlin: '#A97BFF', Swift: '#F05138', 'C++': '#f34b7d',
  C: '#555555', 'C#': '#178600', Ruby: '#701516', PHP: '#4F5D95', HTML: '#e34c26',
  CSS: '#663399', Shell: '#89e051', Vue: '#41b883', Dart: '#00B4AB', Lua: '#000080',
  Scala: '#c22d40', Perl: '#0298c3', R: '#198CE7', Julia: '#a270ba', Zig: '#ec915c',
  Elixir: '#6e4a7e', Haskell: '#5e5086', OCaml: '#ef7a08', Matlab: '#e16737',
  'Jupyter Notebook': '#DA5B0B', Astro: '#ff5a03', Svelte: '#ff3e00', Nix: '#7e7eff',
};

const DELTA_LABEL = {
  snapshot: '实测',
  new_repo: '新建',
  estimate: '估算',
  page: '页面',
  none: '—',
};

const state = {
  data: null,
  period: 'three_day',
  view: 'news',       // 'news' | 'repos' | 'history'，默认新闻
  hist: {
    index: null,        // { days: [{date, news, repos}], months: [...] }
    hashes: null,       // Set<'YYYY-MM-DD'>，快速判断某天有无归档
    month: '',          // 日历当前显示的年月，'YYYY-MM'
    selected: '',       // 当前查看的日期，'YYYY-MM-DD'
    mode: 'news',       // 'news' | 'repos'，历史面板展示内容
    cache: {},          // { 'YYYY-MM': { 'YYYY-MM-DD': payload } }
    loadingMonth: '',
    indexPromise: null, // 索引加载中的 Promise，避免重复请求
  },
};

/* ------------------------------------------------------------ 工具函数 ---- */

/** 千分位格式化。 */
function fmt(n) {
  if (typeof n !== 'number' || !isFinite(n)) return '0';
  return n.toLocaleString('en-US');
}

/** 紧凑数字：12345 → 12.3k。 */
function compact(n) {
  if (typeof n !== 'number' || !isFinite(n)) return '0';
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
  return String(n);
}

/** 只放行 http / https，杜绝 javascript: 之类的协议注入。 */
function safeUrl(raw) {
  if (typeof raw !== 'string' || !raw) return null;
  try {
    const u = new URL(raw, window.location.href);
    return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : null;
  } catch (_) {
    return null;
  }
}

/** 创建元素并设置文本与类名。 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

/* ------------------------------------------------------------ 数据加载 ---- */

/**
 * 优先 fetch JSON；若以 file:// 打开（fetch 受 CORS 限制）则回退到脚本方式。
 */
async function loadData() {
  try {
    const res = await fetch(JSON_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } catch (err) {
    console.warn('fetch JSON 失败，回退到脚本数据：', err.message);
    return await loadScriptData();
  }
}

/** 通过 <script> 标签加载预生成的数据文件（file:// 场景可用）。 */
function loadScriptData() {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = JS_FALLBACK;
    s.onload = () => {
      if (window.__AI_INTEL_DATA__) resolve(window.__AI_INTEL_DATA__);
      else reject(new Error('脚本数据未定义'));
    };
    s.onerror = () => reject(new Error('无法加载 ' + JS_FALLBACK));
    document.head.appendChild(s);
  });
}

/* ------------------------------------------------------------ 渲染新闻 ---- */

/**
 * 渲染新闻卡片。
 * @param {Array} items 新闻条目
 * @param {HTMLElement} container 容器
 * @param {HTMLElement} emptyEl 空态节点
 * @param {{archived?: boolean}} opts archived=true 表示历史归档：
 *        文案显示绝对发布时间（"XX 分钟前"对旧闻没有意义）
 */
function renderNews(items, container, emptyEl, opts) {
  const options = opts || {};
  container.textContent = '';
  if (!items || !items.length) {
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;

  items.forEach((item, idx) => {
    const card = el('article', 'news-card');
    card.style.animationDelay = (idx * 35) + 'ms';

    // --- 顶部：排名 / 来源 / 分数 ---
    const top = el('div', 'card-top');
    const rankNo = typeof item.rank === 'number' ? item.rank : idx + 1;
    const rank = el('span', 'rank' + (rankNo <= 3 ? ' r' + rankNo : ''), rankNo);
    top.appendChild(rank);

    const chip = el('span', 'source-chip', item.source || '未知来源');
    if (item.lang) chip.dataset.lang = item.lang;
    top.appendChild(chip);

    if (item.is_paper) top.appendChild(el('span', 'paper-tag', '论文'));

    top.appendChild(el('span', 'spacer'));

    const score = typeof item.score === 'number' ? item.score : 0;
    const scoreBadge = el('span', 'score-badge' + (score >= 0.5 ? ' hot' : score >= 0.35 ? ' mid' : ''),
      score.toFixed(2));
    scoreBadge.title = '综合评分（新鲜度 28% · AI 相关度 27% · 热度 28% · 来源权重 17%）';
    top.appendChild(scoreBadge);
    card.appendChild(top);

    // --- 标题（外链）---
    const url = safeUrl(item.url);
    const title = el('h3', 'news-title');
    if (url) {
      const link = el('a', null, item.title || '(无标题)');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      title.appendChild(link);
    } else {
      title.textContent = item.title || '(无标题)';
    }
    card.appendChild(title);

    // --- 摘要 ---
    if (item.summary) card.appendChild(el('p', 'news-summary', item.summary));

    // --- 底部：关键词 / 时间 / 转载 ---
    const foot = el('div', 'card-foot');
    (item.keywords || []).slice(0, 3).forEach(k => foot.appendChild(el('span', 'kw', k)));

    const right = el('div', 'foot-right');
    if (item.dup_count > 1) {
      const dup = el('span', 'dup', item.dup_count + ' 家转载');
      dup.title = '该事件被多个来源报道';
      right.appendChild(dup);
    }
    const timeText = options.archived
      ? archiveTime(item)
      : (item.display_time || '');
    right.appendChild(el('span', 'time', timeText));
    foot.appendChild(right);
    card.appendChild(foot);

    container.appendChild(card);
  });
}

/** 历史归档里的时间展示：转为北京时间 MM-DD HH:mm。 */
function archiveTime(item) {
  const iso = item.published_iso;
  if (!iso) return '';
  const t = new Date(iso);
  if (isNaN(t.getTime())) return '';
  const cst = new Date(t.getTime() + 8 * 3600 * 1000); // 转北京时间
  const pad = (n) => String(n).padStart(2, '0');
  return pad(cst.getUTCMonth() + 1) + '-' + pad(cst.getUTCDate()) +
    ' ' + pad(cst.getUTCHours()) + ':' + pad(cst.getUTCMinutes());
}

/* ------------------------------------------------------------ 渲染仓库 ---- */

function renderRepos(repos, container, emptyEl, opts) {
  const options = opts || {};
  container.textContent = '';
  if (!repos || !repos.length) {
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;

  repos.forEach((r, idx) => {
    const row = el('div', 'repo-row');
    row.style.animationDelay = (idx * 28) + 'ms';

    // 排名
    row.appendChild(el('div', 'repo-rank' + (idx < 3 ? ' top' : ''), idx + 1));

    // 主体：名称 + 描述
    const main = el('div', 'repo-main');
    const nameLine = el('div', 'repo-name');
    const url = safeUrl(r.url);
    // 历史归档里只存了 full_name，拆出 owner/name 供展示
    let owner = r.owner;
    let name = r.name;
    if ((!owner || !name) && r.full_name) {
      const parts = String(r.full_name).split('/');
      owner = parts[0] || '';
      name = parts.slice(1).join('/') || '';
    }
    if (url) {
      const link = el('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.appendChild(el('span', 'owner', (owner || '') + ' / '));
      link.appendChild(document.createTextNode(name || ''));
      nameLine.appendChild(link);
    } else {
      nameLine.appendChild(el('span', 'owner', (owner || '') + ' / '));
      nameLine.appendChild(document.createTextNode(name || ''));
    }
    if (r.is_new) {
      const badge = el('span', 'badge-new', 'NEW');
      badge.title = '该仓库在区间内新建，当前星数即为区间增量';
      nameLine.appendChild(badge);
    }
    main.appendChild(nameLine);
    if (r.description) {
      const desc = el('div', 'repo-desc', r.description);
      desc.title = r.description;
      main.appendChild(desc);
    }
    row.appendChild(main);

    // 语言
    const langBox = el('div', 'repo-lang');
    const dot = el('span', 'lang-dot');
    if (r.language && LANG_COLORS[r.language]) dot.style.background = LANG_COLORS[r.language];
    langBox.appendChild(dot);
    langBox.appendChild(document.createTextNode(r.language || '—'));
    row.appendChild(langBox);

    // 总星数 / 分叉
    const stars = el('div', 'repo-stars');
    stars.appendChild(el('b', null, '★ ' + fmt(r.stars)));
    if (r.forks) stars.appendChild(document.createTextNode(' ⑂ ' + compact(r.forks)));
    row.appendChild(stars);

    // 区间增量
    const deltaBox = el('div', 'repo-delta');
    deltaBox.appendChild(el('span', 'delta-val', '+' + fmt(r.delta)));
    const label = r.delta_label || (options.archived ? '区间新增' : '');
    const note = el('span', 'delta-note',
      label + (DELTA_LABEL[r.delta_source] ? ' · ' + DELTA_LABEL[r.delta_source] : ''));
    note.title = explainDelta(r);
    deltaBox.appendChild(note);
    row.appendChild(deltaBox);

    container.appendChild(row);
  });
}

/** 增量来源的说明文案。 */
function explainDelta(r) {
  const map = {
    snapshot: '由本地历史快照差分得出：当前星数减去该区间起点的星数，为实测值。',
    new_repo: '该仓库在区间内新建，起点星数为 0，因此当前星数即为区间真实增量。',
    estimate: 'GitHub 官方未提供三日档位，此处按周增量的日均速度外推三日，为估算值。',
    page: '直接取自 GitHub Trending 页面标注的区间新增星数。',
    none: '暂无可用增量数据。',
  };
  return map[r.delta_source] || '';
}

/* -------------------------------------------------------------- 顶部态 ---- */

function renderHeader(data) {
  document.getElementById('genTime').textContent = data.generated_at_cst || '—';
  const stats = data.news_stats || {};
  document.getElementById('rawCount').textContent =
    stats.raw_count ? stats.raw_count + ' 条' : '—';

  // 顶部「覆盖源」显示实际采集成功的源数量，而非精选结果里出现的来源数
  const sources = new Set(data.news_sources || []);
  if (!sources.size) {
    (data.news || []).forEach(i => sources.add(i.source));
  }
  document.getElementById('sourceCount').textContent = sources.size || '—';
  document.getElementById('candCount').textContent =
    (data.github_meta && data.github_meta.candidate_count) || '—';

  // 导航徽标：新闻条数 / 当前档位的仓库条数
  document.getElementById('navNewsCount').textContent = (data.news || []).length || '—';
  document.getElementById('navRepoCount').textContent =
    ((data.github && data.github[state.period]) || []).length || '—';

  // 底部脚注：说明增量口径
  const sourcesUsed = (data.github_meta && data.github_meta.sources_used) || [];
  const note = document.getElementById('repoNote');
  const parts = ['增量口径：新建仓库取「当前星数 = 区间增量」（真实值）；老项目在有历史快照后自动切换为快照差分实测值。'];
  if (sourcesUsed.includes('estimate')) {
    parts.push('三日档 GitHub 官方无对应数据，当前按周增量日均外推估算，运行满 3 天后自动切换为实测。');
  }
  note.textContent = parts.join(' ');
}

/* ------------------------------------------------------- 历史：数据层 ---- */

/** 北京时间的「今天」，YYYY-MM-DD。 */
function todayCST() {
  const t = new Date(Date.now() + 8 * 3600 * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return t.getUTCFullYear() + '-' + pad(t.getUTCMonth() + 1) + '-' + pad(t.getUTCDate());
}

/** 'YYYY-MM-DD' → 'YYYY-MM'。 */
function ymOf(date) {
  return String(date || '').slice(0, 7);
}

/**
 * 加载历史索引（哪天有归档）。
 * @returns {Promise<{days: Array, months: Array}>}
 */
async function loadHistoryIndex() {
  try {
    const res = await fetch(HIST_INDEX_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } catch (err) {
    console.warn('fetch 历史索引失败，回退到脚本方式：', err.message);
    return await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = HIST_INDEX_JS;
      s.onload = () => window.__AI_INTEL_HISTORY__
        ? resolve(window.__AI_INTEL_HISTORY__)
        : reject(new Error('历史索引未定义'));
      s.onerror = () => reject(new Error('无法加载 ' + HIST_INDEX_JS));
      document.head.appendChild(s);
    });
  }
}

/**
 * 取某个月的分片数据（按月缓存，只请求一次）。
 * @param {string} ym 'YYYY-MM'
 * @returns {Promise<Object>} { 'YYYY-MM-DD': payload }
 */
async function loadHistoryMonth(ym) {
  const cache = state.hist.cache;
  if (cache[ym]) return cache[ym];
  if (state.hist.loadingMonth === ym) return cache[ym] || {};
  state.hist.loadingMonth = ym;
  try {
    const res = await fetch(HIST_MONTH_URL(ym), { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const obj = await res.json();
    cache[ym] = obj || {};
    return cache[ym];
  } catch (err) {
    console.warn('加载 ' + ym + ' 归档失败：', err.message);
    cache[ym] = {};
    return cache[ym];
  } finally {
    state.hist.loadingMonth = '';
  }
}

/* ------------------------------------------------------- 历史：日历 UI ---- */

const WEEKDAY_NAMES = ['日', '一', '二', '三', '四', '五', '六'];

/** 渲染当前月份的日历网格。 */
function renderCalendar() {
  const grid = document.getElementById('calGrid');
  const title = document.getElementById('calTitle');
  const hist = state.hist;
  const ym = hist.month || ymOf(todayCST());
  const [year, month] = ym.split('-').map(Number);
  if (!year || !month) return;

  title.textContent = year + ' 年 ' + month + ' 月';

  const today = todayCST();
  const first = new Date(Date.UTC(year, month - 1, 1));
  // 以周一为一周起点：JS 的 getUTCDay() 里周日是 0，折算成 0..6 的周一序号
  const lead = (first.getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();

  grid.textContent = '';

  // 上月补位
  const prevMonthDays = new Date(Date.UTC(year, month - 1, 0)).getUTCDate();
  for (let i = lead - 1; i >= 0; i--) {
    const d = prevMonthDays - i;
    const cell = el('span', 'cal-cell blank', d);
    grid.appendChild(cell);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const pad = (n) => String(n).padStart(2, '0');
    const date = year + '-' + pad(month) + '-' + pad(d);
    const has = hist.hashes && hist.hashes.has(date);
    const isToday = date === today;
    const isSel = date === hist.selected;

    let cls = 'cal-cell';
    if (has) cls += ' has';
    if (isToday) cls += ' today';
    if (isSel) cls += ' selected';

    const cell = el(has ? 'button' : 'span', cls, d);
    if (has) {
      cell.type = 'button';
      cell.dataset.date = date;
      const dotCount = (state.hist.index && state.hist.index.days || [])
        .find(x => x.date === date);
      cell.title = date + '（' + (dotCount ? dotCount.news + ' 条情报 · ' + dotCount.repos + ' 个项目' : '有归档') + '）';
      cell.setAttribute('aria-label', cell.title);
    }
    grid.appendChild(cell);
  }

  // 月末补位到整行（7 的倍数），保持网格高度稳定
  const tail = (7 - ((lead + daysInMonth) % 7)) % 7;
  for (let i = 1; i <= tail; i++) {
    grid.appendChild(el('span', 'cal-cell blank', i));
  }

  renderMonthJump();
}

/** 月份快捷跳转按钮（只给有归档的月份）。 */
function renderMonthJump() {
  const box = document.getElementById('monthJump');
  const months = (state.hist.index && state.hist.index.months) || [];
  box.textContent = '';
  months.slice(-6).reverse().forEach(ym => {
    const [y, m] = ym.split('-');
    const btn = el('button', 'month-chip' + (ym === state.hist.month ? ' active' : ''),
      y.slice(2) + '/' + m);
    btn.type = 'button';
    btn.title = y + ' 年 ' + Number(m) + ' 月';
    btn.dataset.ym = ym;
    box.appendChild(btn);
  });
}

/** 切换日历显示的月份，delta 为月份偏移量。 */
function shiftMonth(delta) {
  const ym = state.hist.month || ymOf(todayCST());
  const [y, m] = ym.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  const pad = (n) => String(n).padStart(2, '0');
  state.hist.month = d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1);
  renderCalendar();
  updateCalNavState();
}

/** 首尾月的上/下月按钮置灰。 */
function updateCalNavState() {
  const months = (state.hist.index && state.hist.index.months) || [];
  const ym = state.hist.month;
  const cur = ymOf(todayCST());
  document.getElementById('calPrev').disabled = !months.length || ym <= months[0];
  document.getElementById('calNext').disabled = ym >= (months[months.length - 1] > cur
    ? months[months.length - 1] : cur);
}

/**
 * 选中某一天并渲染右侧内容。
 * @param {string} date 'YYYY-MM-DD'
 */
async function selectDate(date) {
  const hist = state.hist;
  hist.selected = date;
  hist.month = ymOf(date);
  renderCalendar();
  updateCalNavState();

  const grid = document.getElementById('histNewsGrid');
  const table = document.getElementById('histRepoTable');
  const empty = document.getElementById('histEmpty');
  const meta = document.getElementById('histMeta');
  document.getElementById('histDate').textContent = prettyDate(date);
  meta.textContent = '加载中…';

  grid.textContent = '';
  table.textContent = '';
  grid.hidden = hist.mode !== 'news';
  table.hidden = hist.mode !== 'repos';
  empty.hidden = true;

  const month = await loadHistoryMonth(ymOf(date));
  // 期间用户可能又点了别的日期
  if (hist.selected !== date) return;

  const payload = month[date];
  if (!payload) {
    empty.hidden = false;
    grid.hidden = true;
    table.hidden = true;
    meta.textContent = '';
    updateHash(date);
    return;
  }

  const nNews = (payload.news || []).length;
  const nRepos = ((payload.github || {}).three_day || []).length;
  const stats = payload.news_stats || {};
  const bits = [nNews + ' 条情报', nRepos + ' 个开源项目'];
  if (stats.raw_count) bits.push('候选 ' + stats.raw_count + ' 条');
  if (stats.source_total) bits.push('覆盖 ' + stats.source_total + ' 个源');
  if (payload.generated_at_cst) bits.push('生成于 ' + payload.generated_at_cst.slice(11, 16));
  meta.textContent = bits.join(' · ');

  renderHistContent(payload);
  updateHash(date);
}

/** 按当前 mode 渲染历史面板内容。 */
function renderHistContent(payload) {
  const hist = state.hist;
  const grid = document.getElementById('histNewsGrid');
  const table = document.getElementById('histRepoTable');
  const empty = document.getElementById('histEmpty');

  if (!payload) return;
  const isEmpty = (list) => !list || !list.length;
  if (hist.mode === 'news') {
    grid.hidden = false;
    table.hidden = true;
    renderNews(payload.news || [], grid, empty, { archived: true });
    // 当日没有新闻时，别把空态挂在隐藏的开源表格上
    if (isEmpty(payload.news)) {
      grid.hidden = true;
      empty.hidden = false;
      empty.textContent = '这一天的归档里没有情报条目。';
    }
  } else {
    grid.hidden = true;
    table.hidden = false;
    const repos = (payload.github || {}).three_day || [];
    renderRepos(repos, table, empty, { archived: true });
    if (isEmpty(repos)) {
      table.hidden = true;
      empty.hidden = false;
      empty.textContent = '这一天的归档里没有开源项目榜单。';
    }
  }
}

/** 'YYYY-MM-DD' → '2026 年 10 月 29 日 星期四'。 */
function prettyDate(date) {
  if (!date || date.length < 10) return '—';
  const [y, m, d] = date.split('-').map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return y + ' 年 ' + m + ' 月 ' + d + ' 日 · 星期' + WEEKDAY_NAMES[wd];
}

/** 把当前日期同步进 URL（#history/YYYY-MM-DD），便于分享某一天。 */
function updateHash(date) {
  if (state.view !== 'history') return;
  try {
    history.replaceState(null, '', '#history/' + date);
  } catch (_) { /* file:// 下可能受限，忽略 */ }
}

/**
 * 确保历史索引已加载（幂等，并发调用共享同一个请求）。
 * 索引很小（只记录哪天有归档），页面启动时就拉一次，
 * 这样首页导航的徽标不必等用户点进历史视图才有数字。
 */
async function ensureHistoryIndex() {
  const hist = state.hist;
  if (hist.index) return hist.index;
  if (hist.indexPromise) return hist.indexPromise;

  hist.indexPromise = (async () => {
    try {
      const idx = await loadHistoryIndex();
      hist.index = idx;
      hist.hashes = new Set((idx.days || []).map(x => x.date));
      const count = (idx.days || []).length;
      document.getElementById('navHistoryCount').textContent = count || '—';
      document.getElementById('histDays').textContent = count || '0';
    } catch (err) {
      console.error(err);
      hist.index = { days: [], months: [] };
      hist.hashes = new Set();
      document.getElementById('navHistoryCount').textContent = '—';
      document.getElementById('histDays').textContent = '0';
    } finally {
      hist.indexPromise = null;
    }
    return hist.index;
  })();

  return hist.indexPromise;
}

/** 历史视图首次进入时的初始化。 */
async function initHistory() {
  const hist = state.hist;
  await ensureHistoryIndex();

  if (!hist.month) hist.month = ymOf(todayCST());
  renderCalendar();
  updateCalNavState();

  // 默认选中：URL 指定的日期 → 今天（若有归档）→ 最近一个有归档的日期
  let target = hist.selected;
  if (!target) {
    const want = location.hash.startsWith('#history/') ? location.hash.slice(9) : '';
    if (want && hist.hashes.has(want)) target = want;
  }
  if (!target) {
    const today = todayCST();
    target = hist.hashes.has(today) ? today : ((hist.index.days || []).slice(-1)[0] || {}).date;
  }
  if (target) {
    // 已在显示的日期不重复请求，但必须把日历同步到它的月份并补画高亮
    const shown = document.querySelector('.hist-date');
    if (hist.selected === target && shown && shown.textContent !== '—') {
      hist.month = ymOf(target);
      renderCalendar();
      updateCalNavState();
      return;
    }
    hist.selected = '';
    hist.month = ymOf(target);
    await selectDate(target);
  } else {
    document.getElementById('histEmpty').hidden = false;
    document.getElementById('histDate').textContent = '暂无归档';
    document.getElementById('histMeta').textContent = '';
  }
}

/* ------------------------------------------------------------ 视图切换 ---- */

const VIEW_IDS = { news: 'newsSection', repos: 'repoSection', history: 'historySection' };

/** 从 location.hash 解析视图与附带参数。 */
function parseRoute() {
  const hash = location.hash || '';
  if (hash.startsWith('#repos')) return { view: 'repos' };
  if (hash.startsWith('#history')) return { view: 'history', date: hash.slice(9) || '' };
  return { view: 'news' };
}

/**
 * 切换主视图。nav 点击与 URL hash（#news / #repos / #history）都走这里，
 * 保证刷新、分享链接后仍停留在同一视图。
 */
function setView(view, opts) {
  const options = opts || {};
  if (!VIEW_IDS[view]) view = 'news';
  state.view = view;

  Object.keys(VIEW_IDS).forEach(v => {
    const sec = document.getElementById(VIEW_IDS[v]);
    const on = v === view;
    sec.hidden = !on;
    sec.classList.toggle('view', on);
  });

  document.querySelectorAll('#mainNav .nav-item').forEach(btn => {
    const on = btn.dataset.view === view;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });

  if (options.updateHash !== false) {
    const next = view === 'repos' ? '#repos'
      : view === 'history' ? '#history'
        : location.pathname + location.search;
    try {
      history.replaceState(null, '', next);
    } catch (_) { /* file:// 下可能受限，忽略 */ }
  }

  if (!options.keepScroll) window.scrollTo({ top: 0, behavior: 'smooth' });
}

function initNav() {
  const nav = document.getElementById('mainNav');
  nav.addEventListener('click', (e) => {
    const btn = e.target.closest('.nav-item');
    if (!btn) return;
    setView(btn.dataset.view);
    if (btn.dataset.view === 'history') initHistory();
  });

  // 键盘左右箭头在各项间切换（role="tablist" 的无障碍惯例）
  nav.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const items = Array.from(nav.querySelectorAll('.nav-item'));
    const idx = items.indexOf(document.activeElement);
    if (idx < 0) return;
    e.preventDefault();
    const next = items[(idx + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length];
    next.focus();
    setView(next.dataset.view);
    if (next.dataset.view === 'history') initHistory();
  });

  // 支持浏览器前进/后退与直接带 hash 打开
  window.addEventListener('hashchange', () => {
    const route = parseRoute();
    setView(route.view, { updateHash: false });
    if (route.view === 'history') {
      if (route.date && route.date !== state.hist.selected) {
        state.hist.selected = '';
        initHistory();
      } else {
        initHistory();
      }
    }
  });

  const route = parseRoute();
  setView(route.view, { updateHash: false });
  if (route.view === 'history') {
    state.hist.selected = route.date && /^\d{4}-\d{2}-\d{2}$/.test(route.date) ? route.date : '';
    initHistory();
  }
}

/* -------------------------------------------------------------- 主流程 ---- */

async function refresh() {
  const btn = document.getElementById('refreshBtn');
  btn.classList.add('loading');
  try {
    const data = await loadData();
    state.data = data;
    renderHeader(data);
    renderNews(data.news, document.getElementById('newsGrid'), document.getElementById('newsEmpty'));
    renderRepos(data.github[state.period], document.getElementById('repoTable'),
      document.getElementById('repoEmpty'));
  } catch (err) {
    console.error(err);
    document.getElementById('newsGrid').textContent = '';
    document.getElementById('newsEmpty').hidden = false;
    document.getElementById('newsEmpty').textContent =
      '数据加载失败：' + err.message + '（本地预览请用 python -m http.server 启动后访问）';
  } finally {
    btn.classList.remove('loading');
  }
}

function initTabs() {
  const tabs = document.getElementById('repoTabs');
  tabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    tabs.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    state.period = btn.dataset.period;
    if (state.data) {
      const repos = state.data.github[state.period] || [];
      document.getElementById('navRepoCount').textContent = repos.length || '—';
      renderRepos(repos, document.getElementById('repoTable'),
        document.getElementById('repoEmpty'));
    }
  });
}

document.getElementById('refreshBtn').addEventListener('click', refresh);

/* ------------------------------------------------ 日历：交互事件绑定 ---- */

/** 绑定日历与历史面板上的所有点击。 */
function initCalendarEvents() {
  document.getElementById('calPrev').addEventListener('click', () => shiftMonth(-1));
  document.getElementById('calNext').addEventListener('click', () => shiftMonth(1));

  document.getElementById('calGrid').addEventListener('click', (e) => {
    const cell = e.target.closest('.cal-cell.has');
    if (!cell || !cell.dataset.date) return;
    selectDate(cell.dataset.date);
  });

  document.getElementById('monthJump').addEventListener('click', (e) => {
    const btn = e.target.closest('.month-chip');
    if (!btn) return;
    state.hist.month = btn.dataset.ym;
    renderCalendar();
    updateCalNavState();
  });

  // 回到今天：若今天没有归档，则跳到最近一个有归档的日期
  document.getElementById('calToday').addEventListener('click', () => {
    const today = todayCST();
    const hashes = state.hist.hashes || new Set();
    if (hashes.has(today)) {
      selectDate(today);
      return;
    }
    const last = ((state.hist.index && state.hist.index.days) || []).slice(-1)[0];
    if (last) selectDate(last.date);
  });

  // 历史面板的「情报 / 开源项目」切换
  const modeTabs = document.getElementById('histModeTabs');
  modeTabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    modeTabs.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    state.hist.mode = btn.dataset.hist;
    const ym = ymOf(state.hist.selected);
    const payload = (state.hist.cache[ym] || {})[state.hist.selected];
    if (payload) renderHistContent(payload);
  });

  // 日历键盘操作：方向键移动高亮日（仅在有归档的日期间跳转）
  document.getElementById('calendar').addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault();
    const dates = (state.hist.index && state.hist.index.days || []).map(x => x.date);
    if (!dates.length) return;
    const i = dates.indexOf(state.hist.selected);
    const step = (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 1;
    let next = i < 0 ? dates.length - 1 : i + step;
    next = Math.max(0, Math.min(dates.length - 1, next));
    selectDate(dates[next]);
  });
}

initCalendarEvents();
initNav();
initTabs();
refresh();
// 索引很小，启动时就拉一次，让导航的归档天数徽标立刻有数字
ensureHistoryIndex();
