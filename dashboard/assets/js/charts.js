/* Grafik garis deret waktu tanpa pustaka. Garis diputus pada celah data, bukan disambung. */
(function () {
  const pad = (n) => String(n).padStart(2, "0");
  const hms = (t) => { const d = new Date(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 5, 10]) if (v <= m * p) return m * p;
    return 10 * p;
  }

  function create(canvas, tip, opts) {
    let last = null;
    const ctxOf = () => {
      const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      const g = canvas.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { g, w: r.width, h: r.height };
    };

    function draw(series, from, to, gapMs) {
      const { g, w, h } = ctxOf();
      const left = 42, right = 8, top = 8, bottom = 24;
      const iw = w - left - right, ih = h - top - bottom;
      const X = (t) => left + ((t - from) / (to - from)) * iw;
      g.clearRect(0, 0, w, h);
      const visible = series.map((s) => s.points.filter((p) => p.t >= from - gapMs));
      const peak = Math.max(0, ...visible.flat().map((p) => p[opts.key]));
      const maxY = niceMax(peak * 1.05);
      const Y = (v) => top + ih - (v / maxY) * ih;
      g.font = "12px 'Atkinson Hyperlegible Next', system-ui, sans-serif";
      g.lineWidth = 1;
      for (let i = 0; i <= 2; i++) {
        const val = (maxY * i) / 2, y = Y(val);
        g.strokeStyle = css("--line"); g.beginPath(); g.moveTo(left, y); g.lineTo(w - right, y); g.stroke();
        g.fillStyle = css("--muted"); g.textAlign = "right"; g.textBaseline = "middle";
        g.fillText(val.toFixed(maxY < 2 ? 2 : 1), left - 6, y);
      }
      g.textAlign = "center"; g.textBaseline = "alphabetic"; g.fillStyle = css("--muted");
      const ticks = iw < 320 ? 2 : 4;
      for (let i = 0; i <= ticks; i++) {
        const t = from + ((to - from) * i) / ticks;
        g.textAlign = i === 0 ? "left" : i === ticks ? "right" : "center";
        g.fillText(hms(t), X(t), h - 6);
      }
      g.save();
      g.beginPath(); g.rect(left, top, iw, ih); g.clip();
      // Celah tersorot dulu, memakai sumber data utama
      series.forEach((s, i) => {
        const pts = visible[i];
        g.fillStyle = css("--gap");
        for (let k = 1; k < pts.length; k++) {
          if (pts[k].t - pts[k - 1].t > gapMs) g.fillRect(X(pts[k - 1].t), top, X(pts[k].t) - X(pts[k - 1].t), ih);
        }
      });
      series.forEach((s, i) => {
        const pts = visible[i];
        g.strokeStyle = css(s.color); g.fillStyle = css(s.color); g.lineWidth = 2;
        g.setLineDash(s.dash ? [6, 4] : []);
        g.beginPath();
        pts.forEach((p, k) => {
          const brk = k === 0 || p.t - pts[k - 1].t > gapMs;
          if (brk) g.moveTo(X(p.t), Y(p[opts.key])); else g.lineTo(X(p.t), Y(p[opts.key]));
        });
        g.stroke(); g.setLineDash([]);
        pts.forEach((p, k) => {   // titik tunggal di antara dua celah tetap terlihat
          const alone = (k === 0 || p.t - pts[k - 1].t > gapMs) && (k === pts.length - 1 || pts[k + 1].t - p.t > gapMs);
          if (alone) { g.beginPath(); g.arc(X(p.t), Y(p[opts.key]), 3, 0, 7); g.fill(); }
        });
      });
      g.restore();
      last = { series, visible, X, iw, left, from, to };
      return visible.flat().length;
    }

    function showAt(x) {
      if (!last) return;
      let best = null;
      last.series.forEach((s, i) => last.visible[i].forEach((p) => {
        const d = Math.abs(last.X(p.t) - x);
        if (p.t >= last.from && (!best || d < best.d)) best = { d, p, s };
      }));
      if (!best || best.d > 30) { tip.hidden = true; return; }
      tip.textContent = `${best.s.name}: ${best.p[opts.key].toFixed(3)} ${opts.unit}. Waktu sensor ${hms(best.p.sent)}, seq ${best.p.seq}`;
      tip.hidden = false;
      const wrap = canvas.parentElement.getBoundingClientRect();
      tip.style.left = Math.max(0, Math.min(x, wrap.width - tip.offsetWidth)) + "px";
    }
    canvas.addEventListener("pointermove", (e) => showAt(e.clientX - canvas.getBoundingClientRect().left));
    canvas.addEventListener("pointerleave", () => { tip.hidden = true; });
    canvas.addEventListener("blur", () => { tip.hidden = true; });
    canvas.addEventListener("focus", () => { if (last) showAt(last.left + last.iw); });
    return { draw };
  }
  window.WACharts = { create, hms };
})();
