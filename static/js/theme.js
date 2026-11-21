/* New look, stage 1: theme switch, current-page highlight and phone tab bar.
   Visual only: reads links that base.html already shows or hides by role. */
(function () {
    var KEY = 'sts_theme';
    var root = document.documentElement;
    function current() { return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
    function apply(t) {
        root.setAttribute('data-theme', t);
        var m = document.querySelector('meta[name="theme-color"]');
        if (m) m.setAttribute('content', t === 'light' ? '#F3F5F7' : '#12151B');
        var b = document.getElementById('themeSwitch');
        if (b) {
            b.setAttribute('aria-pressed', t === 'light' ? 'true' : 'false');
            b.setAttribute('aria-label', t === 'light' ? 'Light look is on. Switch to dark look' : 'Dark look is on. Switch to light look');
        }
    }
    window.stsSetTheme = function (t) {
        t = (t === 'light') ? 'light' : 'dark';
        try { localStorage.setItem(KEY, t); } catch (e) {}
        apply(t);
    };
    apply(current());
    var sw = document.getElementById('themeSwitch');
    if (sw) sw.addEventListener('click', function () { window.stsSetTheme(current() === 'light' ? 'dark' : 'light'); });

    var path = window.location.pathname.replace(/\/+$/, '') || '/';
    function isCurrent(href) {
        if (!href) return false;
        if (href === path) return true;
        if (href === '/jobs' && /^\/jobs\/\d+/.test(path)) return true;
        return false;
    }
    document.querySelectorAll('.nav-scroll a').forEach(function (a) {
        if (isCurrent(a.getAttribute('href'))) a.classList.add('is-current');
    });

    var ICONS = {
        '/dashboard': '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
        '/supplier': '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
        '/jobs': '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/></svg>',
        '/locations': '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>',
        '/stock': '<svg viewBox="0 0 24 24"><path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/></svg>',
        '/yard': '<svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8l2 2 4-4"/><path d="M8 15h8"/></svg>',
        '/jobs/create': '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>'
    };
    var LABELS = { '/dashboard': 'Dashboard', '/supplier': 'Dashboard', '/jobs': 'Jobs', '/locations': 'Locations', '/stock': 'Stock', '/yard': 'Yard check', '/jobs/create': 'Create' };
    function buildTabbar() {
        var nav = document.querySelector('header .nav-scroll');
        if (!nav || document.getElementById('tabbar')) return;
        var want = ['a[href="/dashboard"], a[href="/supplier"]', '#navJobs', '#navLocations', '#navStock', '#navCreate'];
        var picked = [];
        want.forEach(function (sel) {
            var a = nav.querySelector(sel);
            if (a && !a.classList.contains('hidden')) picked.push(a);
        });
        if (picked.length < 4) {
            var y = nav.querySelector('a[href="/yard"]');
            if (y && !y.classList.contains('hidden')) picked.splice(Math.min(1, picked.length), 0, y);
        }
        if (!picked.length) return;
        var bar = document.createElement('nav');
        bar.id = 'tabbar';
        bar.className = 'tabbar';
        bar.setAttribute('aria-label', 'Main');
        picked.slice(0, 5).forEach(function (a) {
            var href = a.getAttribute('href');
            var t = document.createElement('a');
            t.href = href;
            t.innerHTML = (ICONS[href] || '') + '<span></span>';
            t.querySelector('span').textContent = LABELS[href] || a.textContent.trim();
            if (isCurrent(href)) t.classList.add('is-current');
            bar.appendChild(t);
        });
        document.body.appendChild(bar);
        document.body.classList.add('has-tabbar');
    }
    function hdr() {
        var h = document.querySelector('header.sticky-top');
        if (h) root.style.setProperty('--hdr', h.offsetHeight + 'px');
    }
    hdr();
    window.addEventListener('resize', hdr);
    if (!document.getElementById('loginForm') && localStorage.getItem('token')) buildTabbar();
})();
