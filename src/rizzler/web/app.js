(()=>{'use strict';
const $=id=>document.getElementById(id);
const s={ws:null,mode:'offline',key:'',session:false,muted:false,recording:false,seq:0,rate:48000,
 ctx:null,media:null,src:null,worklet:null,pre:[],bytes:[],recent:[],recentBytes:0,
 quiet:0,voiced:0,noise:.003,playing:new Set(),nextAudio:0,allowSeq:0,done:false,
 request:null,history:new Map(),sessionId:(crypto.randomUUID?.()||String(Date.now())).replaceAll('-','').slice(0,48)};
function status(p,d=''){document.body.className=p;$('phase').textContent=p[0].toUpperCase()+p.slice(1);$('detail').textContent=d}
function message(role,text,seq){const id=role+seq;let el=s.history.get(id);if(!el){document.querySelector('.empty')?.remove();el=document.createElement('article');el.className='bubble '+role;const label=document.createElement('small');label.textContent=role==='user'?'You':'Rizzler';const body=document.createElement('div');el.append(label,body);$('messages').append(el);s.history.set(id,el)}el.lastChild.textContent=text;$('messages').scrollTop=$('messages').scrollHeight}
function stopAudio(){for(const a of s.playing){try{a.stop()}catch(_){}}s.playing.clear();s.nextAudio=0;s.allowSeq=0}
function barge(){if(s.playing.size||s.request||document.body.className==='thinking'){stopAudio();s.request?.abort();s.request=null;if(s.mode==='ws'&&s.ws?.readyState===1)s.ws.send(JSON.stringify({type:'interrupt'}));else fetch('/api/interrupt',{method:'POST',headers:headers()}).catch(()=>{})}}
const headers=()=>({'x-rizzler-key':s.key,'x-session-id':s.sessionId});
function server(msg){const seq=Number(msg.generation??s.seq);if(!['ready','interrupted'].includes(msg.type)&&seq!==s.seq)return;
 switch(msg.type){case'ready':$('connection').textContent='WebSocket live';break;
 case'status':status(msg.label?.toLowerCase()||'thinking');break;
 case'transcript':message('user',msg.text,seq);break;
 case'assistant_text':message('assistant',msg.text,seq);break;
 case'audio_begin':s.allowSeq=seq;s.done=false;break;
 case'metrics':{const m=msg.data||{};$('metrics').textContent=`ASR: ${m.asr_ms??'—'} ms · Gemini TTFT: ${m.llm_first_text_ms??'—'} ms · First server PCM: ${m.post_pause_first_audio_ms??'—'} ms · Total server: ${m.total_server_ms??'—'} ms. Not browser-audible timing.`;break}
 case'done':s.done=true;if(!s.playing.size)status('listening','Ask a follow-up.');break;
 case'error':status('error',msg.message||'Turn failed');break;
 }
}
function playback(samples,seq,rate=24000){if(seq!==s.allowSeq||s.recording||!s.ctx)return;
 const audio=s.ctx.createBuffer(1,samples.length,rate),arr=audio.getChannelData(0);
 for(let i=0;i<samples.length;i++)arr[i]=samples[i]/32768;
 const node=s.ctx.createBufferSource();node.buffer=audio;node.connect(s.ctx.destination);
 const begin=Math.max(s.nextAudio,s.ctx.currentTime+.06);s.nextAudio=begin+audio.duration;s.playing.add(node);
 node.onended=()=>{s.playing.delete(node);node.disconnect();if(s.done&&!s.playing.size&&!s.recording)status('listening','Ask a follow-up.')};node.start(begin);status('speaking','You can interrupt with your voice.')
}
function wsAudio(raw){if(raw.byteLength<6)return;const gen=new DataView(raw).getUint32(0,true);playback(new Int16Array(raw,4),gen)}
async function connectWs(){return new Promise((resolve,reject)=>{const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);s.ws=ws;ws.binaryType='arraybuffer';let ready=false;const timer=setTimeout(()=>{if(!ready){ws.close();reject(Error('Connection timeout'))}},6000);
 ws.onopen=()=>ws.send(JSON.stringify({type:'auth',token:s.key,client_id:s.sessionId,sample_rate:s.rate}));
 ws.onmessage=e=>{if(typeof e.data==='string'){let m;try{m=JSON.parse(e.data)}catch(_){return};if(m.type==='ready'&&!ready){ready=true;clearTimeout(timer);resolve()}server(m)}else wsAudio(e.data)};
 ws.onclose=()=>{if(!ready){clearTimeout(timer);reject(Error('WebSocket unavailable'))}else if(s.session){s.mode='http';$('connection').textContent='HTTPS fallback'}};
 ws.onerror=()=>{};
 })}
function concat(parts){const size=parts.reduce((n,x)=>n+x.length,0),out=new Uint8Array(size);let pos=0;for(const x of parts){out.set(x,pos);pos+=x.length}return out}
async function httpTurn(parts,seq){const data=concat(parts);const ctrl=new AbortController();s.request=ctrl;try{const res=await fetch('/api/turn',{method:'POST',headers:{...headers(),'x-sample-rate':String(s.rate),'content-type':'application/octet-stream'},body:data,signal:ctrl.signal});if(!res.ok)throw Error('HTTP '+res.status);const m=await res.json();if(seq!==s.seq)return;server({type:'transcript',text:m.transcript,generation:seq});server({type:'assistant_text',text:m.answer,generation:seq});server({type:'metrics',data:m.metrics,generation:seq});s.allowSeq=seq;s.done=true;const bytes=Uint8Array.from(atob(m.audio_b64),c=>c.charCodeAt(0));playback(new Int16Array(bytes.buffer),seq,m.sample_rate);if(!bytes.length)status('error','No speech returned')}catch(e){if(e.name!=='AbortError')status('error',e.message)}finally{if(s.request===ctrl)s.request=null}}
function start(){if(s.recording||s.muted)return;barge();s.seq++;s.recording=true;s.voiced=0;s.quiet=0;s.bytes=s.pre.slice();if(s.mode==='ws'){s.ws.send(JSON.stringify({type:'speech_start',generation:s.seq}));for(const x of s.pre)if(s.ws.bufferedAmount<256000)s.ws.send(x)}status('listening','Capturing speech…')}
function finish(){if(!s.recording)return;s.recording=false;const chunks=s.bytes;s.bytes=[];s.voiced=0;s.quiet=0;const length=chunks.reduce((n,x)=>n+x.length,0);if(length<s.rate*.35*2){if(s.mode==='ws')s.ws.send(JSON.stringify({type:'interrupt'}));status('listening','Speech too short.');return};s.allowSeq=s.seq;s.done=false;status('thinking','Transcribing and generating…');if(s.mode==='ws')s.ws.send(JSON.stringify({type:'speech_end',generation:s.seq}));else httpTurn(chunks,s.seq)}
function onSamples(pcm){if(!s.session||s.muted)return;const x=pcm instanceof Int16Array?pcm:new Int16Array(pcm),raw=new Uint8Array(x.buffer.slice(0));s.pre.push(raw);if(s.pre.length>12)s.pre.shift();s.recent.push(raw);s.recentBytes+=raw.length;while(s.recentBytes>s.rate*2*3){s.recentBytes-=s.recent.shift().length}
 if(s.mode==='ws'&&s.recording&&s.ws?.readyState===1&&s.ws.bufferedAmount<256000)s.ws.send(raw);
 let pow=0;for(let i=0;i<x.length;i+=3)pow+=(x[i]/32768)**2;const rms=Math.sqrt(pow/Math.ceil(x.length/3));const threshold=Math.max(.012,s.noise*3.2,document.body.className==='speaking'?.028:0),active=rms>threshold,elapsed=x.length/s.rate*1000;
 if(!s.recording){if(!active)s.noise=s.noise*.99+rms*.01;s.voiced=active?s.voiced+elapsed:Math.max(0,s.voiced-elapsed);if(s.voiced>160)start()}
 else{s.bytes.push(raw);s.quiet=active?0:s.quiet+elapsed;if(s.quiet>430)finish();if(s.bytes.length>4500)finish()}
}
async function openMic(){s.ctx=new AudioContext({latencyHint:'interactive'});await s.ctx.resume();s.rate=s.ctx.sampleRate;s.media=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
 await s.ctx.audioWorklet.addModule('/static/capture.js');s.src=s.ctx.createMediaStreamSource(s.media);s.worklet=new AudioWorkletNode(s.ctx,'rizzler-capture');s.worklet.port.onmessage=e=>onSamples(e.data);const silent=s.ctx.createGain();silent.gain.value=0;s.src.connect(s.worklet);s.worklet.connect(silent);silent.connect(s.ctx.destination)}
async function disconnect(){s.session=false;s.recording=false;stopAudio();s.request?.abort();s.ws?.close();s.media?.getTracks().forEach(t=>t.stop());await s.ctx?.close();s.ctx=null;s.mode='offline';$('connection').textContent='Disconnected';status('offline','Session ended');$('connect').textContent='Connect microphone';for(const id of ['mute','send','reset'])$(id).disabled=true}
$('unlock').addEventListener('submit',async e=>{e.preventDefault();s.key=$('key').value;try{const r=await fetch('/api/auth',{method:'POST',headers:headers()});if(!r.ok)throw Error('Invalid access key');if(!window.isSecureContext)throw Error('Microphone requires HTTPS or localhost');await openMic();try{await connectWs();s.mode='ws'}catch(_){s.mode='http';$('connection').textContent='HTTPS fallback'}s.session=true;$('modal').classList.add('hidden');$('connect').textContent='Disconnect';for(const id of ['mute','send','reset'])$(id).disabled=false;status('listening','Ready. Speak naturally.')}catch(err){$('error').textContent=err.message;s.media?.getTracks().forEach(t=>t.stop());await s.ctx?.close();s.ctx=null}});
$('connect').addEventListener('click',()=>s.session?disconnect():$('modal').classList.remove('hidden'));
$('mute').addEventListener('click',()=>{s.muted=!s.muted;$('mute').textContent=s.muted?'Unmute':'Mute';if(s.muted){barge();s.recording=false;status('muted','Microphone muted')}else status('listening','Speak naturally')});
$('send').addEventListener('click',()=>{if(s.recording){finish();return}if(!s.recent.length)return;start();s.bytes=s.recent.slice();if(s.mode==='ws')for(const x of s.bytes)if(s.ws.bufferedAmount<256000)s.ws.send(x);finish()});
$('reset').addEventListener('click',async()=>{barge();s.history.clear();$('messages').replaceChildren();if(s.mode==='ws')s.ws.send(JSON.stringify({type:'new_conversation'}));else await fetch('/api/reset',{method:'POST',headers:headers()}).catch(()=>{});status('listening','New conversation')});
window.addEventListener('pagehide',()=>{s.ws?.close();s.media?.getTracks().forEach(t=>t.stop())});
})();
