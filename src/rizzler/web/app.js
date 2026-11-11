(()=>{'use strict';
const $=id=>document.getElementById(id);
const {VoiceGate,TurnFence,TimingLedger,scheduleBlock}=window.RizzlerVoice;
const s={ws:null,mode:'offline',key:'',session:false,muted:false,recording:false,
 rate:48000,ctx:null,media:null,src:null,worklet:null,pre:[],preBytes:0,recent:[],recentBytes:0,
 chunks:[],chunkBytes:0,playing:new Set(),nextAudio:0,
 request:null,history:new Map(),gate:null,fence:new TurnFence(),ledger:new TimingLedger(),
 allowSeq:0,done:false,epoch:0,reconnecting:false,reconnectTimer:null,reconnectAttempts:0,
 sessionId:(crypto.randomUUID?.()||String(Date.now())).replaceAll('-','').slice(0,48)};
const now=()=>performance.now();
const headers=()=>({'x-rizzler-key':s.key,'x-session-id':s.sessionId});
function status(p,d=''){document.body.className=p;$('phase').textContent=p[0].toUpperCase()+p.slice(1);$('detail').textContent=d}
function message(role,text,seq){const id=role+seq;let el=s.history.get(id);if(!el){document.querySelector('.empty')?.remove();el=document.createElement('article');el.className='bubble '+role;const label=document.createElement('small');label.textContent=role==='user'?'You':'Rizzler';const body=document.createElement('div');el.append(label,body);$('messages').append(el);s.history.set(id,el)}el.lastChild.textContent=text;$('messages').scrollTop=$('messages').scrollHeight}
function noteLatency(){const q=s.ledger.summary();const extra=q.n?` · Output-start proxy p50 ${q.p50} / p95 ${q.p95} / p99 ${q.p99} ms (n=${q.n})`:'';$('clientmetrics').textContent='Browser pause-to-scheduled-playback (not physically measured speaker audio)'+extra}
function stopAudio(){s.epoch++;s.fence.cancel();for(const a of s.playing){try{a.onended=null;a.stop()}catch(_){ }try{a.disconnect()}catch(_){}}s.playing.clear();s.nextAudio=0;s.allowSeq=0}
function interrupt(){const active=s.playing.size||s.request||['thinking','speaking'].includes(document.body.className);
 if(!active)return;
 stopAudio();s.request?.abort();s.request=null;
 if(s.mode==='ws'&&s.ws?.readyState===1)s.ws.send(JSON.stringify({type:'interrupt'}));
 else fetch('/api/interrupt',{method:'POST',headers:headers()}).catch(()=>{});
}
function server(msg){const seq=Number(msg.generation??s.fence.generation);
 if(!['ready','interrupted'].includes(msg.type)&&!s.fence.accepts(seq))return;
 switch(msg.type){
 case'ready':$('connection').textContent='WebSocket live';break;
 case'status':if(!s.recording)status((msg.label||'thinking').toLowerCase());break;
 case'transcript':message('user',msg.text,seq);break;
 case'assistant_text':message('assistant',msg.text,seq);break;
 case'audio_begin':s.allowSeq=seq;s.done=false;break;
 case'metrics':{const m=msg.data||{};
 $('metrics').textContent=`ASR ${m.asr_ms??'—'} ms · Gemini first text ${m.llm_first_text_ms??'—'} ms · Server first PCM ${m.post_pause_first_audio_ms??'—'} ms · Total server ${m.total_server_ms??'—'} ms`;
 s.ledger.server(seq,m.post_pause_first_audio_ms);break}
 case'done':s.done=true;if(!s.playing.size&&!s.recording)status('listening','Ask a follow-up.');break;
 case'error':s.ledger.cancel(seq);stopAudio();status('error',msg.message||'Voice turn failed');break;
 }}
function playback(samples,seq,rate=24000){if(!s.fence.accepts(seq)||seq!==s.allowSeq||s.recording||!s.ctx||!samples.length)return;
 const epoch=s.epoch,ctx=s.ctx,buffer=ctx.createBuffer(1,samples.length,rate),arr=buffer.getChannelData(0);
 for(let i=0;i<samples.length;i++)arr[i]=samples[i]/32768;
 const node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);
 const timeline=scheduleBlock(ctx.currentTime,s.nextAudio,buffer.duration);s.nextAudio=timeline.end;s.playing.add(node);
 if(s.ledger.turns.get(seq)?.output===null){ // Scheduling-based estimate; physical first audible requires loopback.
   const estimated=now()+Math.max(0,timeline.start-ctx.currentTime)*1000;
   s.ledger.output(seq,estimated);
   const value=s.ledger.complete(seq);
   if(value!==null)noteLatency();
 }
 node.onended=()=>{s.playing.delete(node);node.disconnect();if(epoch===s.epoch&&s.done&&!s.playing.size&&!s.recording)status('listening','Ask a follow-up.')};
 node.start(timeline.start);
 if(epoch===s.epoch)status('speaking','Speak to interrupt.');
}
function wsAudio(raw){if(raw.byteLength<6||raw.byteLength%2!==0)return;const seq=new DataView(raw).getUint32(0,true);if(!s.fence.accepts(seq))return;playback(new Int16Array(raw,4),seq)}
function concat(parts){const size=parts.reduce((n,x)=>n+x.length,0),out=new Uint8Array(size);let pos=0;for(const x of parts){out.set(x,pos);pos+=x.length}return out}
async function httpTurn(parts,seq){const bytes=concat(parts),ctrl=new AbortController();s.request=ctrl;
 try{const res=await fetch('/api/turn',{method:'POST',headers:{...headers(),'x-sample-rate':String(s.rate),'content-type':'application/octet-stream'},body:bytes,signal:ctrl.signal});
 if(!res.ok)throw Error('HTTP '+res.status);const m=await res.json();if(!s.fence.accepts(seq))return;
 server({type:'transcript',text:m.transcript,generation:seq});
 server({type:'assistant_text',text:m.answer,generation:seq});
 server({type:'metrics',data:m.metrics,generation:seq});
 s.allowSeq=seq;s.done=true;
 const pcm=Uint8Array.from(atob(m.audio_b64),c=>c.charCodeAt(0));
 if(!pcm.length||pcm.length%2)throw Error('Invalid response PCM');
 playback(new Int16Array(pcm.buffer),seq,m.sample_rate);
 }catch(e){if(e.name!=='AbortError'&&s.fence.accepts(seq)){s.ledger.cancel(seq);status('error','Request failed: '+e.message)}}
 finally{if(s.request===ctrl)s.request=null}}
function sendWs(msg){if(s.mode!=='ws'||s.ws?.readyState!==1)return false;s.ws.send(JSON.stringify(msg));return true}
function start(manual=false){if(s.recording||s.muted||!s.session)return;
 interrupt();const seq=s.fence.next();const initial=manual?s.recent:s.pre;
 s.recording=true;s.chunks=initial.slice();s.chunkBytes=initial.reduce((n,x)=>n+x.length,0);s.done=false;
 if(sendWs({type:'speech_start',generation:seq}))for(const x of initial){if(s.ws.bufferedAmount<256000)s.ws.send(x)}
 status('listening','Capturing speech…');
}
function finish(){if(!s.recording)return;s.recording=false;
 const seq=s.fence.generation,bytes=s.chunks,chunksLen=s.chunkBytes;
 s.chunks=[];s.chunkBytes=0;s.gate.reset();
 if(chunksLen<s.rate*.35*2){sendWs({type:'interrupt'});status('listening','Speech too short.');return}
 s.allowSeq=seq;s.done=false;s.ledger.begin(seq,now());status('thinking','Transcribing and generating…');
 if(!sendWs({type:'speech_end',generation:seq}))httpTurn(bytes,seq);
}
function onSamples(samples){if(!s.session||s.muted)return;
 const raw=new Uint8Array(samples.buffer.slice(samples.byteOffset,samples.byteOffset+samples.byteLength));
 const elapsed=samples.length/s.rate*1000;
 let sum=0;for(let i=0;i<samples.length;i+=3)sum+=(samples[i]/32768)**2;
 const rms=Math.sqrt(sum/Math.ceil(samples.length/3));
 // Feed before retaining the current block so pre-roll is not sent twice.
 const action=s.gate.feed(rms,elapsed,s.playing.size>0);
 if(action==='start')start();
 if(s.recording){
   s.chunks.push(raw);s.chunkBytes+=raw.length;
   if(s.mode==='ws'&&s.ws?.readyState===1){
     if(s.ws.bufferedAmount<256000)s.ws.send(raw);
     else { // Never transmit a partial voice turn as a complete utterance.
       sendWs({type:'interrupt'});s.mode='http';$('connection').textContent='HTTPS fallback (network congestion)';
     }
   }
 }
 s.recent.push(raw);s.recentBytes+=raw.length;
 while(s.recentBytes>s.rate*2*3&&s.recent.length){s.recentBytes-=s.recent.shift().length}
 s.pre.push(raw);s.preBytes+=raw.length;
 const maxPre=Math.floor(s.rate*2*.30);
 while(s.preBytes>maxPre&&s.pre.length){s.preBytes-=s.pre.shift().length}
 if(action==='end'||(s.recording&&s.chunkBytes>=s.rate*2*22))finish();
}
function setFallback(label){s.mode='http';$('connection').textContent=label;status('listening','HTTPS mode active.')}
function connectWs(){return new Promise((resolve,reject)=>{
 const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
 s.ws=ws;ws.binaryType='arraybuffer';let ready=false;
 const timeout=setTimeout(()=>{if(!ready){ws.close();reject(Error('WebSocket timeout'))}},6000);
 ws.onopen=()=>ws.send(JSON.stringify({type:'auth',token:s.key,client_id:s.sessionId,sample_rate:s.rate}));
 ws.onmessage=e=>{if(ws!==s.ws)return;
 if(typeof e.data==='string'){let m;try{m=JSON.parse(e.data)}catch(_){return}
 if(m.type==='ready'&&!ready){ready=true;clearTimeout(timeout);s.reconnectAttempts=0;resolve()}
 server(m);
 }else wsAudio(e.data)};
 ws.onclose=()=>{if(!ready){clearTimeout(timeout);reject(Error('WebSocket unavailable'))}
 else if(s.session&&ws===s.ws){
   if(s.recording){s.mode='http';$('connection').textContent='HTTPS fallback (connection interrupted)'}
   else {stopAudio();s.ledger.cancel(s.fence.generation);setFallback('HTTPS fallback');scheduleReconnect()}
 }};
 ws.onerror=()=>{};
 })}
function scheduleReconnect(){if(s.reconnecting||!s.session||s.recording||s.reconnectAttempts>=5)return;
 s.reconnecting=true;const delay=Math.min(15000,1000*2**s.reconnectAttempts++);
 s.reconnectTimer=setTimeout(async()=>{s.reconnecting=false;if(!s.session||s.recording||s.mode==='ws')return;
 try{await connectWs();s.mode='ws';$('connection').textContent='WebSocket restored'}
 catch(_){scheduleReconnect()}},delay);
}
async function openMic(){
 const media=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
 s.media=media;const ctx=new AudioContext({latencyHint:'interactive'});s.ctx=ctx;await ctx.resume();s.rate=ctx.sampleRate;
 s.gate=new VoiceGate(s.rate);await ctx.audioWorklet.addModule('/static/capture.js');
 const source=ctx.createMediaStreamSource(media),worklet=new AudioWorkletNode(ctx,'rizzler-capture');
 worklet.port.onmessage=e=>onSamples(e.data);const silent=ctx.createGain();silent.gain.value=0;
 source.connect(worklet);worklet.connect(silent);silent.connect(ctx.destination);
 s.src=source;s.worklet=worklet;
 media.getAudioTracks().forEach(track=>track.addEventListener('ended',()=>{if(s.session){stopAudio();setFallback('Microphone disconnected');status('error','Microphone ended; reconnect to restore capture')}}));
}
async function disconnect(){s.session=false;s.recording=false;clearTimeout(s.reconnectTimer);s.reconnecting=false;
 stopAudio();s.ledger.cancel(s.fence.generation);s.request?.abort();s.ws?.close();s.media?.getTracks().forEach(t=>t.stop());
 await s.ctx?.close();s.ctx=null;s.mode='offline';$('connection').textContent='Disconnected';status('offline','Session ended');
 $('connect').textContent='Connect microphone';for(const id of ['mute','send','reset'])$(id).disabled=true;
}
$('unlock').addEventListener('submit',async e=>{
 e.preventDefault();s.key=$('key').value;
 try{const r=await fetch('/api/auth',{method:'POST',headers:headers()});if(!r.ok)throw Error('Invalid access key');
 if(!window.isSecureContext)throw Error('Microphone requires HTTPS or localhost');
 await openMic();try{await connectWs();s.mode='ws'}catch(_){setFallback('HTTPS fallback')}
 s.session=true;$('modal').classList.add('hidden');$('connect').textContent='Disconnect';
 for(const id of ['mute','send','reset'])$(id).disabled=false;
 status('listening','Ready. Speak naturally.');noteLatency();
 if(s.mode==='http')scheduleReconnect();
 }catch(err){$('error').textContent=err.message;s.media?.getTracks().forEach(t=>t.stop());await s.ctx?.close();s.ctx=null}});
$('connect').addEventListener('click',()=>s.session?disconnect():$('modal').classList.remove('hidden'));
$('mute').addEventListener('click',()=>{s.muted=!s.muted;$('mute').textContent=s.muted?'Unmute':'Mute';
 if(s.muted){interrupt();s.recording=false;s.gate.reset();status('muted','Microphone muted')}else status('listening','Speak naturally')});
$('send').addEventListener('click',()=>{if(s.recording){finish();return}if(s.recentBytes<s.rate*2*.35)return;
 start(true);finish()});
$('reset').addEventListener('click',async()=>{interrupt();s.history.clear();$('messages').replaceChildren();s.ledger.cancel(s.fence.generation);
 if(!sendWs({type:'new_conversation'}))await fetch('/api/reset',{method:'POST',headers:headers()}).catch(()=>{});
 status('listening','New conversation')});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&s.session&&s.ctx?.state==='suspended')s.ctx.resume().catch(()=>{})});
window.addEventListener('pagehide',()=>{s.ws?.close();s.media?.getTracks().forEach(t=>t.stop())});
})();
