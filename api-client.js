/* ==========================================================================
   AI 情报站 · 阿里云 API 前端调用层（可选功能，默认关闭）

   ⚠️ 唯一需要改的地方在下面 CONFIG.API_BASE。
      留空   → 本文件不注入任何 DOM、不发任何请求，页面与纯静态版完全一致。
      填地址 → 右上角出现「账户」按钮，新闻卡片出现收藏星标，可注册/登录/查询收藏。

   填法（三选一，优先级从高到低）：
     1. 部署前改本文件 CONFIG.API_BASE，然后重新发布（正式做法）
     2. 浏览器控制台执行，刷新即生效（临时调试，无需重新发布）：
          localStorage.setItem('aiIntelApiBase', 'https://api.你的域名')
     3. 在 index.html 引入本文件前设置 window.AI_INTEL_API_BASE = 'https://...'

   地址要求：https 开头、不带尾斜杠、域名已备案、证书有效、nginx 已配 CORS 白名单。
   若页面是 https 而 API 是 http，浏览器会按 Mixed Content 直接拦掉。

   后端契约见 aliyun-api/server.py；不依赖任何第三方库，也不修改 app.js。
   所有用户输入的展示一律用 textContent，不拼 innerHTML。
   ========================================================================== */

(function () {
  'use strict';

  const CONFIG = {
    API_BASE: '',                 // ← 例：'https://api.example.com'
    TOKEN_KEY: 'aiIntelToken',
    BASE_KEY: 'aiIntelApiBase',
  };

  const base = (window.AI_INTEL_API_BASE ||
                (function () { try { return localStorage.getItem(CONFIG.BASE_KEY); } catch (_) { return ''; } })() ||
                CONFIG.API_BASE || '').replace(/\/+$/, '');

  // 未配置 API 地址：彻底静默退出，保证现有静态站零改动
  if (!base) return;

  /* ------------------------------------------------------------ 样式 ---- */
  const css = `
.aiapi-btn{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border:1px solid var(--line,#e2e5ea);
  border-radius:8px;background:var(--surface,#fff);color:inherit;font:inherit;font-size:13px;cursor:pointer}
.aiapi-btn:hover{border-color:#4f7cff}
.aiapi-account{margin-left:12px}
.aiapi-mask{position:fixed;inset:0;background:rgba(20,24,32,.42);z-index:9000;display:none}
.aiapi-mask.open{display:block}
.aiapi-panel{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:min(420px,calc(100vw - 32px));
  max-height:min(620px,calc(100vh - 40px));overflow:auto;background:#fff;color:#1f2329;border-radius:14px;
  box-shadow:0 12px 40px rgba(0,0,0,.18);z-index:9001;padding:20px;display:none;font-family:inherit}
.aiapi-panel.open{display:block}
.aiapi-panel h2{margin:0 0 4px;font-size:17px;font-weight:600}
.aiapi-sub{margin:0 0 16px;font-size:12px;color:#8a9099;line-height:1.6}
.aiapi-tabs{display:flex;gap:6px;margin-bottom:16px;border-bottom:1px solid #eceff3}
.aiapi-tab{padding:8px 12px;border:0;background:none;font:inherit;font-size:13px;color:#6b7280;cursor:pointer;
  border-bottom:2px solid transparent}
.aiapi-tab.active{color:#1f2329;border-bottom-color:#4f7cff}
.aiapi-field{margin-bottom:12px}
.aiapi-field label{display:block;font-size:12px;color:#6b7280;margin-bottom:5px}
.aiapi-field input{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid #dfe3e8;border-radius:8px;
  font:inherit;font-size:14px;outline:none}
.aiapi-field input:focus{border-color:#4f7cff}
.aiapi-primary{width:100%;padding:10px;border:0;border-radius:8px;background:#4f7cff;color:#fff;
  font:inherit;font-size:14px;cursor:pointer}
.aiapi-primary:disabled{opacity:.55;cursor:default}
.aiapi-msg{margin-top:10px;font-size:12px;line-height:1.6;min-height:18px}
.aiapi-msg.err{color:#c0392b}.aiapi-msg.ok{color:#1a7f4b}
.aiapi-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 0;
  border-bottom:1px solid #f0f2f5;font-size:13px}
.aiapi-row:last-child{border-bottom:0}
.aiapi-row a{color:#2f5fd0;text-decoration:none;flex:1;min-width:0;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.aiapi-mini{padding:4px 9px;border:1px solid #e2e5ea;background:#fff;border-radius:6px;
  font:inherit;font-size:12px;cursor:pointer;color:#6b7280}
.aiapi-user{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;
  padding:10px 12px;background:#f6f8fb;border-radius:8px;font-size:13px}
.aiapi-star{margin-left:6px;padding:0 6px;border:0;background:none;cursor:pointer;font-size:14px;
  color:#c8ccd2;line-height:1}
.aiapi-star.on{color:#f0a020}
.aiapi-empty{font-size:13px;color:#8a9099;text-align:center;padding:24px 0}
.aiapi-hint{margin-top:14px;padding:10px;background:#fff8e6;border-radius:8px;font-size:11.5px;
  color:#8a6d3b;line-height:1.6}
@media(max-width:640px){.aiapi-account{margin-left:0;margin-top:10px}}
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  /* ------------------------------------------------------------ 请求 ---- */
  function token() {
    try { return localStorage.getItem(CONFIG.TOKEN_KEY) || ''; } catch (_) { return ''; }
  }
  function setToken(t) {
    try { t ? localStorage.setItem(CONFIG.TOKEN_KEY, t) : localStorage.removeItem(CONFIG.TOKEN_KEY); } catch (_) {}
  }

  async function request(method, path, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (token()) headers.Authorization = 'Bearer ' + token();
    let res;
    try {
      res = await fetch(base + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
      });
    } catch (err) {
      // fetch 抛错几乎总是 HTTPS/CORS/备案/证书/DNS 问题，给出可排查的提示
      throw new Error('无法连接 API：请确认地址是 https、证书有效、域名已备案、nginx 已放行本页 Origin。(' + err.message + ')');
    }
    let data;
    try { data = await res.json(); } catch (_) { throw new Error('API 返回了非 JSON 内容（HTTP ' + res.status + '）'); }
    if (!res.ok || data.ok === false) {
      throw new Error(data.message || data.error || ('HTTP ' + res.status));
    }
    return data.data;
  }

  const api = {
    health:        () => request('GET', '/api/health'),
    register:      (u, p) => request('POST', '/api/register', { username: u, password: p }),
    login:         (u, p) => request('POST', '/api/login', { username: u, password: p }),
    me:            () => request('GET', '/api/me'),
    bookmarks:     () => request('GET', '/api/bookmarks'),
    addBookmark:   (item) => request('POST', '/api/bookmarks', item),
    delBookmark:   (id) => request('DELETE', '/api/bookmarks?id=' + encodeURIComponent(id)),
    query:         (q, date) => request('GET', '/api/query?q=' + encodeURIComponent(q || '') +
                                        '&date=' + encodeURIComponent(date || '')),
  };
  window.AIIntelAPI = api;   // 方便在控制台里直接调

  /* ------------------------------------------------------------ 工具 ---- */
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  /* ------------------------------------------------------------ UI ---- */
  const mask = el('div', 'aiapi-mask');
  const panel = el('div', 'aiapi-panel');
  document.body.appendChild(mask);
  document.body.appendChild(panel);
  mask.addEventListener('click', closePanel);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePanel(); });

  const state = { user: null, bookmarks: [], tab: 'login' };
  let msgEl = null;

  function setMsg(text, kind) {
    if (!msgEl) return;
    msgEl.textContent = text || '';
    msgEl.className = 'aiapi-msg' + (kind ? ' ' + kind : '');
  }

  function closePanel() { mask.classList.remove('open'); panel.classList.remove('open'); }
  function openPanel() { mask.classList.add('open'); panel.classList.add('open'); renderPanel(); }

  function renderPanel() {
    panel.textContent = '';
    panel.appendChild(el('h2', null, 'AI 情报站 · 账户'));
    panel.appendChild(el('p', 'aiapi-sub', '数据保存在你自己的阿里云主机，与情报站静态内容相互独立。'));

    if (state.user) {
      const bar = el('div', 'aiapi-user');
      bar.appendChild(el('span', null, '已登录：' + state.user.username));
      const out = el('button', 'aiapi-mini', '退出');
      out.addEventListener('click', () => {
        setToken(''); state.user = null; state.bookmarks = [];
        syncStars(); renderPanel(); renderAccountBtn();
      });
      bar.appendChild(out);
      panel.appendChild(bar);
      renderBookmarks();
    } else {
      const tabs = el('div', 'aiapi-tabs');
      [['login', '登录'], ['register', '注册']].forEach(([key, label]) => {
        const b = el('button', 'aiapi-tab' + (state.tab === key ? ' active' : ''), label);
        b.addEventListener('click', () => { state.tab = key; renderPanel(); });
        tabs.appendChild(b);
      });
      panel.appendChild(tabs);
      renderAuthForm();
    }

    msgEl = el('div', 'aiapi-msg');
    panel.appendChild(msgEl);
    panel.appendChild(el('div', 'aiapi-hint',
      '若报「无法连接 API」：检查 API 域名是否 https、证书是否有效、大陆域名是否完成 ICP 备案、' +
      'nginx 的 CORS 白名单是否包含 ' + location.origin + '。'));
  }

  function renderAuthForm() {
    const isReg = state.tab === 'register';
    const wrap = el('div');
    const fUser = el('div', 'aiapi-field');
    const labU = el('label', null, '用户名');
    const inpU = el('input'); inpU.type = 'text'; inpU.autocomplete = 'username';
    inpU.placeholder = '2-32 位中英文 / 数字 / 下划线';
    labU.appendChild(inpU); fUser.appendChild(labU); wrap.appendChild(fUser);

    const fPwd = el('div', 'aiapi-field');
    const labP = el('label', null, '密码');
    const inpP = el('input'); inpP.type = 'password';
    inpP.autocomplete = isReg ? 'new-password' : 'current-password';
    inpP.placeholder = isReg ? '至少 8 位' : '输入密码';
    labP.appendChild(inpP); fPwd.appendChild(labP); wrap.appendChild(fPwd);

    const btn = el('button', 'aiapi-primary', isReg ? '注册并登录' : '登录');
    btn.addEventListener('click', async () => {
      if (!inpU.value.trim() || !inpP.value) { setMsg('请填写用户名和密码', 'err'); return; }
      btn.disabled = true; setMsg('正在连接 API…', '');
      try {
        const data = isReg ? await api.register(inpU.value.trim(), inpP.value)
                           : await api.login(inpU.value.trim(), inpP.value);
        setToken(data.token);
        state.user = data.user;
        await loadBookmarks();
        setMsg(isReg ? '注册成功' : '登录成功', 'ok');
        renderAccountBtn(); syncStars();
        setTimeout(renderPanel, 300);
      } catch (err) {
        setMsg(err.message, 'err');
      } finally {
        btn.disabled = false;
      }
    });
    inpP.addEventListener('keydown', (e) => { if (e.key === 'Enter') btn.click(); });
    wrap.appendChild(btn);
    panel.insertBefore(wrap, msgEl || null);
  }

  async function loadBookmarks() {
    if (!token()) return;
    try { state.bookmarks = (await api.bookmarks()).items || []; }
    catch (_) { state.bookmarks = []; }
  }

  function renderBookmarks() {
    const box = el('div');
    const search = el('div', 'aiapi-field');
    const lab = el('label', null, '查询我的收藏（按标题 / 来源 / 日期）');
    const inp = el('input'); inp.type = 'search'; inp.placeholder = '输入关键词后回车，如 agent';
    lab.appendChild(inp); search.appendChild(lab); box.appendChild(search);

    const list = el('div');
    function paint(items) {
      list.textContent = '';
      if (!items.length) { list.appendChild(el('div', 'aiapi-empty', '暂无收藏')); return; }
      items.forEach((it) => {
        const row = el('div', 'aiapi-row');
        const a = el('a', null, it.title || it.item_url);
        a.href = it.item_url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        row.appendChild(a);
        row.appendChild(el('span', 'aiapi-mini', it.source || it.item_date || ''));
        const del = el('button', 'aiapi-mini', '删除');
        del.addEventListener('click', async () => {
          try {
            await api.delBookmark(it.id);
            state.bookmarks = state.bookmarks.filter(x => x.id !== it.id);
            syncStars(); paint(state.bookmarks);
          } catch (err) { setMsg(err.message, 'err'); }
        });
        row.appendChild(del);
        list.appendChild(row);
      });
    }
    inp.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      try { paint((await api.query(inp.value.trim())).items || []); }
      catch (err) { setMsg(err.message, 'err'); }
    });
    paint(state.bookmarks);
    box.appendChild(list);
    panel.insertBefore(box, msgEl || null);
  }

  function renderAccountBtn() {
    let btn = document.getElementById('aiapiAccountBtn');
    if (!btn) {
      const host = document.querySelector('.header-inner') || document.body;
      btn = el('button', 'aiapi-btn aiapi-account');
      btn.id = 'aiapiAccountBtn';
      btn.type = 'button';
      btn.addEventListener('click', openPanel);
      host.appendChild(btn);
    }
    btn.textContent = state.user ? '账户 · ' + state.user.username : '登录 / 注册';
  }

  /* ------------------------------------------------ 新闻卡片收藏星标 ---- */
  function cardInfo(card) {
    const link = card.querySelector('.news-title a');
    if (!link) return null;
    const chip = card.querySelector('.source-chip');
    const dateEl = card.querySelector('.hist-date');
    return {
      item_url: link.href,
      title: (link.textContent || '').trim(),
      source: chip ? chip.textContent.trim() : '',
      item_date: /^\d{4}-\d{2}-\d{2}/.test(dateEl ? dateEl.textContent : '')
        ? (dateEl.textContent.trim().slice(0, 10).replace(/\s/g, ''))
        : '',
      kind: 'news',
    };
  }

  function syncStars() {
    const urls = new Set(state.bookmarks.map(x => x.item_url));
    document.querySelectorAll('.aiapi-star').forEach((star) => {
      star.classList.toggle('on', urls.has(star.dataset.url));
      star.title = urls.has(star.dataset.url) ? '已收藏，点击取消' : '收藏这条情报';
    });
  }

  function mountStars(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('.news-card').forEach((card) => {
      if (card.dataset.aiapiMounted) return;
      const info = cardInfo(card);
      if (!info) return;
      card.dataset.aiapiMounted = '1';
      const top = card.querySelector('.card-top');
      if (!top) return;
      const star = el('button', 'aiapi-star', '☆');
      star.type = 'button';
      star.dataset.url = info.item_url;
      star.title = '收藏这条情报';
      star.addEventListener('click', async () => {
        if (!token()) { openPanel(); setMsg('请先登录后再收藏', 'err'); return; }
        const existing = state.bookmarks.find(x => x.item_url === info.item_url);
        try {
          if (existing) {
            await api.delBookmark(existing.id);
            state.bookmarks = state.bookmarks.filter(x => x.id !== existing.id);
          } else {
            const r = await api.addBookmark(info);
            state.bookmarks.unshift({ id: r.id, item_url: info.item_url, title: info.title,
                                      source: info.source, item_date: info.item_date });
          }
          syncStars();
        } catch (err) { setMsg(err.message, 'err'); openPanel(); }
      });
      top.appendChild(star);
    });
    syncStars();
  }

  // app.js 会在切视图/刷新时重建卡片，用 MutationObserver 覆盖新增节点，
  // 这样不需要改动 app.js 一行代码。
  const observer = new MutationObserver((records) => {
    records.forEach((r) => {
      r.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.classList && n.classList.contains('news-card')) mountStars(n.parentNode || document);
        else if (n.querySelectorAll) mountStars(n);
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
  mountStars(document);

  /* ------------------------------------------------------------ 启动 ---- */
  renderAccountBtn();
  if (token()) {
    api.me().then((d) => { state.user = d.user; renderAccountBtn(); return loadBookmarks(); })
           .then(syncStars)
           .catch(() => { setToken(''); });   // token 过期/失效，静默退出登录态
  }
})();
