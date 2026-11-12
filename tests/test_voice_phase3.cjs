'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {VoiceFrames,PlaybackBudget,TurnFence,VoiceGate,TimingLedger} =
  require('../src/rizzler/web/voice-core.js');

test('versioned input frames carry ordered generation, timestamp and samples',()=>{
  const frames = new VoiceFrames(48000);
  const raw = new Int16Array(1024).fill(16000);
  const packet = frames.input(raw,9);
  const d = new DataView(packet);
  assert.equal(d.getUint32(0,true),0x32565a52);
  assert.equal(d.getUint32(4,true),9);
  assert.equal(d.getUint32(8,true),0);
  assert.equal(d.getUint32(16,true),1024);
  assert.equal(new Int16Array(packet,20)[100],16000);
  assert.equal(new DataView(frames.input(raw,9)).getUint32(8,true),1);
  assert.throws(()=>frames.input(new Int16Array(3000),9));
  assert.throws(()=>frames.input(raw,-1));
  assert.throws(()=>frames.input(new Int16Array(0),9));
  frames.reset();
  assert.equal(new DataView(frames.input(raw,10)).getUint32(8,true),0);
});

test('output packets reject replay, wrong PCM rate and malformed payload',()=>{
  const f = new VoiceFrames(16000);
  function pkt(seq,rate=24000){
    const b=new ArrayBuffer(16+480);
    const d=new DataView(b);
    d.setUint32(0,0x324f5a52,true);
    d.setUint32(4,7,true);
    d.setUint32(8,seq,true);
    d.setUint32(12,rate,true);
    return b;
  }
  assert.equal(f.output(pkt(0)).generation,7);
  assert.equal(f.output(pkt(1)).samples.length,240);
  assert.throws(()=>f.output(pkt(1)));
  f.reset();
  assert.throws(()=>f.output(pkt(0,16000)));
  assert.throws(()=>f.output(new ArrayBuffer(0)));
});

test('playback limit prevents unbounded scheduling',()=>{
  const budget = new PlaybackBudget(5);
  assert.ok(budget.accepts(10,11,2));
  assert.ok(!budget.accepts(10,14.9,2));
  assert.ok(!budget.accepts(NaN,12,2));
});

test('interruption fences stale audio across 100 generations',()=>{
  const fence=new TurnFence(),frames=new VoiceFrames(48000);
  for(let i=0;i<100;i++){
    const seq=fence.next();
    const encoded=frames.input(new Int16Array(1024),seq);
    assert.equal(new DataView(encoded).getUint32(4,true),seq);
    fence.cancel();frames.reset();
    assert.ok(!fence.accepts(seq));
  }
});

test('adaptive gate does not trigger on quiet noise or nonfinite levels',()=>{
  const gate = new VoiceGate(48000);
  for(let i=0;i<100;i++)assert.equal(gate.feed(0.001,20,true),null);
  assert.equal(gate.feed(Infinity,20,true),null);
  assert.equal(gate.active,false);
});
