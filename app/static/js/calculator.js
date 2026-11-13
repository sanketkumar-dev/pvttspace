(function () {
  var exprEl = document.getElementById('calc-expr');
  var dispEl = document.getElementById('calc-display');
  var histEl = document.getElementById('calc-history');
  var sci = document.getElementById('calc-sci');
  var sciBtn = document.getElementById('calc-sci-toggle');
  var angleBtn = document.getElementById('calc-angle');
  if (!exprEl) { return; }

  var expr = '';
  var degrees = true;
  var justDone = false;
  var history = [];

  function fact(n) {
    if (n < 0 || n !== Math.floor(n) || n > 170) { throw new Error('Factorial needs a whole number from 0 to 170'); }
    var r = 1; for (var i = 2; i <= n; i++) { r *= i; } return r;
  }
  var FUNCS = {
    sin: function (x) { return Math.sin(degrees ? x * Math.PI / 180 : x); },
    cos: function (x) { return Math.cos(degrees ? x * Math.PI / 180 : x); },
    tan: function (x) { return Math.tan(degrees ? x * Math.PI / 180 : x); },
    log: function (x) { if (x <= 0) { throw new Error('log needs a positive number'); } return Math.log10(x); },
    ln: function (x) { if (x <= 0) { throw new Error('ln needs a positive number'); } return Math.log(x); },
    sqrt: function (x) { if (x < 0) { throw new Error('Square root of a negative number'); } return Math.sqrt(x); }
  };

  /* A small recursive-descent parser, so nothing is ever passed to eval. */
  function evaluate(src) {
    var s = src.replace(/\u00d7/g, '*').replace(/\u00f7/g, '/').replace(/\u2212/g, '-').replace(/\u03c0/g, 'pi').replace(/\u221a/g, 'sqrt');
    var tok = [], i = 0;
    while (i < s.length) {
      var c = s[i];
      if (c === ' ') { i++; continue; }
      if (/[0-9.]/.test(c)) {
        var j = i; while (j < s.length && /[0-9.]/.test(s[j])) { j++; }
        var t = s.slice(i, j);
        if (t === '.' || (t.match(/\./g) || []).length > 1) { throw new Error('Check the number'); }
        tok.push({ t: 'num', v: parseFloat(t) }); i = j;
      } else if (/[a-z]/.test(c)) {
        var k = i; while (k < s.length && /[a-z]/.test(s[k])) { k++; }
        tok.push({ t: 'id', v: s.slice(i, k) }); i = k;
      } else if ('+-*/^%!()'.indexOf(c) >= 0) { tok.push({ t: 'op', v: c }); i++; }
      else { throw new Error('Unsupported character'); }
    }
    var p = 0;
    function peekOp(ops) { var x = tok[p]; return x && x.t === 'op' && ops.indexOf(x.v) >= 0 ? x : null; }
    function expectOp(o) { var x = tok[p++]; if (!x || x.t !== 'op' || x.v !== o) { throw new Error('Missing ' + o); } }
    function sum() { var v = prod(); var o; while ((o = peekOp(['+', '-']))) { p++; var r = prod(); v = o.v === '+' ? v + r : v - r; } return v; }
    function prod() { var v = unary(); var o; while ((o = peekOp(['*', '/']))) { p++; var r = unary(); if (o.v === '/' && r === 0) { throw new Error('Cannot divide by zero'); } v = o.v === '*' ? v * r : v / r; } return v; }
    function unary() { var o = peekOp(['-', '+']); if (o) { p++; var v = unary(); return o.v === '-' ? -v : v; } return power(); }
    function power() { var b = postfix(); if (peekOp(['^'])) { p++; return Math.pow(b, unary()); } return b; }
    function postfix() { var v = primary(); var o; while ((o = peekOp(['%', '!']))) { p++; v = o.v === '%' ? v / 100 : fact(v); } return v; }
    function primary() {
      var x = tok[p++];
      if (!x) { throw new Error('The expression is incomplete'); }
      if (x.t === 'num') { return x.v; }
      if (x.t === 'id') {
        if (x.v === 'pi') { return Math.PI; }
        if (x.v === 'e') { return Math.E; }
        var f = FUNCS[x.v]; if (!f) { throw new Error('Unknown function ' + x.v); }
        expectOp('('); var a = sum(); expectOp(')'); return f(a);
      }
      if (x.v === '(') { var v = sum(); expectOp(')'); return v; }
      throw new Error('Unexpected ' + x.v);
    }
    var out = sum();
    if (p < tok.length) { throw new Error('Check the expression'); }
    if (!isFinite(out)) { throw new Error('Math error'); }
    if (Math.abs(out) < 1e-12) { out = 0; }
    return parseFloat(out.toPrecision(12));
  }

  function show(result) {
    exprEl.textContent = expr || '\u00a0';
    dispEl.textContent = result !== undefined ? result : (expr || '0');
  }

  function addHistory(e, r) {
    history.unshift(e + ' = ' + r);
    history = history.slice(0, 12);
    histEl.innerHTML = '';
    history.forEach(function (h) { var li = document.createElement('li'); li.className = 'row-item py-2 text-break'; li.textContent = h; histEl.appendChild(li); });
  }

  function press(k) {
    var isOperator = /^[+\-\u00d7\u00f7^%!)]$/.test(k);
    if (justDone && !isOperator) { expr = ''; }
    justDone = false;
    expr += k;
    show();
  }

  function act(a) {
    if (a === 'clear') { expr = ''; justDone = false; show('0'); }
    else if (a === 'del') { expr = expr.replace(/(sin\(|cos\(|tan\(|log\(|ln\(|sqrt\(|pi|.)$/, ''); show(expr ? undefined : '0'); }
    else if (a === 'angle') { degrees = !degrees; angleBtn.textContent = degrees ? 'DEG' : 'RAD'; }
    else if (a === 'eval') {
      if (!expr) { return; }
      try { var r = evaluate(expr); addHistory(expr, r); exprEl.textContent = expr + ' ='; dispEl.textContent = r; expr = String(r); justDone = true; }
      catch (err) { exprEl.textContent = expr; dispEl.textContent = err.message; justDone = false; }
    }
  }

  document.getElementById('calc').addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) { return; }
    if (b.dataset.k) { press(b.dataset.k); } else if (b.dataset.act) { act(b.dataset.act); }
  });
  sciBtn.addEventListener('click', function () { var open = sci.hidden; sci.hidden = !open; sciBtn.setAttribute('aria-pressed', open ? 'true' : 'false'); });

  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.ctrlKey || e.metaKey || e.altKey) { return; }
    if (/^[0-9.()+\-%^!]$/.test(e.key)) { press(e.key); e.preventDefault(); }
    else if (e.key === '*') { press('\u00d7'); e.preventDefault(); }
    else if (e.key === '/') { press('\u00f7'); e.preventDefault(); }
    else if (e.key === 'Enter' || e.key === '=') { act('eval'); e.preventDefault(); }
    else if (e.key === 'Backspace') { act('del'); e.preventDefault(); }
    else if (e.key === 'Escape') { act('clear'); }
  });
  show('0');
})();
