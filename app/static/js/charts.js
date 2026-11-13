(function () {
  var PALETTE = ['#14625c', '#b45309', '#1d4ed8', '#9f1239', '#0e7490', '#a16207', '#15803d', '#4b5563'];
  var charts = new WeakMap();

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function fmtMoney(v) { return '\u20b9' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }); }

  function render(canvas) {
    var type = canvas.dataset.type || 'bar';
    var url = '/analytics/data?dataset=' + encodeURIComponent(canvas.dataset.dataset) + '&days=' + encodeURIComponent(canvas.dataset.days || 14);
    fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) { throw new Error('bad response'); }
      return r.json();
    }).then(function (data) {
      var old = charts.get(canvas);
      if (old) { old.destroy(); }
      var hasData = data.series.some(function (s) { return s.data.some(function (v) { return v > 0 || v < 0; }); });
      var holder = canvas.parentElement;
      var note = holder.querySelector('.chart-empty');
      if (note) { note.remove(); }
      if (!hasData) {
        canvas.style.display = 'none';
        var p = document.createElement('p');
        p.className = 'chart-empty text-secondary';
        p.textContent = 'No data to show yet for ' + data.title.toLowerCase() + '.';
        holder.appendChild(p);
        return;
      }
      canvas.style.display = '';
      Chart.defaults.color = css('--ink-soft');
      Chart.defaults.font.family = '"IBM Plex Sans", system-ui, sans-serif';
      var isPie = type === 'pie';
      var datasets = data.series.map(function (s, i) {
        var color = PALETTE[i % PALETTE.length];
        if (isPie) { return { label: s.label, data: s.data, backgroundColor: s.data.map(function (_, j) { return PALETTE[j % PALETTE.length]; }), borderColor: css('--surface'), borderWidth: 2 }; }
        return { label: s.label, data: s.data, backgroundColor: type === 'area' ? color + '33' : color, borderColor: color, borderWidth: 2, fill: type === 'area', tension: 0.25, pointRadius: 2 };
      });
      var options = {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: isPie || data.series.length > 1 },
          tooltip: { callbacks: { label: function (ctx) {
            var v = isPie ? ctx.parsed : ctx.parsed.y;
            var text = data.money ? fmtMoney(v) : data.percent ? v + '%' : v;
            return (ctx.dataset.label ? ctx.dataset.label + ': ' : '') + text;
          } } }
        }
      };
      if (!isPie) {
        options.scales = {
          x: { grid: { color: css('--line') }, ticks: { maxRotation: 45, autoSkip: true } },
          y: { beginAtZero: true, grid: { color: css('--line') }, ticks: { precision: data.money ? undefined : 0, callback: function (v) { return data.money ? fmtMoney(v) : data.percent ? v + '%' : v; } } }
        };
        if (data.percent) { options.scales.y.max = 100; }
      }
      charts.set(canvas, new Chart(canvas, { type: isPie ? 'pie' : (type === 'area' ? 'line' : type), data: { labels: data.labels, datasets: datasets }, options: options }));
    }).catch(function () {
      var holder = canvas.parentElement;
      if (!holder.querySelector('.chart-empty')) {
        var p = document.createElement('p');
        p.className = 'chart-empty text-secondary';
        p.textContent = 'This chart could not be loaded.';
        holder.appendChild(p);
      }
    });
  }

  window.renderPvttChart = render;
  document.querySelectorAll('canvas[data-chart]').forEach(render);
})();
