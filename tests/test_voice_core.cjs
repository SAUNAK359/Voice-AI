'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {VoiceGate, TurnFence, TimingLedger, scheduleBlock} =
  require('../src/rizzler/web/voice-core.js');

test('adaptive speech gate detects onset and closes after stable silence', () => {
  const g = new VoiceGate(48000, 22);
  for (let i = 0; i < 30; i++) assert.equal(g.feed(0.002, 20), null);
  let started = false;
  for (let i = 0; i < 10; i++) if (g.feed(0.08, 20) === 'start') started = true;
  assert.ok(started);
  let ended = false;
  for (let i = 0; i < 30; i++) if (g.feed(0.001, 20) === 'end') ended = true;
  assert.ok(ended);
});

test('noise does not start a turn; hard maximum duration stops a continuous utterance', () => {
  const g = new VoiceGate(48000, 1);
  for (let i = 0; i < 20; i++) g.feed(0.002, 20);
  assert.equal(g.active, false);
  let ended = false;
  for (let i = 0; i < 90; i++) if (g.feed(0.3, 20) === 'end') { ended = true; break; }
  assert.ok(ended);
});

test('turn fence rejects stale generations and epochs', () => {
  const f = new TurnFence();
  const one = f.next(), oldEpoch = f.epoch;
  assert.ok(f.accepts(one, oldEpoch));
  f.cancel();
  assert.ok(!f.accepts(one, oldEpoch));
  const two = f.next();
  assert.ok(f.accepts(two));
  assert.ok(!f.accepts(one));
});

test('playback timeline is monotonic and never schedules overlapping chunks', () => {
  const a = scheduleBlock(10, 0, 0.04);
  const b = scheduleBlock(10.01, a.end, 0.04);
  assert.ok(b.start >= a.end);
  assert.equal(Math.round((b.end - b.start) * 100), 4);
  assert.throws(() => scheduleBlock(0, 0, -1));
});

test('latency ledger records output-start proxy, calculates nearest-rank percentiles', () => {
  const l = new TimingLedger(3);
  for (const [seq, elapsed] of [[1, 100], [2, 200], [3, 300], [4, 400]]) {
    l.begin(seq, 1000);
    l.output(seq, 1000 + elapsed);
    assert.equal(l.complete(seq), elapsed);
  }
  assert.deepEqual(l.summary(), {n: 3, p50: 300, p95: 400, p99: 400});
  l.begin(8, 100);
  l.cancel(8);
  assert.equal(l.complete(8), null);
});
