/* Pure voice timing, utterance detection, and generation fences.
   Node's built-in test runner exercises this same browser module. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RizzlerVoice = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  class VoiceGate {
    constructor(rate, maxSeconds = 22) {
      this.rate = rate; this.maxMs = maxSeconds * 1000;
      this.noise = 0.003; this.armed = true; this.reset();
    }
    reset() { this.speechMs = 0; this.silenceMs = 0; this.elapsedMs = 0; this.active = false; }
    feed(rms, ms, isSpeaking = false) {
      if (!Number.isFinite(rms) || !Number.isFinite(ms) || ms <= 0) return null;
      const level = Math.max(0, Math.min(1, rms));
      const threshold = Math.max(0.010, this.noise * 3.3, isSpeaking ? 0.032 : 0);
      const voiced = level >= threshold;
      if (!this.active) {
        if (!voiced) this.noise = this.noise * 0.98 + level * 0.02;
        this.speechMs = voiced ? this.speechMs + ms : Math.max(0, this.speechMs - ms * 1.5);
        if (this.speechMs >= 170) {
          this.active = true; this.elapsedMs = this.speechMs;
          this.silenceMs = 0; return 'start';
        }
        return null;
      }
      this.elapsedMs += ms;
      this.silenceMs = voiced ? 0 : this.silenceMs + ms;
      if (this.elapsedMs >= this.maxMs || (this.elapsedMs >= 360 && this.silenceMs >= 520)) {
        this.reset(); return 'end';
      }
      return null;
    }
  }
  class TurnFence {
    constructor() { this.generation = 0; this.epoch = 0; }
    next() { this.generation += 1; this.epoch += 1; return this.generation; }
    cancel() { this.generation += 1; this.epoch += 1; }
    accepts(sequence, epoch) {
      return Number.isSafeInteger(sequence) && sequence === this.generation &&
        (epoch === undefined || epoch === this.epoch);
    }
  }
  class TimingLedger {
    constructor(limit = 200) { this.limit = limit; this.turns = new Map(); this.samples = []; }
    begin(seq, at) { this.turns.set(seq, {pause: at, output: null, server: null}); }
    output(seq, at) {
      const row = this.turns.get(seq);
      if (row && row.output === null && at >= row.pause) row.output = at;
    }
    server(seq, value) {
      const row = this.turns.get(seq);
      if (row && Number.isFinite(value) && value >= 0) row.server = value;
    }
    complete(seq) {
      const row = this.turns.get(seq); this.turns.delete(seq);
      if (!row || row.output === null) return null;
      const elapsed = Math.round((row.output - row.pause) * 10) / 10;
      if (!Number.isFinite(elapsed) || elapsed < 0) return null;
      this.samples.push(elapsed);
      if (this.samples.length > this.limit) this.samples.shift();
      return elapsed;
    }
    cancel(seq) { this.turns.delete(seq); }
    summary() {
      const values = this.samples.slice().sort((a, b) => a - b);
      const rank = p => values.length ? values[Math.ceil(values.length * p / 100) - 1] : null;
      return {n: values.length, p50: rank(50), p95: rank(95), p99: rank(99)};
    }
  }
  function scheduleBlock(now, previousEnd, duration, lead = 0.045) {
    if (![now, previousEnd, duration, lead].every(Number.isFinite) || duration <= 0)
      throw new RangeError('Invalid audio timeline');
    const start = Math.max(now + lead, previousEnd);
    return {start, end: start + duration};
  }
  return {VoiceGate, TurnFence, TimingLedger, scheduleBlock};
});
