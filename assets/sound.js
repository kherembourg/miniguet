/* Miniguet sound: soft chimes (Web Audio, synthesized) + optional looping background music.
   - The two switches (chimes, music) are remembered in localStorage and survive reloads.
   - Browsers refuse sound before a first tap on the page: when a switch is ON but the browser blocks it,
     state() reports "locked" and the next tap anywhere unlocks it, no need to press the button again.
   - Chimes are a separate audio path from the music: a chime plays on top, the music is never cut. */
(function () {
  const MG = (window.MG = window.MG || {});
  const K = { sound: "mg_sound", music: "mg_music" };
  const MUSIC_SRC = "/assets/ambient.mp3", MUSIC_VOL = 0.3, CHIME_VOL = 0.4, DUCK = 0.35;   // music drops to 35% for a moment under a chime, then comes back
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  };
  let ctx = null, music = null, listeners = [], lockedChime = false, lockedMusic = false, lastChime = null;

  const on = (k) => store.get(k) === "on";
  const emit = () => listeners.forEach((f) => { try { f(); } catch (e) {} });
  function audioCtx() {
    if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { ctx = null; } }
    return ctx;
  }
  async function ready() {   // true when the browser lets us make sound now
    const c = audioCtx();
    if (!c) return false;
    if (c.state !== "running") { try { await c.resume(); } catch (e) {} }
    return c.state === "running";
  }
  // one soft note: sine + quiet octave, quick attack, long exponential decay, low-passed
  function note(c, t0, freq, dur, type, vol) {
    const g = c.createGain(), lp = c.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 5200;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    [[freq, 1, type || "sine"], [freq * 2, 0.18, "sine"]].forEach(([f, k, ty]) => {
      const o = c.createOscillator(), og = c.createGain();
      o.type = ty; o.frequency.value = f; og.gain.value = k;
      o.connect(og); og.connect(g); o.start(t0); o.stop(t0 + dur + 0.05);
    });
    g.connect(lp); lp.connect(c.destination);
  }
  const SHAPES = {   // [frequency Hz, offset s, duration s]
    new:      { n: [[659.3, 0, 1.0], [880, 0.16, 1.4]], type: "sine" },              // a session now waits for you
    deadline: { n: [[523.3, 0, 0.9], [659.3, 0.15, 0.9], [784, 0.3, 1.5]], type: "sine" },
    error:    { n: [[392, 0, 1.0], [293.7, 0.2, 1.5]], type: "triangle" },
    wake:     { n: [[880, 0, 1.2]], type: "sine" },                                  // a snoozed session is back
  };
  async function chime(kind) {
    if (!on(K.sound)) return false;
    if (!(await ready())) { lockedChime = true; emit(); armUnlock(); return false; }
    const c = ctx, s = SHAPES[kind] || SHAPES.new, t = c.currentTime + 0.02;
    s.n.forEach(([f, off, d]) => note(c, t + off, f, d, s.type, CHIME_VOL));
    lastChime = { at: Date.now(), kind, ctx: c.state };
    duck(1800);
    emit();
    return true;
  }
  let duckTimer = null;
  function duck(ms) {   // lower the music under the chime so it is heard, then restore it smoothly
    if (!music || music.paused) return;
    clearInterval(duckTimer);
    music.volume = MUSIC_VOL * DUCK;
    const t0 = Date.now() + ms * 0.4;
    duckTimer = setInterval(() => {
      const k = Math.min(1, Math.max(0, (Date.now() - t0) / (ms * 0.6)));
      music.volume = MUSIC_VOL * (DUCK + (1 - DUCK) * k);
      if (k >= 1) clearInterval(duckTimer);
    }, 60);
  }
  function getMusic() {
    if (!music) { music = new Audio(MUSIC_SRC); music.loop = true; music.volume = MUSIC_VOL; music.preload = "auto"; }
    return music;
  }
  async function startMusic() {
    try { await getMusic().play(); lockedMusic = false; emit(); return true; }
    catch (e) { lockedMusic = true; emit(); armUnlock(); return false; }
  }
  function armUnlock() {   // first tap/key anywhere: retry whatever the browser blocked
    if (armUnlock.armed) return; armUnlock.armed = true;
    const go = async () => {
      armUnlock.armed = false;
      ["pointerdown", "keydown", "touchstart"].forEach((e) => document.removeEventListener(e, go, true));
      if (on(K.sound)) { if (await ready()) { lockedChime = false; } }
      if (on(K.music)) await startMusic();
      emit();
    };
    ["pointerdown", "keydown", "touchstart"].forEach((e) => document.addEventListener(e, go, true));
  }

  MG.sound = {
    soundOn: () => on(K.sound),
    musicOn: () => on(K.music),
    /* "off" | "on" | "locked" (switched on, waiting for a first tap) */
    soundState: () => (!on(K.sound) ? "off" : lockedChime ? "locked" : "on"),
    musicState: () => (!on(K.music) ? "off" : lockedMusic ? "locked" : "on"),
    chime,
    async toggleSound() {
      if (on(K.sound)) { store.set(K.sound, "off"); lockedChime = false; emit(); return; }
      store.set(K.sound, "on");               // called from a tap: the browser allows sound now
      lockedChime = !(await ready()); emit();
      if (!lockedChime) chime("wake");          // short confirmation
    },
    async toggleMusic() {
      if (on(K.music)) { store.set(K.music, "off"); lockedMusic = false; if (music) music.pause(); emit(); return; }
      store.set(K.music, "on"); await startMusic();
    },
    onChange(f) { listeners.push(f); },
    debug: () => ({ ctx: ctx && ctx.state, lockedChime, lockedMusic, lastChime }),   // shown in the bell's tooltip
    /* call once at page load: re-applies what was switched on before the reload */
    async restore() {
      if (on(K.sound)) { lockedChime = !(await ready()); if (lockedChime) armUnlock(); }
      if (on(K.music)) await startMusic();
      emit();
    },
  };
})();
