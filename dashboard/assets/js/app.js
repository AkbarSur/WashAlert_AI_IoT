/* Menghubungkan MQTT, store, dan tampilan. Isi dari jaringan hanya ditulis lewat textContent. */
(function () {
  const $ = (id) => document.getElementById(id);
  const { hms } = window.WACharts;
  const fmtDur = window.WAStore.fmtDur;
  const CMD_TIMEOUT_MS = 8000;
  const REASONS = {
    model_missing: "file model tidak ditemukan", metadata_missing: "metadata model tidak ditemukan", metadata_invalid: "metadata model tidak valid",
    synthetic_not_allowed: "model sintetis tidak diizinkan", feature_schema_mismatch: "skema fitur tidak cocok", model_hash_mismatch: "file model berubah atau rusak",
    dependency_missing: "pustaka ML belum terpasang", dependency_mismatch: "versi pustaka ML tidak cocok", model_invalid: "file model rusak",
    prediction_error: "prediksi gagal berulang", unexpected_label: "model memberi label tak dikenal", missing_features: "telemetri tidak membawa fitur model",
    incomplete_window: "jendela 30 detik belum lengkap", stale_sensor: "sampel sensor basi", sensor_fault: "sensor gagal terbaca",
    low_probability: "probabilitas di bawah ambang", out_of_training_range: "fitur di luar rentang data latih", invalid_features: "fitur tidak valid",
  };
  const why = (r) => REASONS[r] || r || "alasan tidak dilaporkan";
  const SOURCE = { model: "Model", rule: "Aturan ambang, bukan AI", rule_low_probability: "Aturan, probabilitas model rendah", rule_fallback: "Aturan, fallback", none: "Tidak ada, timer FSM ditahan" };
  const NOTE = { IDLE: "Mesin diam", WASHING: "Mesin mencuci", SPIN: "Fase peras", DONE: "Menunggu konfirmasi", DISARMED: "Pemantauan dijeda", OFFLINE: "Detector tidak tersambung", SENSOR_LOST: "HP A tidak mengirim data", ONLINE: "Menunggu telemetri", UNKNOWN: "Status tak dikenal" };
  const KINDS = { completed_after_spin: "Cucian selesai", stopped_without_spin: "Mesin berhenti tanpa spin", correction: "Koreksi: mesin aktif lagi", sensor_lost: "HP A tidak mengirim data" };
  const ALERT_STATE = { pending: "Menunggu konfirmasi", acknowledged: "Dikonfirmasi pemilik", superseded: "Digantikan koreksi", disarmed: "Dihentikan DISARM", expired: "Kedaluwarsa", ended: "Berakhir", info: "Informasi" };
  const DEVICE_STATE = { none: "belum ada data", live: "live", stale: "data usang", offline: "offline" };

  const cache = new Map();
  function text(id, value) {
    if (cache.get(id) === value) return;
    cache.set(id, value);
    $(id).textContent = value;
  }
  function attr(el, k, v) { if (el.getAttribute(k) !== v) el.setAttribute(k, v); }
  function badge(id, value, tone) { text(id, value); attr($(id), "data-tone", tone); }
  function el(tag, cls, content) { const e = document.createElement(tag); if (cls) e.className = cls; if (content !== undefined) e.textContent = content; return e; }

  let store = null, client = null, prefix = "", cfg = null, connFailure = null, rendered = -1, firstConnectAt = 0;
  let rangeMin = 5, pendingCmd = null, charts = {};

  /* ---------- MQTT ---------- */
  function connect(auth) {
    if (typeof window.mqtt === "undefined") return fatal("Pustaka MQTT gagal dimuat. Periksa file assets/vendor/mqtt.min.js.");
    badge("conn", "Menghubungkan", "neutral");
    const options = Object.assign({ clientId: "dash-" + Math.random().toString(16).slice(2, 10), reconnectPeriod: 3000, connectTimeout: 10000, clean: true }, auth || {});
    client = window.mqtt.connect(cfg.websocket_url, options);
    client.on("connect", () => {
      connFailure = null; firstConnectAt = firstConnectAt || Date.now();
      store.setConnected(true, Date.now());
      badge("conn", "Menyambung ulang", "warn");
      client.subscribe(["status", "alerts", "alert_state", "edge/+/telemetry"].map((t) => prefix + t), { qos: 1 }, (err) => {
        if (err) { connFailure = "Gagal berlangganan topik: " + err.message; badge("conn", "Galat berlangganan", "bad"); return; }
        badge("conn", "Tersambung", "ok");
      });
    });
    client.on("reconnect", () => { if (!connFailure) badge("conn", "Menyambung ulang", "warn"); });
    client.on("close", () => { store.setConnected(false, Date.now()); if (!connFailure) badge("conn", "Terputus, mencoba lagi", "bad"); schedule(); });
    client.on("offline", () => { store.setConnected(false, Date.now()); schedule(); });
    client.on("error", (err) => {
      const denied = /not authori[sz]ed|bad user/i.test(err.message || "");
      connFailure = denied ? "Broker menolak akun ini" : "Galat koneksi: " + err.message;
      badge("conn", denied ? "Tidak diizinkan" : "Galat koneksi", "bad");
      if (denied) { client.end(true); $("login").hidden = false; }
      schedule();
    });
    client.on("message", onMessage);
    window.addEventListener("pagehide", () => client && client.end(true), { once: true });
  }

  function onMessage(topic, payload) {
    let data;
    try { data = JSON.parse(payload.toString()); } catch (e) { store.ignored.invalid++; return schedule(); }
    const now = Date.now(), t = topic.slice(prefix.length);
    if (t === "status") {
      const accepted = store.onStatus(data, now);
      if (accepted && pendingCmd && data.last_command === pendingCmd.cmd && data.at_ms >= pendingCmd.at - 5000) resolveCmd();
    } else if (t === "alerts") store.onAlert(data, now);
    else if (t === "alert_state") store.onAlertState(data, now);
    else {
      const m = /^edge\/([^/]+)\/telemetry$/.exec(t);
      if (m) store.onTelemetry(m[1], data, now);
    }
    schedule();
  }

  /* ---------- Perintah: sukses hanya setelah detector menerbitkan status balasan ---------- */
  function feedback(message, tone) { text("cmd-feedback", message); attr($("cmd-feedback"), "data-tone", tone); }
  function send(cmd) {
    if (pendingCmd) return;
    if (!client || !store.connected) return feedback(`${cmd} gagal: dashboard tidak tersambung ke broker.`, "bad");
    feedback(`Mengirim ${cmd}.`, "neutral");
    const at = Date.now();
    pendingCmd = { cmd, at, timer: setTimeout(() => {
      pendingCmd = null; setButtons();
      feedback(`Batas waktu ${cmd}: detector tidak menjawab dalam ${CMD_TIMEOUT_MS / 1000} detik. Status mesin tidak berubah di sini. Periksa apakah detector berjalan.`, "bad");
    }, CMD_TIMEOUT_MS) };
    setButtons();
    client.publish(prefix + "control", cmd, { qos: 1 }, (err) => {
      if (!err || !pendingCmd) { if (pendingCmd) feedback(`${cmd} terkirim, menunggu konfirmasi detector.`, "neutral"); return; }
      clearTimeout(pendingCmd.timer); pendingCmd = null; setButtons();
      feedback(`${cmd} gagal dikirim: ${err.message}`, "bad");
    });
  }
  function resolveCmd() {
    clearTimeout(pendingCmd.timer);
    const c = pendingCmd.cmd; pendingCmd = null; setButtons();
    feedback(`Detector mengonfirmasi ${c} pada ${hms(Date.now())}.`, "ok");
  }
  function setButtons() {
    const busy = !!pendingCmd;
    ["btn-arm", "btn-disarm", "btn-disarm-yes"].forEach((id) => { $(id).disabled = busy; });
  }
  function askDisarm(show) {
    $("disarm-confirm").hidden = !show; $("btn-disarm").hidden = show; $("btn-arm").hidden = show;
    if (show) $("btn-disarm-no").focus();
  }

  /* ---------- Render, dibatasi agar paket MQTT tidak memicu render per pesan ---------- */
  let timer = null;
  function schedule() {
    if (timer || document.hidden) return;
    timer = setTimeout(() => { timer = null; render(); }, 250);
  }

  function render() {
    if (!store) return;
    const now = Date.now();
    store.expire(now);
    renderHeader(now); renderHero(now); renderAI(now); renderQuality(now); renderBanners(now);
    renderStrip(now); renderAlerts(now); renderEvents(); renderCharts(now);
    rendered = store.version;
  }

  function renderHeader(now) {
    text("clock", hms(now));
    const s = store.status;
    text("mode-chip", s && s.effective_mode ? (s.detection_mode === s.effective_mode ? s.effective_mode : `${s.effective_mode}, diminta ${s.detection_mode}`) : "Belum diketahui");
    const lastDev = Math.max(store.devices.edge1.lastAt, store.devices.edge2.lastAt, store.statusAt);
    text("last-update", lastDev ? `${hms(lastDev)}, ${fmtDur(now - lastDev)} lalu` : "Belum ada");
  }

  function renderHero(now) {
    const s = store.status, door = $("door");
    let fresh = "wait", note = "Menunggu detector";
    if (!s) {
      if (store.connected && now - firstConnectAt > 4000) { text("status", "Belum ada"); note = "Detector belum pernah melapor ke broker ini"; fresh = "empty"; }
      else if (connFailure) { text("status", "Galat"); note = connFailure; fresh = "error"; }
      else if (!store.connected && firstConnectAt) { text("status", "Terputus"); note = "Koneksi ke broker putus"; fresh = "offline"; }
      else text("status", "Memuat");
    } else {
      text("status", s.status);
      note = NOTE[s.status];
      fresh = "live";
      if (!store.connected) { fresh = "stale"; note = `Data terakhir ${hms(s.at_ms)}. Broker terputus`; }
      else if (s.status === "OFFLINE") fresh = "offline";
      else if (["WASHING", "SPIN"].includes(s.status) && store.deviceState("edge1", now) !== "live") { fresh = "stale"; note = "Belum ada data baru dari HP A"; }
    }
    text("door-note", note);
    attr(door, "data-status", s ? s.status : "LOADING"); attr(door, "data-fresh", fresh);
    document.querySelectorAll(".steps li").forEach((li) => {
      const on = s && li.dataset.s === s.status;
      li.classList.toggle("on", !!on);
      on ? li.setAttribute("aria-current", "step") : li.removeAttribute("aria-current");
    });
    text("reason", s ? s.reason : "Belum ada laporan dari detector.");
    // aktivitas
    const a = store.lastActivity;
    if (a) {
      text("activity", a.activity);
      text("activity-sub", a.activity === "UNKNOWN" ? `Tidak dapat ditentukan: ${why(a.activity_reason)}` : `Sumber: ${SOURCE[a.activity_source] || a.activity_source}`);
    } else {
      text("activity", s && s.status === "DISARMED" ? "Tidak dipantau" : s && s.status === "OFFLINE" ? "Tidak tersedia" : "Belum ada data");
      text("activity-sub", "Hasil pengolahan sensor saat ini");
    }
    // prediksi
    const ms = s ? s.model_status : null;
    if (!s || !ms) { text("prediction", "Belum ada prediksi"); text("prediction-sub", s ? "Status model tidak dilaporkan detector" : ""); }
    else if (ms === "not_configured") { text("prediction", "AI tidak aktif"); text("prediction-sub", "Mode RULE_ONLY"); }
    else if (ms !== "active") { text("prediction", "Model tidak dimuat"); text("prediction-sub", `Memakai aturan: ${why(s.fallback_reason)}`); }
    else if (a && a.activity_source === "model") {
      text("prediction", a.activity);
      text("prediction-sub", num(a.model_probability) ? `Probabilitas prediksi ${(a.model_probability * 100).toFixed(0)}%, belum terkalibrasi` : "");
    } else if (a) { text("prediction", "Tidak dipakai saat ini"); text("prediction-sub", why(a.activity_reason)); }
    else { text("prediction", "Belum ada prediksi"); text("prediction-sub", ""); }
    // lama siklus
    const inCycle = s && ["WASHING", "SPIN", "DONE", "SENSOR_LOST"].includes(s.status);
    text("minutes", inCycle ? `${s.run_minutes.toFixed(1)} menit` : "Belum ada siklus");
    text("avg", s && s.status !== "OFFLINE" && s.device_id === "edge1" ? `RMS rata-rata ${s.avg_rms.toFixed(3)} m/s²` : "");
    // perangkat
    const conn = store.connected;
    ["edge1", "edge2"].forEach((d) => {
      const st = store.deviceState(d, now), name = d === "edge1" ? "HP A" : "HP B";
      const shown = !conn && st !== "none" ? "tidak diketahui, broker putus" : DEVICE_STATE[st];
      const age = st === "stale" || st === "offline" ? `, ${fmtDur(now - store.devices[d].lastAt)} lalu` : "";
      text("dev-" + d, `${name}: ${shown}${age}`);
      attr($("dev-" + d), "data-tone", !conn && st !== "none" ? "warn" : { none: "neutral", live: "ok", stale: "warn", offline: "bad" }[st]);
    });
    const detector = !s ? ["belum melapor", "neutral"] : s.status === "OFFLINE" ? ["offline", "bad"] : !conn ? ["tidak diketahui, broker putus", "warn"] : [`online, melapor ${hms(s.at_ms)}`, "ok"];
    text("dev-detector", "Detector: " + detector[0]); attr($("dev-detector"), "data-tone", detector[1]);
    // alert ringkas
    const open = store.alerts.find((x) => x.pending);
    text("alert-state", open ? `${KINDS[open.kind]}, menunggu konfirmasi` : store.alerts.length ? "Tidak ada alert aktif" : "Belum ada alert");
    text("alert-sub", open ? "Goyang HP B untuk konfirmasi" : "");
    attr($("alert-state"), "data-tone", open ? "warn" : "neutral");
    text("armed", !s ? "Belum diketahui" : s.status === "OFFLINE" ? "Tidak diketahui, detector offline" : s.armed ? "Aktif (ARM)" : "Dijeda (DISARM)");
  }

  const num = (v) => typeof v === "number" && Number.isFinite(v);

  function renderAI(now) {
    const s = store.status, a = store.lastActivity;
    if (!s) return;
    const ms = s.model_status;
    const badges = { active: s.model_data_kind === "synthetic" ? ["Model pengembangan, sintetis", "warn"] : ["Model dimuat", "info"], not_configured: ["Model tidak dipakai", "neutral"], unavailable: ["Model tidak dimuat", "bad"], failed: ["Model gagal", "bad"] };
    const b = badges[ms] || ["Status model tidak diketahui", "neutral"];
    badge("model-badge", b[0], b[1]);
    text("ai-mode", s.detection_mode || "Tidak dilaporkan");
    text("effective-mode", s.effective_mode || "Tidak dilaporkan");
    text("ai-activity", a ? a.activity : "Belum ada prediksi");
    text("ai-source", a ? (SOURCE[a.activity_source] || a.activity_source) : "Belum diketahui");
    text("ai-prob", a && num(a.model_probability) ? `${(a.model_probability * 100).toFixed(1)}%${s.probability_calibrated ? "" : ", belum terkalibrasi"}${a.activity_source === "model" ? "" : ", tidak dipakai FSM"}` : "Tidak tersedia");
    text("ai-time", a && num(a.model_probability) && num(a.classified_at_ms) ? hms(a.classified_at_ms) : "Tidak tersedia");
    text("ai-latency", num(s.inference_latency_ms) ? `${s.inference_latency_ms.toFixed(2)} ms` : "Tidak tersedia");
    text("ai-name", s.model_name || "Model tidak dimuat");
    text("ai-version", s.model_version || "Tidak tersedia");
    text("ai-kind", s.model_data_kind === "synthetic" ? "SINTETIS, bukan mesin cuci nyata" : s.model_data_kind === "real" ? "Rekaman mesin nyata" : "Tidak tersedia");
    text("ai-fallback", s.fallback_reason ? `Aktif: ${why(s.fallback_reason)}` : a && a.activity_source && a.activity_source.startsWith("rule_") ? `Sesaat: ${why(a.activity_reason)}` : "Tidak ada");
  }

  function renderQuality(now) {
    const dev = store.devices.edge1, d = dev.last, s = store.status;
    const st = store.deviceState("edge1", now);
    const sensorText = { none: ["Menunggu data sensor", "neutral"], live: ["Live", "ok"], stale: ["Data usang", "warn"], offline: ["HP A offline", "bad"] }[st];
    const conn = store.connected;
    const shown = !conn && st !== "none" ? ["Broker terputus", "bad"] : sensorText;
    badge("sensor-badge", shown[0], shown[1]);
    let q = shown;
    text("q-rej-br", `${store.ignored.invalid} rusak, ${store.ignored.duplicate} duplikat atau tidak urut`);
    text("q-rej-det", s && s.rejected ? `${s.rejected.stale} basi, ${s.rejected.replay} replay, ${s.rejected.schema} rusak` : "Tidak tersedia");
    if (!d) { badge("q-badge", q[0], q[1]); return; }
    text("q-time", hms(d.sent_at_ms));
    const skew = (dev.lastAt - d.sent_at_ms) / 1000;
    text("q-skew", Math.abs(skew) > 5 ? `${skew.toFixed(1)} detik, periksa jam HP` : `${skew.toFixed(1)} detik`);
    const v2 = d.schema_version === 2 && num(d.actual_hz);
    const na = "Tidak dilaporkan, telemetri v1";
    text("q-hz", v2 ? `${d.actual_hz.toFixed(2)} Hz` : na);
    text("q-n", v2 ? `${d.n_samples} dalam ${d.window_s.toFixed(1)} detik` : na);
    text("q-stale", v2 ? `${d.stale_count} dari ${d.n_samples}` : na);
    text("q-fault", !v2 ? na : d.sensor_fault ? "Gagal terbaca" : "Normal");
    const ds = { android: "Sensor Android", simulator: "SIMULATOR", synthetic_replay: "REKAMAN SINTETIS" }[d.data_source];
    text("q-source", ds || "Tidak dilaporkan");
    if (st === "live" && conn) {
      if (v2 && d.sensor_fault) q = ["Sensor gagal", "bad"];
      else if (!v2) q = ["Telemetri v1, kualitas tak dilaporkan", "warn"];
      else if (d.stale_count > 0) q = ["Sebagian sampel basi", "warn"];
    }
    badge("q-badge", q[0], q[1]);
  }

  function renderBanners(now) {
    const s = store.status, out = [];
    if (connFailure) out.push(["bad", "Koneksi bermasalah", connFailure]);
    if (s && s.model_status === "active" && s.model_data_kind !== "real") out.push(["warn", "MODEL PENGEMBANGAN (SINTETIS)", "Model ini dilatih dari data sintetis dan belum divalidasi pada mesin cuci. Prediksinya bukan bukti performa."]);
    if (s && (s.model_status === "unavailable" || s.model_status === "failed")) out.push(["bad", "Model tidak dipakai", `Sistem memakai aturan ambang. Alasan: ${why(s.fallback_reason)}.`]);
    const sim = ["edge1", "edge2"].filter((k) => { const d = store.devices[k]; return d.last && ["simulator", "synthetic_replay"].includes(d.last.data_source) && store.deviceState(k, now) !== "offline"; });
    if (sim.length) out.push(["info", "MODE SIMULASI", `Data ${sim.map((k) => (k === "edge1" ? "HP A" : "HP B")).join(" dan ")} berasal dari simulator atau rekaman sintetis, bukan sensor pada mesin cuci.`]);
    if (s && s.sensor && s.sensor.fault) out.push(["bad", "Sensor gagal terbaca", "Timer FSM ditahan sampai HP A mengirim data yang dapat dipercaya."]);
    const key = JSON.stringify(out);
    if (cache.get("banners") === key) return;
    cache.set("banners", key);
    const box = $("banners");
    box.replaceChildren(...out.map(([tone, title, body]) => {
      const div = el("div", "banner"); div.setAttribute("data-tone", tone);
      div.append(el("strong", "", title), el("span", "", body));
      return div;
    }));
  }

  function renderStrip(now) {
    const to = now, from = now - rangeMin * 60000, box = $("strip");
    const lanes = [["cycle", "Status siklus (FSM)"], ["activity", "Aktivitas"], ["source", "Sumber aktivitas"]];
    const any = store.lanes.cycle.length > 0;
    attr(box, "data-empty", any ? "false" : "true");
    text("strip-from", hms(from));
    if (store.path.length) text("path", store.path.join(" → "));
    if (!any) { text("strip-empty", store.connected ? "Menunggu laporan pertama dari detector." : "Belum tersambung ke broker."); return; }
    const LABEL = { rule: "aturan", model: "model", rule_low_probability: "aturan", rule_fallback: "fallback", none: "tidak ada" };
    box.replaceChildren(...lanes.map(([key, title]) => {
      const row = el("div", "lane");
      row.append(el("span", "lane-name", title));
      const track = el("div", "track");
      const segs = store.lanes[key];
      segs.forEach((seg, i) => {
        const end = i + 1 < segs.length ? segs[i + 1].from : now;
        if (end <= from) return;
        const a = Math.max(seg.from, from), left = ((a - from) / (to - from)) * 100, w = ((end - a) / (to - from)) * 100;
        const name = seg.v === null ? "tidak ada data" : (key === "source" ? LABEL[seg.v] || seg.v : seg.v);
        const d = el("div", "seg", w > 7 ? name : "");
        d.dataset.v = seg.v === null ? "NODATA" : seg.v;
        d.style.left = left + "%"; d.style.width = Math.max(w, 0.3) + "%";
        d.title = `${name}, ${hms(seg.from)}, ${fmtDur(end - seg.from)}`;
        track.append(d);
      });
      track.setAttribute("role", "img");
      const cur = segs[segs.length - 1];
      track.setAttribute("aria-label", `${title}, saat ini ${cur ? (cur.v === null ? "tidak ada data" : cur.v) : "belum ada data"}`);
      row.append(track);
      return row;
    }));
  }

  function renderAlerts(now) {
    const open = store.alerts.find((a) => a.pending), box = $("alert-active");
    const sig = JSON.stringify([store.alerts.map((a) => [a.state, a.reminders, a.lastAt]), store.dupAlerts, store.deviceState("edge2", now), store.status && store.status.spin_seen]);
    if (cache.get("alerts") === sig) return;
    cache.set("alerts", sig);
    box.hidden = !open;
    if (open) {
      const h2 = store.deviceState("edge2", now);
      box.replaceChildren(el("strong", "", KINDS[open.kind]),
        el("p", "", open.latestReason || open.reason),
        el("p", "", `Mode ${open.mode || "tidak diketahui"}. Spin ${open.spin ? "terdeteksi" : "tidak terdeteksi"}. Mesin bekerja ${open.run} menit.`),
        el("p", "ack", "Konfirmasi dilakukan dengan menggoyang HP B." + (h2 === "live" ? "" : " HP B saat ini tidak mengirim data.")));
    }
    const list = $("alerts");
    if (!store.alerts.length) { list.replaceChildren(el("li", "empty", "Belum ada alert.")); }
    else list.replaceChildren(...store.alerts.map((a) => {
      const li = el("li");
      li.dataset.state = a.state;
      const head = el("div", "alert-head");
      head.append(el("strong", "", KINDS[a.kind] || a.kind), el("span", "badge small", ALERT_STATE[a.state]));
      head.lastChild.setAttribute("data-tone", { pending: "warn", acknowledged: "ok", superseded: "info", disarmed: "neutral", expired: "bad", info: "info", ended: "neutral" }[a.state]);
      li.append(head, el("span", "meta", `${hms(a.firstAt)}${a.reminders ? `, ${a.reminders} pengingat` : ""}${a.endedAt ? `, berakhir ${hms(a.endedAt)}` : ""}`), el("span", "why", a.reason));
      return li;
    }));
    text("dup-note", store.dupAlerts ? `${store.dupAlerts} alert duplikat diabaikan berdasarkan alert_id.` : "");
  }

  function renderEvents() {
    if (cache.get("events") === store.version) return;
    cache.set("events", store.version);
    const list = $("events");
    if (!store.events.length) return;
    list.replaceChildren(...store.events.slice(0, 40).map((e) => {
      const li = el("li");
      li.dataset.kind = e.kind;
      li.append(el("time", "", hms(e.at)), el("span", "", e.text));
      return li;
    }));
  }

  function renderCharts(now) {
    const from = now - rangeMin * 60000, gap = store.staleMs;
    const series = [{ name: "HP A", color: "--series-a", points: store.devices.edge1.points }, { name: "HP B", color: "--series-b", dash: true, points: store.devices.edge2.points }];
    [["rms", "getaran", "m/s²"], ["rot", "rotasi", "rad"]].forEach(([key, label, unit]) => {
      const n = charts[key].draw(series, from, now, gap);
      $("empty-" + key).hidden = n > 0;
      const a = store.devices.edge1.last, val = a ? a[key === "rms" ? "motion_rms" : "rotation_rad"] : null;
      attr($("chart-" + key), "aria-label", a ? `Grafik ${label}, nilai terakhir HP A ${val.toFixed(3)} ${unit} pada ${hms(a.sent_at_ms)}` : `Grafik ${label}, belum ada data`);
    });
  }

  function fatal(message) {
    connFailure = message;
    badge("conn", "Galat", "bad");
    if (store) render(); else { text("status", "Galat"); text("door-note", message); attr($("door"), "data-fresh", "error"); }
  }

  /* ---------- Mulai ---------- */
  function start() {
    charts = {
      rms: window.WACharts.create($("chart-rms"), $("tip-rms"), { key: "rms", unit: "m/s²" }),
      rot: window.WACharts.create($("chart-rot"), $("tip-rot"), { key: "rot", unit: "rad" }),
    };
    $("btn-arm").addEventListener("click", () => send("ARM"));
    $("btn-disarm").addEventListener("click", () => askDisarm(true));
    $("btn-disarm-no").addEventListener("click", () => { askDisarm(false); $("btn-disarm").focus(); });
    $("btn-disarm-yes").addEventListener("click", () => { askDisarm(false); send("DISARM"); $("btn-disarm").focus(); });
    $("range").addEventListener("change", (e) => {
      rangeMin = Number(e.target.value);
      try { localStorage.setItem("washalert.range", String(rangeMin)); } catch (err) { /* preferensi saja */ }
      render();
    });
    try { const r = localStorage.getItem("washalert.range"); if (["2", "5", "15"].includes(r)) { rangeMin = Number(r); $("range").value = r; } } catch (err) { /* preferensi saja */ }
    document.addEventListener("visibilitychange", () => { if (!document.hidden) render(); });
    window.addEventListener("resize", schedule);
    $("login").addEventListener("submit", (e) => {
      e.preventDefault();
      $("login").hidden = true; connFailure = null;
      const auth = { username: $("login-user").value, password: $("login-pass").value };
      $("login-pass").value = "";
      connect(auth);
    });
    setInterval(() => { if (!document.hidden) render(); }, 1000);

    fetch("/config.json", { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then((c) => {
      cfg = c;
      store = window.WAStore.create(c);
      window.__washalert = store;   // hanya dibaca oleh test
      text("project", c.project_id);
      prefix = `washalert/${c.project_id}/`;
      text("foot", c.automatic_connection
        ? "Broker publik tanpa akun: PROJECT_ID hanya pemisah topik, bukan pengaman. Pihak lain dapat membaca atau mengirim pesan ke topik ini. Gunakan broker berakun untuk pemakaian nyata."
        : "Akun broker tidak disimpan di halaman ini maupun di /config.json.");
      render();
      if (!c.websocket_url) { connFailure = "MQTT_WS_URL belum diisi di .env"; badge("conn", "Belum dikonfigurasi", "bad"); return render(); }
      if (!c.automatic_connection) { $("login").hidden = false; badge("conn", "Perlu login", "warn"); return; }
      connect();
    }).catch((err) => fatal("Gagal membaca /config.json: " + err.message));
  }
  document.addEventListener("DOMContentLoaded", start);
})();
