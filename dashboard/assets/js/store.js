/* Keadaan dashboard tanpa DOM dan tanpa MQTT. Semua pesan divalidasi di sini.
   Status dan alert hanya berasal dari detector. Browser tidak pernah mengarang state mesin. */
(function () {
  const STATUS = ["ONLINE", "IDLE", "WASHING", "SPIN", "DONE", "DISARMED", "OFFLINE", "SENSOR_LOST"];
  const COMPLETION = ["completed_after_spin", "stopped_without_spin"];
  const MAX_POINTS = 1200, MAX_EVENTS = 100, MAX_ALERTS = 30, MAX_SEGMENTS = 300;
  const num = (v) => typeof v === "number" && Number.isFinite(v);
  const nonneg = (v) => num(v) && v >= 0;
  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

  function create(cfg) {
    const s = {
      staleMs: (cfg.stale_after_s || 20) * 1000,
      offlineMs: (cfg.offline_after_s || 60) * 1000,
      status: null, statusAt: 0, lastAtMs: 0,
      devices: { edge1: device(), edge2: device() },
      lanes: { cycle: [], activity: [], source: [] },
      events: [], alerts: [], path: [],
      ignored: { invalid: 0, duplicate: 0 },
      dupAlerts: 0, seenAlerts: new Set(), connected: false, version: 0,
    };
    return Object.assign(s, api);
  }
  function device() {
    return { points: [], last: null, lastAt: 0, boot: null, seq: -1 };
  }

  function validTelemetry(d, device) {
    return isObj(d) && d.device_id === device && typeof d.boot_id === "string" && d.boot_id &&
      Number.isInteger(d.sequence) && d.sequence >= 0 && Number.isInteger(d.sent_at_ms) && d.sent_at_ms > 0 &&
      nonneg(d.motion_rms) && nonneg(d.rotation_rad);
  }

  const api = {
    addEvent(at, kind, text) {
      this.events.unshift({ at, kind, text });
      this.events.sort((a, b) => b.at - a.at);   // status retained bisa membawa waktu lebih lama
      this.events.length = Math.min(this.events.length, MAX_EVENTS);
      this.version++;
    },

    onTelemetry(device, d, now) {
      const dev = this.devices[device];
      if (!dev || !validTelemetry(d, device)) { this.ignored.invalid++; return false; }
      // Sequence per boot_id: duplikat dan pesan tidak urut tidak boleh menggambar ulang titik lama.
      if (dev.boot === d.boot_id && d.sequence <= dev.seq) { this.ignored.duplicate++; return false; }
      dev.boot = d.boot_id; dev.seq = d.sequence; dev.last = d; dev.lastAt = now;
      dev.points.push({ t: now, sent: d.sent_at_ms, rms: d.motion_rms, rot: d.rotation_rad, seq: d.sequence });
      if (dev.points.length > MAX_POINTS) dev.points.shift();
      this.version++;
      return true;
    },

    deviceState(device, now) {
      const dev = this.devices[device];
      if (!dev.lastAt) return "none";
      const age = now - dev.lastAt;
      if (age >= this.offlineMs) return "offline";
      return age >= this.staleMs ? "stale" : "live";
    },

    onStatus(d, now) {
      if (!isObj(d) || typeof d.status !== "string" || !d.status || typeof d.reason !== "string" ||
          typeof d.armed !== "boolean" || !Number.isInteger(d.at_ms)) { this.ignored.invalid++; return false; }
      if (d.at_ms < this.lastAtMs) { this.ignored.duplicate++; return false; }
      if (this.status && d.at_ms === this.lastAtMs && d.status === this.status.status && d.reason === this.status.reason) {
        this.ignored.duplicate++; return false;   // retained yang diterima ulang setelah reconnect
      }
      const known = STATUS.includes(d.status) ? d.status : "UNKNOWN";
      const prev = this.status;
      this.status = Object.assign({}, d, { status: known, rawStatus: d.status });
      this.statusAt = now; this.lastAtMs = d.at_ms;
      if (!prev || prev.status !== known) {
        const dur = prev ? fmtDur(d.at_ms - prev.changedAt) : null;
        this.status.changedAt = d.at_ms;
        this.addEvent(d.at_ms, "cycle", (prev ? `${prev.status} ke ${known}` : known) + (dur ? ` setelah ${dur}` : "") + `. ${d.reason}`);
        if (["IDLE", "WASHING", "SPIN", "DONE", "SENSOR_LOST"].includes(known)) this.pushPath(known);
      } else {
        this.status.changedAt = prev.changedAt;
        if (d.last_command) this.addEvent(d.at_ms, "cmd", d.reason);
      }
      this.extend("cycle", known, d.at_ms);
      if (typeof d.activity === "string") {
        this.extend("activity", d.activity, num(d.classified_at_ms) ? d.classified_at_ms : d.at_ms, d);
        this.extend("source", d.activity_source || "none", d.at_ms);
        this.lastActivity = d;
      } else if (known === "DISARMED" || known === "OFFLINE") {
        this.extend("activity", null, d.at_ms); this.extend("source", null, d.at_ms); this.lastActivity = null;
      }
      const fb = d.fallback_reason || null;
      if (prev ? (prev.fallback_reason || null) !== fb : fb) this.addEvent(d.at_ms, "model", fb ? `Model tidak dipakai: ${fb}` : "Model aktif kembali");
      this.version++;
      return true;
    },

    pushPath(v) {
      if (v === "IDLE" && this.path[this.path.length - 1] === "DONE") this.path = [];   // siklus baru setelah konfirmasi
      if (this.path[this.path.length - 1] !== v) this.path.push(v);
      if (this.path.length > 12) this.path.shift();
    },

    extend(lane, value, at, detail) {
      const seg = this.lanes[lane], last = seg[seg.length - 1];
      if (last && last.v === value) { if (detail) last.detail = detail; return; }
      if (last && at < last.from) at = last.from;
      seg.push({ v: value, from: at, detail });
      if (seg.length > MAX_SEGMENTS) seg.shift();
    },

    setConnected(ok, now) {
      if (this.connected === ok) return;
      this.connected = ok;
      if (!ok) for (const k of Object.keys(this.lanes)) if (this.lanes[k].length) this.extend(k, null, now);
      this.addEvent(now, "conn", ok ? "Tersambung ke broker" : "Koneksi ke broker terputus");
    },

    onAlert(d, now) {
      if (!isObj(d) || typeof d.event !== "string" || typeof d.reason !== "string" || !nonneg(d.run_minutes) ||
          !Number.isInteger(d.detected_at_ms) || d.detected_at_ms <= 0) { this.ignored.invalid++; return false; }
      if (d.alert_id) {
        if (this.seenAlerts.has(d.alert_id)) { this.dupAlerts++; return false; }
        this.seenAlerts.add(d.alert_id);
      }
      const kind = d.kind || "completed_after_spin";
      const completion = COMPLETION.includes(kind);
      const open = completion && this.alerts.find((a) => a.pending);
      if (open) {
        open.lastAt = d.detected_at_ms; open.reminders += 1; open.validFor = d.valid_for_s || open.validFor;
        open.state = "pending"; open.latestReason = d.reason;
        this.addEvent(d.detected_at_ms, "alert", `Pengingat ke-${open.reminders}: ${d.reason}`);
      } else {
        this.alerts.unshift({ kind, firstAt: d.detected_at_ms, lastAt: d.detected_at_ms, reason: d.reason, run: d.run_minutes,
          reminders: 0, pending: completion, state: completion ? "pending" : "info", validFor: d.valid_for_s || 900,
          mode: this.status && this.status.effective_mode, spin: kind === "completed_after_spin" });
        this.alerts.length = Math.min(this.alerts.length, MAX_ALERTS);
        this.addEvent(d.detected_at_ms, "alert", `Alert: ${d.reason}`);
      }
      this.version++;
      return true;
    },

    onAlertState(d, now) {
      if (!isObj(d) || typeof d.active !== "boolean") { this.ignored.invalid++; return false; }
      if (d.active) return this.onAlert(d, now);
      const open = this.alerts.find((a) => a.pending);
      if (open) {
        open.pending = false;
        open.state = ["acknowledged", "superseded", "disarmed"].includes(d.ended_by) ? d.ended_by : "ended";
        open.endedAt = Number.isInteger(d.updated_at_ms) ? d.updated_at_ms : now;
        const text = { acknowledged: "Pemilik mengonfirmasi lewat HP B", superseded: "Alert digantikan koreksi: mesin aktif lagi", disarmed: "Alert dihentikan oleh DISARM", ended: "Alert berakhir" }[open.state];
        this.addEvent(open.endedAt, "alert", text);
      }
      this.version++;
      return true;
    },

    /* Pending yang tidak diperbarui melewati masa berlaku berarti detector berhenti mengingatkan. */
    expire(now) {
      for (const a of this.alerts) {
        if (a.pending && now - a.lastAt > a.validFor * 1000) { a.pending = false; a.state = "expired"; this.version++; }
      }
    },
  };

  function fmtDur(ms) {
    if (!(ms >= 0)) return null;
    const t = Math.round(ms / 1000);
    if (t < 60) return `${t} detik`;
    const m = Math.floor(t / 60);
    return m < 60 ? `${m} menit ${t % 60} detik` : `${Math.floor(m / 60)} jam ${m % 60} menit`;
  }

  window.WAStore = { create, fmtDur };
})();
