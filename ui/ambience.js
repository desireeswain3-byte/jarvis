/* Wellness sounds made right here in the browser, so they work with no internet and never get blocked.
   focus: soft brown noise with a low warm hum.  spa: slow ocean waves with a gentle pad and an occasional chime. */
(function () {
  let ctx = null, master = null, nodes = [], timers = [], current = null;

  function noise(c, kind) {
    const len = c.sampleRate * 4, buf = c.createBuffer(2, len, c.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      let last = 0, b0 = 0, b1 = 0, b2 = 0;
      for (let i = 0; i < len; i++) {
        const w = Math.random() * 2 - 1;
        if (kind === "brown") { last = (last + 0.02 * w) / 1.02; d[i] = last * 3.2; }
        else { b0 = 0.99765 * b0 + w * 0.099046; b1 = 0.963 * b1 + w * 0.2965164; b2 = 0.57 * b2 + w * 1.0526913; d[i] = (b0 + b1 + b2 + w * 0.1848) * 0.11; }
      }
    }
    const s = c.createBufferSource(); s.buffer = buf; s.loop = true; return s;
  }
  function keep(n) { nodes.push(n); return n; }
  function tone(freq, gain, type) {
    const o = keep(ctx.createOscillator()), g = keep(ctx.createGain());
    o.type = type || "sine"; o.frequency.value = freq; g.gain.value = gain;
    o.connect(g); g.connect(master); o.start(); return { o, g };
  }

  function focus() {
    const n = keep(noise(ctx, "brown")), lp = keep(ctx.createBiquadFilter()), g = keep(ctx.createGain());
    lp.type = "lowpass"; lp.frequency.value = 900; g.gain.value = 0.55;
    n.connect(lp); lp.connect(g); g.connect(master); n.start();
    tone(110, 0.035); tone(164.8, 0.02); tone(220.5, 0.012);
  }

  function spa() {
    const n = keep(noise(ctx, "pink")), lp = keep(ctx.createBiquadFilter()), g = keep(ctx.createGain());
    lp.type = "lowpass"; lp.frequency.value = 700; g.gain.value = 0.25;
    n.connect(lp); lp.connect(g); g.connect(master); n.start();
    const lfo = keep(ctx.createOscillator()), depth = keep(ctx.createGain());      // waves: swell about every 9 seconds
    lfo.frequency.value = 0.11; depth.gain.value = 0.22; lfo.connect(depth); depth.connect(g.gain); lfo.start();
    const lfo2 = keep(ctx.createOscillator()), d2 = keep(ctx.createGain());
    lfo2.frequency.value = 0.11; d2.gain.value = 450; lfo2.connect(d2); d2.connect(lp.frequency); lfo2.start();
    [130.8, 196, 261.6, 329.6].forEach((f, i) => { const t = tone(f, 0.012 - i * 0.002, "triangle"); t.o.detune.value = (i % 2 ? 4 : -4); });
    const notes = [523.3, 587.3, 659.3, 784, 880];
    const chime = () => {
      if (!ctx || current !== "spa") return;
      const o = ctx.createOscillator(), e = ctx.createGain(), t = ctx.currentTime;
      o.type = "sine"; o.frequency.value = notes[Math.floor(Math.random() * notes.length)];
      e.gain.setValueAtTime(0, t); e.gain.linearRampToValueAtTime(0.05, t + 0.02); e.gain.exponentialRampToValueAtTime(0.0001, t + 4);
      o.connect(e); e.connect(master); o.start(t); o.stop(t + 4.2);
      timers.push(setTimeout(chime, 6000 + Math.random() * 9000));
    };
    timers.push(setTimeout(chime, 3000));
  }

  function stop(fade) {
    timers.forEach(clearTimeout); timers = [];
    const old = nodes, oldMaster = master; nodes = []; master = null; current = null;
    if (!ctx || !oldMaster) return;
    const t = ctx.currentTime, f = fade == null ? 1.2 : fade;
    oldMaster.gain.cancelScheduledValues(t); oldMaster.gain.setValueAtTime(oldMaster.gain.value, t); oldMaster.gain.linearRampToValueAtTime(0, t + f);
    setTimeout(() => old.forEach((n) => { try { n.stop && n.stop(); } catch (e) { /* already stopped */ } try { n.disconnect(); } catch (e) { /* ignore */ } }), f * 1000 + 100);
  }

  function play(kind) {
    if (kind !== "focus" && kind !== "spa") { stop(); return false; }
    try { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return false; }
    if (ctx.state === "suspended") ctx.resume();
    stop(0.6);
    current = kind;
    master = ctx.createGain(); master.connect(ctx.destination);
    const t = ctx.currentTime; master.gain.setValueAtTime(0, t); master.gain.linearRampToValueAtTime(vol(), t + 2.5);
    (kind === "focus" ? focus : spa)();
    return true;
  }
  function vol() { let v = 0.6; try { const s = parseFloat(localStorage.getItem("jarvis.ambvol")); if (s >= 0 && s <= 1) v = s; } catch (e) { /* ignore */ } return v; }
  function setVolume(v) {
    try { localStorage.setItem("jarvis.ambvol", String(v)); } catch (e) { /* ignore */ }
    if (ctx && master) master.gain.setTargetAtTime(v, ctx.currentTime, 0.1);
  }
  window.Ambience = { play, stop: () => stop(), setVolume, volume: vol, playing: () => current };
})();
