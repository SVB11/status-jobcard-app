/* Yard stock photos: camera/gallery pick, shrink on the phone before upload, shared helpers. */
(function () {
  var MAX_SIDE = 1600;
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  async function shrink(file) {
    if (!file) throw new Error('Take or choose a photo first.');
    if (!/^image\//.test(file.type || 'image/')) throw new Error('That file is not a photo.');
    try {
      var bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      var scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      var c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(bmp.width * scale));
      c.height = Math.max(1, Math.round(bmp.height * scale));
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      var blob = await new Promise(function (res) { c.toBlob(res, 'image/jpeg', 0.85); });
      if (blob) return new File([blob], 'photo.jpg', { type: 'image/jpeg' });
    } catch (e) { /* browser cannot decode (e.g. HEIC off Safari): send the original, the server checks it */ }
    if (file.size > 15 * 1024 * 1024) throw new Error('Photo is larger than 15 MB.');
    return file;
  }
  function token() { try { return localStorage.getItem('token') || ''; } catch (e) { return ''; } }
  async function send(url, formData, method) {
    var r = await fetch(url, { method: method || 'POST', headers: { 'Authorization': 'Bearer ' + token() }, body: formData });
    if (r.status === 401) { location.href = '/login'; throw new Error('Sign in again.'); }
    var data = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(data.detail || 'Could not save.');
    return data;
  }
  /* One hidden camera input per page; resolves with the chosen file (or null if cancelled). */
  var picker = null;
  function pickPhoto() {
    return new Promise(function (resolve) {
      if (!picker) {
        picker = document.createElement('input');
        picker.type = 'file';
        picker.accept = 'image/*';
        picker.setAttribute('capture', 'environment');
        picker.hidden = true;
        document.body.appendChild(picker);
      }
      picker.value = '';
      picker.onchange = function () { resolve(picker.files && picker.files[0] || null); };
      picker.click();
    });
  }
  async function replaceUnitPhoto(unitId) {
    var file = await pickPhoto();
    if (!file) return null;
    var fd = new FormData();
    fd.append('photo', await shrink(file), 'photo.jpg');
    return send('/api/yard/stock/units/' + encodeURIComponent(unitId) + '/photo', fd);
  }
  function time(v) {
    return v ? new Date(v).toLocaleString('en-ZA', { timeZone: 'Africa/Johannesburg', dateStyle: 'medium', timeStyle: 'short' }) + ' SAST' : '';
  }
  window.stsYard = { esc: esc, shrink: shrink, send: send, pickPhoto: pickPhoto, replaceUnitPhoto: replaceUnitPhoto, time: time };
})();
