/* Shared full-screen photo viewer. Keeps the user inside the app (no new tab),
   so the iPhone home-screen app always has a way back.
   Close: the Close button, Esc, a tap outside the photo, or the browser/phone Back. */
(function () {
    var overlay = null, img = null, caption = null, pushed = false;

    function build() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.id = 'photoViewer';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Photo viewer');
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:none;flex-direction:column;background:#000;';
        overlay.innerHTML =
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:calc(env(safe-area-inset-top,0px) + 10px) 14px 10px;">' +
            '<button type="button" id="photoViewerClose" style="min-height:52px;min-width:120px;padding:10px 18px;border-radius:12px;background:#025daa;color:#fff;font-weight:800;font-size:17px;letter-spacing:.06em;text-transform:uppercase;border:2px solid #fff;">&#8592; Close</button>' +
            '<div id="photoViewerCaption" style="color:#cfd8e3;font-size:13px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></div>' +
            '</div>' +
            '<div id="photoViewerStage" style="flex:1;display:flex;align-items:center;justify-content:center;overflow:auto;padding:0 8px calc(env(safe-area-inset-bottom,0px) + 12px);">' +
            '<img id="photoViewerImg" alt="" style="max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;touch-action:pinch-zoom;">' +
            '</div>';
        document.body.appendChild(overlay);
        img = overlay.querySelector('#photoViewerImg');
        caption = overlay.querySelector('#photoViewerCaption');
        overlay.querySelector('#photoViewerClose').addEventListener('click', function (e) { e.stopPropagation(); requestClose(); });
        overlay.addEventListener('click', function (e) { if (e.target !== img) requestClose(); });
    }

    function hide() {
        if (!overlay || overlay.style.display === 'none') return;
        overlay.style.display = 'none';
        img.removeAttribute('src');
        document.documentElement.style.overflow = '';
    }

    function requestClose() {
        if (pushed) { pushed = false; history.back(); }  // popstate is not needed; hide now
        hide();
    }

    window.openPhotoViewer = function (src, label) {
        if (!src) return;
        build();
        img.src = src;
        img.alt = label || 'Photo';
        caption.textContent = label || '';
        overlay.style.display = 'flex';
        document.documentElement.style.overflow = 'hidden';
        if (!pushed) {
            try { history.pushState({ photoViewer: true }, ''); pushed = true; } catch (e) {}
        }
        overlay.querySelector('#photoViewerClose').focus();
    };
    window.closePhotoViewer = requestClose;

    window.addEventListener('popstate', function () { pushed = false; hide(); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay && overlay.style.display !== 'none') requestClose();
    });
    // Any element with data-viewer-src opens in the viewer instead of a new tab.
    document.addEventListener('click', function (e) {
        var el = e.target && e.target.closest ? e.target.closest('[data-viewer-src]') : null;
        if (!el) return;
        e.preventDefault();
        window.openPhotoViewer(el.getAttribute('data-viewer-src'), el.getAttribute('data-viewer-label') || '');
    });
})();
