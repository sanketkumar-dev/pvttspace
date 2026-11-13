(function () {
  if (window.lucide) { window.lucide.createIcons(); }

  /* Sidebar (mobile) */
  var sidebar = document.getElementById('sidebar');
  var overlay = document.getElementById('overlay');
  var menuBtn = document.getElementById('menu-btn');
  function setSidebar(open) {
    if (!sidebar) { return; }
    sidebar.classList.toggle('open', open);
    overlay.classList.toggle('open', open);
    if (menuBtn) { menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
  }
  if (menuBtn) { menuBtn.addEventListener('click', function () { setSidebar(true); }); }
  if (overlay) { overlay.addEventListener('click', function () { setSidebar(false); }); }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { setSidebar(false); } });

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var token = csrfMeta ? csrfMeta.content : '';

  /* Note autosave */
  var form = document.getElementById('note-form');
  if (form && form.dataset.autosave) {
    var status = document.getElementById('save-status');
    var titleEl = document.getElementById('note-title');
    var contentEl = document.getElementById('note-content');
    var timer = null;
    var save = function () {
      status.textContent = 'Saving';
      fetch(form.dataset.autosave, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
        body: JSON.stringify({ title: titleEl.value, content: contentEl.value })
      }).then(function (r) {
        if (!r.ok) { throw new Error('save failed'); }
        return r.json();
      }).then(function (d) { status.textContent = 'Saved at ' + d.saved_at; })
        .catch(function () { status.textContent = 'Could not save automatically. Use the Save note button.'; });
    };
    form.addEventListener('input', function () {
      status.textContent = 'Unsaved changes';
      clearTimeout(timer);
      timer = setTimeout(save, 1200);
    });
  }

  /* Service worker (installable app, offline notice, notification display) */
  var swReady = null;
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
    swReady = navigator.serviceWorker.register('/sw.js').then(function () { return navigator.serviceWorker.ready; }).catch(function () { return null; });
  }

  /* Reminders: poll for due reminders while the site is open */
  var root = document.getElementById('app-root');
  var notifyOn = root && root.dataset.notify === '1';

  function beep() {
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) { return; }
      var ctx = new Ctx(), osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.frequency.value = 880; gain.gain.value = 0.08;
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.35);
    } catch (e) { /* sound is optional */ }
  }

  function showToast(title, body) {
    var holder = document.getElementById('toasts');
    if (!holder || !window.bootstrap) { return; }
    var el = document.createElement('div');
    el.className = 'toast'; el.setAttribute('role', 'alert');
    var head = document.createElement('div'); head.className = 'toast-header';
    var strong = document.createElement('strong'); strong.className = 'me-auto'; strong.textContent = 'Reminder';
    var close = document.createElement('button'); close.type = 'button'; close.className = 'btn-close'; close.setAttribute('data-bs-dismiss', 'toast'); close.setAttribute('aria-label', 'Close');
    head.appendChild(strong); head.appendChild(close);
    var bodyEl = document.createElement('div'); bodyEl.className = 'toast-body';
    var t = document.createElement('div'); t.className = 'fw-medium'; t.textContent = title;
    var b = document.createElement('div'); b.textContent = body;
    bodyEl.appendChild(t); bodyEl.appendChild(b);
    el.appendChild(head); el.appendChild(bodyEl); holder.appendChild(el);
    new window.bootstrap.Toast(el, { autohide: false }).show();
  }

  function notifyUser(r) {
    showToast(r.title, r.body);
    beep();
    if ('Notification' in window && Notification.permission === 'granted') {
      var opts = { body: r.body, tag: 'reminder-' + r.id, icon: '/static/icons/icon-192.png' };
      if (swReady) {
        swReady.then(function (reg) { if (reg) { reg.showNotification(r.title, opts); } else { new Notification(r.title, opts); } });
      } else { new Notification(r.title, opts); }
    }
  }

  var busy = false;
  function poll() {
    if (busy) { return; }
    busy = true;
    fetch('/reminders/due', { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (list) {
        return Promise.all(list.map(function (r) {
          notifyUser(r);
          return fetch('/reminders/' + r.id + '/notified', { method: 'POST', headers: { 'X-CSRFToken': token }, credentials: 'same-origin' });
        }));
      })
      .catch(function () { /* try again on the next tick */ })
      .then(function () { busy = false; });
  }
  if (notifyOn) { poll(); setInterval(poll, 30000); }

  /* Notification permission panel on the reminders page */
  var panel = document.getElementById('notify-panel');
  if (panel) {
    var statusEl = document.getElementById('notify-status');
    var btn = document.getElementById('notify-btn');
    var render = function () {
      btn.hidden = true;
      if (panel.dataset.enabled !== '1') { statusEl.textContent = 'Reminder notifications are turned off in Settings. Reminders will still show as due in this list.'; return; }
      if (!('Notification' in window)) { statusEl.textContent = 'This browser does not support system notifications. Reminders will show as a message inside PVTTSpace while it is open.'; return; }
      if (Notification.permission === 'granted') { statusEl.textContent = 'Notifications are allowed. You will be alerted while PVTTSpace is open.'; }
      else if (Notification.permission === 'denied') { statusEl.textContent = 'Notifications are blocked for this site. You will still see a message inside PVTTSpace. To change this, allow notifications for this site in your browser settings.'; }
      else { statusEl.textContent = 'Notifications are not allowed yet. Without permission you will only see a message inside PVTTSpace.'; btn.hidden = false; }
    };
    btn.addEventListener('click', function () { Notification.requestPermission().then(render); });
    render();
  }
})();
