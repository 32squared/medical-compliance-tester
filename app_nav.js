/* 공통 상단 메뉴 — 모든 화면이 <nav id="appNav"></nav> + <script src="/app_nav.js"></script> 로 쓴다.
 * 메뉴 구성·권한·활성 표시는 여기 한 곳에서만 관리한다. 접근 통제 자체는 서버가 한다(표시 여부만 결정). */
(function () {
  'use strict';

  // 권한 표기: null=누구나, 'auth'=로그인 필요, 'admin'=관리자 전용,
  // 'a|b'=둘 중 하나, 그 외=권한 코드
  var MENUS = [
    { id: 'chat', label: '대화 테스트', segmented: true, items: [
      { label: '채팅 테스터', tab: '단일 대화', href: '/', perm: null },
      { label: 'Arena', tab: 'A·B 비교', href: '/arena', perm: 'use_arena' }
    ] },
    { id: 'scenario', label: '시나리오', items: [
      { label: '시나리오 관리', tab: '시나리오', href: '/manager', perm: 'manage_scenarios' },
      { label: 'HealthBench', href: '/healthbench', perm: 'view_history|run_batch' },
      { label: 'PHR 케이스', href: '/phr', perm: 'admin' }
    ] },
    { id: 'result', label: '결과', items: [
      { label: '테스트 이력', href: '/history', perm: 'view_history' },
      { label: '정답지 검토', href: '/review', perm: 'view_history' },
      { label: '등급별 질답', href: '/grades', perm: 'view_history' },
      { label: '자문 판정', href: '/advisory', perm: 'admin' }
    ] },
    { id: 'eval', label: '평가', items: [
      { label: '문진 평가 기준', href: '/criteria', perm: 'view_criteria|manage_criteria' },
      { label: '외부 답변 평가', href: '/external-eval', perm: 'auth' }
    ] },
    { id: 'admin', label: '⚙ 관리', gear: true, items: [
      { label: '설정', href: '/settings', perm: 'admin' },
      { label: 'RLHF 관리', href: '/rlhf', perm: 'manage_rlhf' },
      { label: 'KB 관리', href: '/kb_manager', perm: 'manage_kb' },
      { label: '검색 API 점검', href: '/admin/search-probe', perm: 'admin' }
    ] }
  ];

  // 현재 경로 → 활성 메뉴 항목 href (별칭 포함)
  var ALIASES = {
    '/chat_tester.html': '/',
    '/index.html': '/',
    '/chat_arena.html': '/arena',
    '/scenario_manager.html': '/manager',
    '/history.html': '/history',
    '/eval_v3.html': '/history',
    '/eval-v3': '/history',
    '/review.html': '/review',
    '/grade_viewer.html': '/grades',
    '/healthbench.html': '/healthbench',
    '/hb_about.html': '/healthbench',
    '/hb_scenario_detail.html': '/healthbench',
    '/criteria_manager.html': '/criteria',
    '/external_eval.html': '/external-eval',
    '/rlhf_manager.html': '/rlhf',
    '/kb_manager.html': '/kb_manager',
    '/settings.html': '/settings',
    '/phr_manager.html': '/phr',
    '/advisory_viewer.html': '/advisory',
    '/search_probe.html': '/admin/search-probe'
  };

  function activeHref(pathname) {
    var raw = pathname !== undefined ? pathname : (window.location.pathname || '/');
    var p = String(raw).replace(/\/+$/, '') || '/';
    if (ALIASES[p]) return ALIASES[p];
    if (p === '/healthbench' || p.indexOf('/healthbench/') === 0) return '/healthbench';
    if (p.indexOf('/hb_') === 0) return '/healthbench';
    return p;
  }

  var CSS = [
    '.appnav{--an-surface:#1e293b;--an-surface2:#334155;--an-accent:#38bdf8;--an-accent-dim:#0c4a6e;--an-border:#475569;--an-text:#e2e8f0;--an-text-dim:#94a3b8;display:flex;align-items:center;gap:8px;flex:1 1 auto;min-width:0;position:relative}',
    '.appnav-gear{margin-left:auto}',
    '.appnav-grp{position:relative;display:inline-flex}',
    '.appnav-btn{background:none;border:1px solid var(--an-border);color:var(--an-text-dim);border-radius:8px;',
    'padding:6px 14px;font-size:12px;cursor:pointer;text-decoration:none;white-space:nowrap;',
    'font-family:inherit;display:inline-flex;align-items:center;gap:6px;line-height:1.4}',
    '.appnav-btn:hover,.appnav-btn:focus-visible{background:var(--an-surface2);color:var(--an-text)}',
    '.appnav-btn:focus-visible{outline:2px solid var(--an-accent);outline-offset:1px}',
    '.appnav-btn.active{background:var(--an-accent-dim);border-color:var(--an-accent);color:var(--an-accent)}',
    '.appnav-caret{font-size:9px;opacity:.8}',
    '.appnav-menu{position:absolute;top:calc(100% + 4px);left:0;min-width:170px;z-index:1000;',
    'background:var(--an-surface);border:1px solid var(--an-border);border-radius:8px;padding:4px;',
    'box-shadow:0 8px 24px rgba(0,0,0,.4);display:none;flex-direction:column;gap:2px}',
    '.appnav-grp.open>.appnav-menu{display:flex}',
    '.appnav-gear .appnav-menu{left:auto;right:0}',
    '.appnav-item{display:block;color:var(--an-text-dim);text-decoration:none;font-size:12px;',
    'padding:7px 12px;border-radius:6px;white-space:nowrap}',
    '.appnav-item:hover,.appnav-item:focus-visible{background:var(--an-surface2);color:var(--an-text);outline:none}',
    '.appnav-item.active{background:var(--an-accent-dim);color:var(--an-accent)}',
    '.appnav-tabs{--an-bg:#0f172a;--an-surface:#1e293b;--an-surface2:#334155;--an-accent:#38bdf8;--an-accent-dim:#0c4a6e;--an-border:#475569;--an-text:#e2e8f0;--an-text-dim:#94a3b8;',
    'display:flex;align-items:stretch;gap:2px;flex:0 0 auto;flex-shrink:0;width:100%;box-sizing:border-box;padding:0 20px;',
    'background:var(--an-bg);border-bottom:1px solid var(--an-border);overflow-x:auto;overflow-y:hidden}',
    '.appnav-tabs-tab{display:inline-flex;align-items:center;min-height:36px;padding:0 16px;font-size:13px;line-height:1.4;',
    'color:var(--an-text-dim);text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;margin-bottom:-1px;box-sizing:border-box}',
    '.appnav-tabs-tab:hover,.appnav-tabs-tab:focus-visible{color:var(--an-text);background:var(--an-surface)}',
    '.appnav-tabs-tab:focus-visible{outline:2px solid var(--an-accent);outline-offset:-2px}',
    '.appnav-tabs-tab.active{color:var(--an-accent);border-bottom-color:var(--an-accent);font-weight:600}',
    '.appnav-tabs.seg{justify-content:center;padding:6px 20px}',
    '.appnav-tabs.seg .appnav-tabs-seg{display:inline-flex;gap:0;border:1px solid var(--an-border);border-radius:8px;overflow:hidden;background:var(--an-surface)}',
    '.appnav-tabs.seg .appnav-tabs-tab{border-bottom:0;margin:0;padding:0 22px;border-radius:0}',
    '.appnav-tabs.seg .appnav-tabs-tab+.appnav-tabs-tab{border-left:1px solid var(--an-border)}',
    '.appnav-tabs.seg .appnav-tabs-tab.active{background:var(--an-accent-dim)}'
  ].join('');

  function injectStyle() {
    if (document.getElementById('appNavStyle')) return;
    var st = document.createElement('style');
    st.id = 'appNavStyle';
    st.textContent = CSS;
    (document.head || document.documentElement).appendChild(st);
  }

  function makeAllow(auth) {
    var perms = (auth && auth.permissions) || [];
    var isAdmin = !!(auth && auth.isAdmin);
    var loggedIn = isAdmin || !!(auth && auth.tester);
    var all = isAdmin || perms.indexOf('*') >= 0;
    return function (perm) {
      if (perm === null || perm === undefined) return true;
      if (isAdmin) return true;
      if (perm === 'admin') return false;
      if (perm === 'auth') return loggedIn;
      if (all) return true;
      var alts = String(perm).split('|');
      for (var i = 0; i < alts.length; i++) {
        if (perms.indexOf(alts[i]) >= 0) return true;
      }
      return false;
    };
  }

  function visibleMenus(auth) {
    var role = (auth && (auth.userRole || (auth.tester && auth.tester.role))) || '';
    var isAdmin = !!(auth && auth.isAdmin);
    var allow = makeAllow(auth);
    var out = [];
    MENUS.forEach(function (m) {
      var items = m.items.filter(function (it) {
        if (!isAdmin && role === 'advisor') return it.href === '/';
        return allow(it.perm);
      });
      if (items.length) out.push({ id: m.id, label: m.label, gear: m.gear, segmented: m.segmented, items: items });
    });
    return out;
  }

  // 현재 경로가 속한 그룹의 섹션 탭. 보이는 항목이 2개 미만이거나 어느 그룹에도 속하지 않으면 null
  function sectionFor(pathname, menus) {
    var active = activeHref(pathname);
    for (var i = 0; i < (menus || []).length; i++) {
      var m = menus[i];
      var cur = m.items.filter(function (it) { return it.href === active; })[0];
      if (!cur) continue;
      if (m.items.length < 2) return null;
      return {
        id: m.id, segmented: !!m.segmented, active: active,
        tabs: m.items.map(function (it) { return { label: it.tab || it.label, href: it.href, active: it.href === active }; })
      };
    }
    return null;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  var openGroups = [];

  function closeAll(except) {
    openGroups.forEach(function (g) {
      if (g.grp === except) return;
      g.grp.classList.remove('open');
      g.btn.setAttribute('aria-expanded', 'false');
    });
  }

  function render(host, auth) {
    var menus = visibleMenus(auth);
    var active = activeHref();
    host.textContent = '';
    host.classList.add('appnav');
    host.setAttribute('aria-label', '주 메뉴');
    openGroups = [];

    menus.forEach(function (m) {
      var hasActive = m.items.some(function (it) { return it.href === active; });

      if (m.items.length === 1 && !m.gear) {
        var it = m.items[0];
        var a = el('a', 'appnav-btn' + (it.href === active ? ' active' : ''), it.label);
        a.href = it.href;
        if (it.href === active) a.setAttribute('aria-current', 'page');
        host.appendChild(a);
        return;
      }

      var grp = el('div', 'appnav-grp' + (m.gear ? ' appnav-gear' : ''));
      var btn = el('button', 'appnav-btn' + (hasActive ? ' active' : ''));
      btn.type = 'button';
      btn.setAttribute('aria-haspopup', 'true');
      btn.setAttribute('aria-expanded', 'false');
      if (m.gear) btn.setAttribute('title', '관리');
      btn.appendChild(document.createTextNode(m.label + ' '));
      btn.appendChild(el('span', 'appnav-caret', '▾'));
      var menu = el('div', 'appnav-menu');
      menu.setAttribute('role', 'menu');
      m.items.forEach(function (it) {
        var a = el('a', 'appnav-item' + (it.href === active ? ' active' : ''), it.label);
        a.href = it.href;
        a.setAttribute('role', 'menuitem');
        if (it.href === active) a.setAttribute('aria-current', 'page');
        menu.appendChild(a);
      });
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var willOpen = !grp.classList.contains('open');
        closeAll(grp);
        grp.classList.toggle('open', willOpen);
        btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        if (willOpen) {
          var first = menu.querySelector('a');
          if (first && ev.detail === 0) first.focus();   // 키보드로 연 경우만 첫 항목으로
        }
      });
      grp.appendChild(btn);
      grp.appendChild(menu);
      host.appendChild(grp);
      openGroups.push({ grp: grp, btn: btn });
    });
  }

  function findTopBar(nav) {
    var n = nav;
    while (n && n.parentNode && n.parentNode !== document.body) {
      var c = n.parentNode;
      var cls = ' ' + (c.className || '') + ' ';
      if (c.tagName === 'HEADER' || cls.indexOf(' topbar ') >= 0 || cls.indexOf(' top-nav ') >= 0 || cls.indexOf(' app-header ') >= 0) return c;
      n = c;
    }
    return null;
  }

  function renderSectionTabs(nav, auth) {
    var old = document.querySelector('.appnav-tabs');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var sec = sectionFor(window.location.pathname, visibleMenus(auth));
    var slot = document.getElementById('appSectionTabs');
    if (!sec) { if (slot) slot.textContent = ''; return; }
    var bar = slot || el('div');
    bar.textContent = '';
    bar.className = 'appnav-tabs' + (sec.segmented ? ' seg' : '');
    bar.setAttribute('role', 'navigation');
    bar.setAttribute('aria-label', '섹션 탭');
    var wrap = sec.segmented ? el('div', 'appnav-tabs-seg') : bar;
    sec.tabs.forEach(function (t) {
      var a = el('a', 'appnav-tabs-tab' + (t.active ? ' active' : ''), t.label);
      a.href = t.href;
      if (t.active) a.setAttribute('aria-current', 'page');
      wrap.appendChild(a);
    });
    if (wrap !== bar) bar.appendChild(wrap);
    if (!slot) {
      var top = findTopBar(nav) || nav;
      if (top && top.parentNode) top.parentNode.insertBefore(bar, top.nextSibling);
    }
  }

  var bound = false;
  function bindGlobal() {
    if (bound) return;
    bound = true;
    document.addEventListener('click', function (ev) {
      openGroups.forEach(function (g) {
        if (!g.grp.contains(ev.target)) {
          g.grp.classList.remove('open');
          g.btn.setAttribute('aria-expanded', 'false');
        }
      });
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape' && ev.key !== 'Esc') return;
      openGroups.forEach(function (g) {
        if (g.grp.classList.contains('open')) {
          g.grp.classList.remove('open');
          g.btn.setAttribute('aria-expanded', 'false');
          if (g.grp.contains(document.activeElement)) g.btn.focus();
        }
      });
    });
  }

  function fetchAuth() {
    var base = '';
    try {
      if (typeof window.getProxyUrl === 'function') base = window.getProxyUrl() || '';
    } catch (e) { base = ''; }
    if (!base) base = window.location.origin;
    return fetch(base + '/api/auth/status', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  function init() {
    injectStyle();
    bindGlobal();
    var host = document.getElementById('appNav');
    // 인증 응답 전에도 기본 메뉴(채팅 테스터만)가 깜빡이지 않도록 응답 후에 그린다
    fetchAuth().then(function (auth) {
      if (host) { render(host, auth); renderSectionTabs(host, auth); }
      resolveReady(auth);
    });
  }

  var resolveReady;
  window.AppNav = {
    ready: new Promise(function (res) { resolveReady = res; }),
    _visibleMenus: visibleMenus,
    _sectionFor: sectionFor
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
