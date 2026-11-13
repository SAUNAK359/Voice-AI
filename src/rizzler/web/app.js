(()=>{'use strict';
const $=id=>document.getElementById(id);
const {VoiceGate,TurnFence,TimingLedger,scheduleBlock,VoiceFrames,PlaybackBudget}=window.RizzlerVoice;
const s={ws:null,mode:'offline',key:'',production:false,session:false,muted:false,recording:false,
 rate:48000,ctx:null,media:null,src:null,worklet:null,pre:[],preBytes:0,recent:[],recentBytes:0,
 chunks:[],chunkBytes:0,playing:new Set(),nextAudio:0,
 request:null,history:new Map(),gate:null,fence:new TurnFence(),ledger:new TimingLedger(),
 allowSeq:0,done:false,epoch:0,reconnecting:false,reconnectTimer:null,reconnectAttempts:0,
 protocol:1,frames:null,budget:new PlaybackBudget(),deviceListener:null,
 memoryEnabled:false,workEnabled:false,visualEnabled:false,visualIDs:[],visualAnalysis:null,pdfDocs:[],pdfSelected:null,pdfPoll:null,visualSeq:100000,sessionId:(crypto.randomUUID?.()||String(Date.now())).replaceAll('-','').slice(0,48)};
const now=()=>performance.now();
const csrf=()=>document.cookie.split('; ').find(x=>x.startsWith('rizzler_csrf='))?.split('=').slice(1).join('=')||'';
const headers=()=>s.production?{'x-csrf-token':decodeURIComponent(csrf())}:
  {'x-rizzler-key':s.key,'x-session-id':s.sessionId};
function status(p,d=''){document.body.className=p;$('phase').textContent=p[0].toUpperCase()+p.slice(1);$('detail').textContent=d}
function message(role,text,seq,final=false){const id=role+seq;let el=s.history.get(id);if(!el){document.querySelector('.empty')?.remove();el=document.createElement('article');el.className='bubble '+role;const label=document.createElement('small');label.textContent=role==='user'?'You':'Rizzler';const body=document.createElement('div');el.append(label,body);$('messages').append(el);s.history.set(id,el)}if(role==='assistant'&&window.RizzlerRich&&final){window.RizzlerRich.render(el.lastChild,text)}else if(role==='assistant'){el.lastChild.textContent=window.RizzlerRich?window.RizzlerRich.latex(text.replace(/\\\(|\\\)|\$/g,'')):text}else el.lastChild.textContent=text;$('messages').scrollTop=$('messages').scrollHeight}
function noteLatency(){const q=s.ledger.summary();const extra=q.n?` · Output-start proxy p50 ${q.p50} / p95 ${q.p95} / p99 ${q.p99} ms (n=${q.n})`:'';$('clientmetrics').textContent='Browser pause-to-scheduled-playback (not physically measured speaker audio)'+extra}
function stopAudio(){s.epoch++;s.fence.cancel();s.frames?.reset();for(const a of s.playing){try{a.onended=null;a.stop()}catch(_){ }try{a.disconnect()}catch(_){}}s.playing.clear();s.nextAudio=0;s.allowSeq=0}
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
 case'interim_transcript':if(s.recording)status('listening','Provisional: '+String(msg.text||'').slice(0,100));break;
 case'transcript':message('user',msg.text,seq);break;
 case'assistant_text':message('assistant',msg.text,seq,msg.final===true);break;
 case'tool_result':if(msg.tool)toolNotice(msg);if(msg.job)refreshWork();break;
 case'audio_begin':s.allowSeq=seq;s.done=false;break;
 case'metrics':{const m=msg.data||{};
 $('metrics').textContent=`ASR ${m.asr_ms??'—'} ms · ${m.tool?('Tool '+m.tool+' '+(m.tool_ms??'—')+' ms'):('Gemini first text '+(m.llm_first_text_ms??'—')+' ms')} · Server first PCM ${m.post_pause_first_audio_ms??'—'} ms · Total server ${m.total_server_ms??'—'} ms`;
 s.ledger.server(seq,m.post_pause_first_audio_ms);break}
 case'done':s.done=true;if(s.ledger.complete(seq)!==null)noteLatency();if(!s.playing.size&&!s.recording)status('listening','Ask a follow-up.');break;
 case'error':s.ledger.cancel(seq);stopAudio();status('error',msg.message||'Voice turn failed');break;
 }}
function playback(samples,seq,rate=24000){if(!s.fence.accepts(seq)||seq!==s.allowSeq||s.recording||!s.ctx||!samples.length)return;
 if(s.ctx.state!=='running'){status('error','Audio suspended. Tap the page to re-enable playback.');return}
 if(rate!==24000 || !s.budget.accepts(s.ctx.currentTime,s.nextAudio,samples.length/rate)){
   interrupt();status('error','Playback buffer exceeded its safety budget; answer remains in chat.');return;
 }
 const epoch=s.epoch,ctx=s.ctx,buffer=ctx.createBuffer(1,samples.length,rate),arr=buffer.getChannelData(0);
 for(let i=0;i<samples.length;i++)arr[i]=samples[i]/32768;
 const node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);
 const timeline=scheduleBlock(ctx.currentTime,s.nextAudio,buffer.duration);s.nextAudio=timeline.end;s.playing.add(node);
 if(s.ledger.turns.get(seq)?.output===null){ // Scheduling-based estimate; physical first audible requires loopback.
   const estimated=now()+Math.max(0,timeline.start-ctx.currentTime)*1000;
   s.ledger.output(seq,estimated);
 }
 node.onended=()=>{s.playing.delete(node);node.disconnect();if(epoch===s.epoch&&s.done&&!s.playing.size&&!s.recording)status('listening','Ask a follow-up.')};
 node.start(timeline.start);
 if(epoch===s.epoch)status('speaking','Speak to interrupt.');
}
function wsAudio(raw){
 try{
  if(s.protocol===2){
   if(raw.byteLength<16)return;
   const sourceGeneration=new DataView(raw).getUint32(4,true);
   if(!s.fence.accepts(sourceGeneration))return;
   const frame=s.frames.output(raw);
   playback(frame.samples,frame.generation,frame.rate);
  }else{
   if(raw.byteLength<6||raw.byteLength%2!==0)return;
   const seq=new DataView(raw).getUint32(0,true);
   if(!s.fence.accepts(seq))return;
   playback(new Int16Array(raw,4),seq);
  }
 }catch(_){
  interrupt();status('error','Invalid or out-of-order voice audio was rejected.');
 }
}
function concat(parts){const size=parts.reduce((n,x)=>n+x.length,0),out=new Uint8Array(size);let pos=0;for(const x of parts){out.set(x,pos);pos+=x.length}return out}
async function scheduleHttpAudio(pcm,seq,rate,signal){
 if(rate!==24000||pcm.byteLength%2)throw Error('Unexpected HTTP voice sample format');
 const samples=new Int16Array(pcm.buffer,pcm.byteOffset,pcm.byteLength/2);
 const playbackDeadline=Date.now()+120000;
 // A full HTTP response can exceed the *queued* playback budget. Stream it
 // into short scheduled PCM segments with a bounded maximum lead.
 for(let offset=0;offset<samples.length;offset+=960){
  const part=samples.subarray(offset,Math.min(offset+960,samples.length));
  while(s.ctx?.state==='running'&&!s.budget.accepts(s.ctx.currentTime,s.nextAudio,part.length/rate)){
   await new Promise(resolve=>setTimeout(resolve,100));
   if(signal.aborted||!s.fence.accepts(seq))return false;
   if(Date.now()>playbackDeadline)throw Error('Audio playback stalled; answer remains in chat.');
  }
  if(signal.aborted||!s.fence.accepts(seq))return false;
  if(!s.ctx||s.ctx.state!=='running')throw Error('Audio suspended; tap the page to resume.');
  playback(part,seq,rate);
 }
 return true;
}
async function httpTurn(parts,seq){const bytes=concat(parts),ctrl=new AbortController();s.request=ctrl;
 try{const res=await fetch('/api/turn',{method:'POST',headers:{...headers(),'x-sample-rate':String(s.rate),'content-type':'application/octet-stream'},body:bytes,signal:ctrl.signal});
 if(!res.ok)throw Error('HTTP '+res.status);const m=await res.json();if(!s.fence.accepts(seq))return;
 server({type:'transcript',text:m.transcript,generation:seq});
 server({type:'assistant_text',text:m.answer,final:true,generation:seq});
 server({type:'metrics',data:m.metrics,generation:seq});
 s.allowSeq=seq;s.done=true;
 const pcm=Uint8Array.from(atob(m.audio_b64),c=>c.charCodeAt(0));
 if(!pcm.length||pcm.length%2)throw Error('Invalid response PCM');
 if(!(await scheduleHttpAudio(pcm,seq,m.sample_rate,ctrl.signal)))return;
 if(s.ledger.complete(seq)!==null)noteLatency();
 }catch(e){if(e.name!=='AbortError'&&s.fence.accepts(seq)){s.ledger.cancel(seq);status('error','Request failed: '+e.message)}}
 finally{if(s.request===ctrl)s.request=null}}
function sendWs(msg){if(s.mode!=='ws'||s.ws?.readyState!==1)return false;s.ws.send(JSON.stringify(msg));return true}
function sendPcm(raw){
 if(s.mode!=='ws'||s.ws?.readyState!==1||s.ws.bufferedAmount>256000)return false;
 try{
  s.ws.send(s.protocol===2?s.frames.input(
   new Int16Array(raw.buffer,raw.byteOffset,raw.byteLength/2),s.fence.generation):raw);
  return true;
 }catch(_){return false}
}
function start(manual=false){if(s.recording||s.muted||!s.session)return;
 interrupt();const seq=s.fence.next();const initial=manual?s.recent:s.pre;
 s.recording=true;s.chunks=initial.slice();s.chunkBytes=initial.reduce((n,x)=>n+x.length,0);s.done=false;
 s.frames?.reset();
 if(sendWs({type:'speech_start',generation:seq}))
   for(const x of initial)if(!sendPcm(x)){sendWs({type:'interrupt'});setFallback('HTTPS fallback (send overflow)');break;}
 status('listening','Capturing speech…');
}
function finish(){if(!s.recording)return;s.recording=false;
 const seq=s.fence.generation,bytes=s.chunks,chunksLen=s.chunkBytes;
 s.chunks=[];s.chunkBytes=0;s.gate.reset();
 if(chunksLen<s.rate*.35*2){sendWs({type:'interrupt'});status('listening','Speech too short.');return}
 s.allowSeq=seq;s.done=false;s.ledger.begin(seq,now());status('thinking','Transcribing and generating…');
 if(!sendWs({type:'speech_end',generation:seq})){httpTurn(bytes,seq);scheduleReconnect()}
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
     if(sendPcm(raw)){} 
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
 ws.onopen=()=>ws.send(JSON.stringify({type:'auth',token:s.key,
   client_id:s.sessionId,sample_rate:s.rate,protocol:2}));
 ws.onmessage=e=>{if(ws!==s.ws)return;
 if(typeof e.data==='string'){let m;try{m=JSON.parse(e.data)}catch(_){return}
 if(m.type==='ready'&&!ready){
   s.protocol=m.protocol===2?2:1;s.frames=new VoiceFrames(s.rate);
   ready=true;clearTimeout(timeout);s.reconnectAttempts=0;resolve();
 }
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
 s.reconnectTimer=setTimeout(async()=>{s.reconnecting=false;if(!s.session||s.recording||s.request||s.playing.size||s.mode==='ws')return;
 try{await connectWs();s.mode='ws';$('connection').textContent='WebSocket restored'}
 catch(_){scheduleReconnect()}},delay);
}
async function openMic(){
 const media=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
 s.media=media;const ctx=new AudioContext({latencyHint:'interactive'});s.ctx=ctx;await ctx.resume();s.rate=ctx.sampleRate;
 s.gate=new VoiceGate(s.rate);s.frames=new VoiceFrames(s.rate);
 await ctx.audioWorklet.addModule('/static/capture.js');
 const source=ctx.createMediaStreamSource(media),worklet=new AudioWorkletNode(ctx,'rizzler-capture');
 worklet.port.onmessage=e=>onSamples(e.data);const silent=ctx.createGain();silent.gain.value=0;
 source.connect(worklet);worklet.connect(silent);silent.connect(ctx.destination);
 s.src=source;s.worklet=worklet;
 media.getAudioTracks().forEach(track=>track.addEventListener('ended',()=>{
   if(s.session){interrupt();s.recording=false;status('error','Microphone disconnected. Reconnect to resume.');}
 }));
 if(navigator.mediaDevices?.addEventListener){
   s.deviceListener=()=>{if(s.session&&s.media?.getAudioTracks().every(t=>t.readyState==='ended')){
     interrupt();status('error','Audio input changed. Reconnect your microphone.');
   }};
   navigator.mediaDevices.addEventListener('devicechange',s.deviceListener);
 }
}
async function disconnect(){clearTimeout(s.pdfPoll);s.pdfSelected=null;s.pdfDocs=[];s.visualIDs=[];renderVisuals();s.session=false;s.recording=false;clearTimeout(s.reconnectTimer);s.reconnecting=false;
 stopAudio();s.ledger.cancel(s.fence.generation);s.request?.abort();s.ws?.close();s.media?.getTracks().forEach(t=>t.stop());
 if(s.deviceListener){navigator.mediaDevices?.removeEventListener?.('devicechange',s.deviceListener);s.deviceListener=null;}
 await s.ctx?.close();s.ctx=null;s.mode='offline';$('connection').textContent='Disconnected';status('offline','Session ended');
 $('connect').textContent='Connect microphone';for(const id of ['mute','send','reset'])$(id).disabled=true;
}
async function connectSession(){
 try{
   if(!s.production){
     const r=await fetch('/api/auth',{method:'POST',headers:headers()});
     if(!r.ok)throw Error('Invalid access key');
   }
   if(!window.isSecureContext)throw Error('Microphone requires HTTPS or localhost');
   await openMic();try{await connectWs();s.mode='ws'}catch(_){setFallback('HTTPS fallback')}
   s.session=true;$('modal').classList.add('hidden');$('connect').textContent='Disconnect';
   for(const id of ['mute','send','reset'])$(id).disabled=false;
   status('listening','Ready. Speak naturally.');noteLatency();
   refreshToolCatalog();if(s.workEnabled)refreshWork();if(s.visualEnabled)refreshPDFDocs();
   if(s.mode==='http')scheduleReconnect();
 }catch(err){$('error').textContent=err.message;status('error',err.message);
   s.media?.getTracks().forEach(t=>t.stop());await s.ctx?.close();s.ctx=null}
}

function renderVisuals(){
 s.visualAnalysis=null;$('visual-report-panel').hidden=true;
 const container=$('visual-list');if(!container)return;
 container.replaceChildren();
 for(const selected of s.visualIDs){
  const button=document.createElement('button');
  button.type='button';button.textContent='Remove '+selected.name;
  button.onclick=async()=>{
   try{const res=await fetch('/api/visual/attachments/'+encodeURIComponent(selected.id),
      {method:'DELETE',headers:headers()});
    if(!res.ok)throw Error('Unable to delete selected visual');
    s.visualIDs=s.visualIDs.filter(x=>x.id!==selected.id);renderVisuals();
   }catch(e){$('visual-status').textContent=e.message}
  };
  container.append(button);
 }
}

async function refreshPDFDocs(){
 if(!s.session||!s.visualEnabled)return;
 try{
  const r=await fetch('/api/pdf/documents',{headers:headers()});
  if(!r.ok)throw Error('PDF status unavailable ('+r.status+')');
  s.pdfDocs=(await r.json()).documents;
  const panel=$('pdf-documents');panel.replaceChildren();
  for(const doc of s.pdfDocs){
   const line=document.createElement('div');line.className='pdf-document';
   const label=document.createElement('span');
   label.textContent=doc.name+' — '+doc.status+
       (doc.pages===null?' · '+doc.uploaded_chunks+' uploaded chunks':
        ' · '+doc.processed_pages+'/'+doc.pages+' pages indexed');
   line.append(label);
   const choose=document.createElement('button');
   choose.type='button';choose.textContent=s.pdfSelected===doc.id?'Selected':'Use document';
   choose.disabled=doc.status!=='complete';
   choose.onclick=async()=>{
    const selected=s.pdfSelected===doc.id?null:doc.id;
    const result=await fetch('/api/pdf/selection',{method:'POST',
      headers:{...headers(),'content-type':'application/json'},
      body:JSON.stringify({document_id:selected})});
    if(!result.ok){$('visual-status').textContent='Cannot select PDF ('+result.status+')';return}
    s.pdfSelected=selected;renderVisuals();await refreshPDFDocs();
   };
   line.append(choose);
   if(doc.status==='paused'||doc.status==='validation_failed'){
    const resume=document.createElement('button');resume.type='button';
    resume.textContent='Resume indexing';
    resume.onclick=async()=>{
     const r=await fetch('/api/pdf/documents/'+encodeURIComponent(doc.id)+'/resume',
      {method:'POST',headers:headers()});
     $('visual-status').textContent=r.ok?'Resuming from saved page checkpoints.':'Cannot resume ('+r.status+')';
     await refreshPDFDocs();
    };line.append(resume);
   }
   if(doc.error){
    const err=document.createElement('small');err.textContent=' · '+doc.error;line.append(err);
   }
   const remove=document.createElement('button');remove.type='button';remove.textContent='Delete';
   remove.disabled=doc.status==='running';
   remove.onclick=async()=>{
    const r=await fetch('/api/pdf/documents/'+encodeURIComponent(doc.id),
      {method:'DELETE',headers:headers()});
    if(!r.ok){$('visual-status').textContent='PDF cannot be deleted ('+r.status+')';return}
    if(s.pdfSelected===doc.id)s.pdfSelected=null;
    await refreshPDFDocs();
   };
   line.append(remove);panel.append(line);
  }
  clearTimeout(s.pdfPoll);
  if(s.pdfDocs.some(x=>['queued','running','validating'].includes(x.status))&&s.session)
   s.pdfPoll=setTimeout(refreshPDFDocs,4000);
 }catch(err){$('visual-status').textContent=err.message}
}
async function uploadPDF(file){
 if(!s.visualEnabled||!s.session)throw Error('Connect the private session first');
 if(!file||!file.name.toLowerCase().endsWith('.pdf'))throw Error('Only PDF documents supported');
 $('visual-status').textContent='Preparing resumable full PDF upload…';
 await refreshPDFDocs();
 const unfinished=s.pdfDocs.find(d=>d.name===file.name&&d.status==='uploading'&&d.expected_bytes===file.size);
 const create=unfinished?null:await fetch('/api/pdf/documents',{method:'POST',
   headers:{...headers(),'content-type':'application/json'},
   body:JSON.stringify({name:file.name,bytes:file.size})});
 if(create&&!create.ok)throw Error('Cannot initialize PDF upload ('+create.status+')');
 const doc=unfinished||await create.json(),size=1024*1024;
 const total=Math.ceil(file.size/size);
 for(let i=0;i<total;i++){
  const part=await file.slice(i*size,Math.min(file.size,(i+1)*size)).arrayBuffer();
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',part)))
      .map(x=>x.toString(16).padStart(2,'0')).join('');
  let success=false;
  for(let attempt=0;attempt<3;attempt++){
   const response=await fetch('/api/pdf/documents/'+encodeURIComponent(doc.id)+
    '/chunks/'+i,{method:'PUT',
      headers:{...headers(),'x-chunk-sha256':digest},
      body:part});
   if(response.ok){success=true;break}
   if(response.status>=400&&response.status<500&&response.status!==429)
     throw Error('PDF chunk rejected ('+response.status+')');
   await new Promise(resolve=>setTimeout(resolve,(attempt+1)*1000));
  }
  if(!success)throw Error('PDF upload paused. Reattach the source to resume later.');
  $('visual-status').textContent='Uploaded '+(i+1)+'/'+total+
      ' encrypted chunks; every page will be indexed.';
 }
 const finish=await fetch('/api/pdf/documents/'+encodeURIComponent(doc.id)+'/complete',
   {method:'POST',headers:headers()});
 if(!finish.ok)throw Error('PDF validation failed ('+finish.status+')');
 $('visual-status').textContent='PDF accepted. Every page is now queued for text and visual indexing.';
 await refreshPDFDocs();
}
async function askCompletePDF(question,seq){
 const doc=s.pdfDocs.find(x=>x.id===s.pdfSelected);
 if(!doc||doc.status!=='complete')
   throw Error('Select a fully indexed PDF. Processing is not yet complete.');
 const create=await fetch('/api/pdf/documents/'+encodeURIComponent(doc.id)+'/research',
  {method:'POST',headers:{...headers(),'content-type':'application/json'},
   body:JSON.stringify({question,mode:'full'})});
 if(!create.ok)throw Error('Full-document research was not accepted ('+create.status+')');
 const job=await create.json();
 $('visual-status').textContent='Full-document analysis started; every page is included.';
 while(s.session){
  await new Promise(resolve=>setTimeout(resolve,3500));
  const r=await fetch('/api/pdf/research/'+encodeURIComponent(job.id),{headers:headers()});
  if(!r.ok)throw Error('PDF analysis status unavailable ('+r.status+')');
  const result=await r.json();
  $('visual-status').textContent='Full PDF: '+result.covered_pages+'/'+result.total_pages+
       ' pages covered; '+result.completed_units+' analysis steps; '+result.status;
  if(result.status==='complete'){
   message('assistant',result.answer,seq,true);
   $('visual-status').textContent='Entire PDF analyzed, with page-based evidence. Review citations and model accuracy.';
   return;
  }
  if(result.status==='paused'){
   $('visual-status').textContent='PDF analysis paused: '+(result.error||'provider unavailable')+
     '. Resume using the analysis ID '+job.id;
   return;
  }
 }
}

async function uploadVisual(file){
 if(!s.visualEnabled||!s.session)throw Error('Connect your private session first');
 if(file?.name?.toLowerCase().endsWith('.pdf'))return uploadPDF(file);
 if(!file||file.size>8000000||file.size<32)throw Error('Image file must be 32 bytes to 8 MB');
 const response=await fetch('/api/visual/attachments',{
  method:'POST',headers:{...headers(),'x-file-name':file.name,
    'content-type':'application/octet-stream'},body:file});
 if(!response.ok)throw Error('Visual upload rejected ('+response.status+')');
 const record=await response.json();
 s.visualIDs=[...s.visualIDs.filter(x=>x.id!==record.id),record].slice(-4);
 renderVisuals();
 $('visual-status').textContent='Shared '+record.name+' for this session. You can ask by text or voice.';
 return record;
}
$('visual-file').addEventListener('change',async e=>{
 try{if(e.target.files?.length)await uploadVisual(e.target.files[0]);}
 catch(err){$('visual-status').textContent=err.message}
 finally{e.target.value=''}
});
$('visual-screen').addEventListener('click',async()=>{
 let capture=null;
 try{
  if(!s.session)throw Error('Connect your session before screen capture');
  if(!navigator.mediaDevices?.getDisplayMedia)throw Error('Screen capture unsupported in this browser');
  capture=await navigator.mediaDevices.getDisplayMedia({video:true,audio:false});
  const track=capture.getVideoTracks()[0];
  const video=document.createElement('video');
  video.srcObject=capture;video.muted=true;
  await video.play();
  if(video.readyState<2)throw Error('No screenshot frames available');
  const canvas=document.createElement('canvas');
  const scale=Math.min(1,1920/video.videoWidth,1920/video.videoHeight);
  canvas.width=Math.max(1,Math.round(video.videoWidth*scale));
  canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
  canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.78));
  if(!blob)throw Error('Could not encode screenshot');
  track.stop();capture.getTracks().forEach(x=>x.stop());capture=null;
  await uploadVisual(new File([blob],'screen-capture.jpg',{type:'image/jpeg'}));
 }catch(err){$('visual-status').textContent='Capture unavailable: '+err.message}
 finally{capture?.getTracks().forEach(x=>x.stop())}
});
$('visual-clear').addEventListener('click',async()=>{
 const snapshot=[...s.visualIDs];s.visualIDs=[];s.pdfSelected=null;renderVisuals();
 await fetch('/api/pdf/selection',{method:'POST',headers:{...headers(),
     'content-type':'application/json'},body:JSON.stringify({document_id:null})}).catch(()=>{});
 await Promise.allSettled(snapshot.map(x=>fetch('/api/visual/attachments/'+encodeURIComponent(x.id),
     {method:'DELETE',headers:headers()})));
 $('visual-status').textContent='Visual selection cleared.';
});
$('visual-form').addEventListener('submit',async e=>{
 e.preventDefault();
 if(!s.session){$('visual-status').textContent='Connect first.';return}
 if(!s.visualIDs.length&&!s.pdfSelected){$('visual-status').textContent='Attach an image or select an indexed PDF first.';return}
 if(s.recording||s.request||s.playing.size){$('visual-status').textContent='Finish the active voice turn first.';return}
 const question=$('visual-question').value.trim();
 if(!question)return;
 const button=$('visual-ask');button.disabled=true;
 const ids=s.visualIDs.map(x=>x.id),seq=++s.visualSeq;
 $('visual-status').textContent='Analyzing shared visual evidence…';
 message('user',question,seq,true);
 try{
  if(s.pdfSelected){
   if(s.visualIDs.length)throw Error('Analyze selected PDF and images separately to preserve evidence.');
   await askCompletePDF(question,seq);return;
  }
  const response=await fetch('/api/visual/ask',{method:'POST',headers:{
   ...headers(),'content-type':'application/json'},body:JSON.stringify({
    question,attachment_ids:ids})});
  if(!response.ok)throw Error('Visual analysis unavailable ('+response.status+')');
  const result=await response.json();
  message('assistant',result.answer,seq,true);
  s.visualAnalysis=result.analysis_id;
  $('visual-report-panel').hidden=!s.workEnabled || !s.visualAnalysis;
  $('visual-status').textContent='Response ready. Evidence is user-provided, not independently verified.';
 }catch(err){$('visual-status').textContent=err.message}
 finally{button.disabled=false}
});

$('visual-report').addEventListener('click',async()=>{
 if(!s.visualAnalysis||!s.workEnabled){$('visual-status').textContent='Analyze visuals and enable Work first.';return}
 const b=$('visual-report');b.disabled=true;
 try{
  const res=await fetch('/api/visual/report',{method:'POST',
    headers:{...headers(),'content-type':'application/json'},
    body:JSON.stringify({analysis_id:s.visualAnalysis,
        format:$('visual-report-format').value})});
  if(!res.ok)throw Error('Work report not accepted ('+res.status+')');
  const item=await res.json();
  $('visual-status').textContent='Work queued: '+item.job.id.slice(0,10)+'. You can continue speaking.';
  if(s.workEnabled)refreshWork();
 }catch(err){$('visual-status').textContent=err.message}
 finally{b.disabled=false}
});

document.addEventListener('pointerdown',()=>{
 if(s.session&&s.ctx?.state==='suspended')s.ctx.resume().catch(()=>{});
},{passive:true});
$('unlock').addEventListener('submit',async e=>{e.preventDefault();s.key=$('key').value;await connectSession()});
$('connect').addEventListener('click',()=>s.session?disconnect():s.production?connectSession():$('modal').classList.remove('hidden'));
$('logout').addEventListener('click',async()=>{
  await disconnect();
  if(!s.production){$('modal').classList.remove('hidden');return}
  await fetch('/auth/logout',{method:'POST',headers:headers()}).catch(()=>{});
  location.replace('/auth/login');
});
(async()=>{
 try{
  const r=await fetch('/api/runtime');if(!r.ok)throw Error('Runtime unavailable');
  const d=await r.json();s.production=d.mode==='production';
  s.workEnabled=!!d.work_enabled;$('work-panel').hidden=!s.workEnabled;
  s.visualEnabled=!!d.multimodal_enabled;$('visual-panel').hidden=!s.visualEnabled;
  s.memoryEnabled=!!d.encrypted_memory_enabled;$('memory-open').hidden=!s.memoryEnabled;
  $('logout').hidden=!s.production;
  if(s.production){
    const who=await fetch('/auth/session');
    if(!who.ok){location.replace('/auth/login');return}
    $('modal').classList.add('hidden');
    status('offline','Signed in. Select Connect microphone to start.');
  }
 }catch(e){status('error','Cannot verify runtime access')}
})();

async function refreshMemories(){
 if(!s.memoryEnabled||(!s.production&&!s.key))return;
 const feedback=$('memory-feedback'),target=$('memory-items');
 try{
  const res=await fetch('/api/voice/memories',{headers:headers()});
  if(!res.ok)throw Error('Memory list unavailable');
  const {items=[]}=await res.json();target.replaceChildren();
  if(!items.length){feedback.textContent='No saved memories.';return}
  feedback.textContent=items.length+' saved memories.';
  for(const item of items){
   const card=document.createElement('article');card.className='job-card';
   const text=document.createElement('p');text.textContent=item.text;
   const remove=document.createElement('button');remove.type='button';remove.textContent='Delete';
   remove.addEventListener('click',async()=>{
    try{
     const r=await fetch('/api/voice/memories/'+encodeURIComponent(item.id),
       {method:'DELETE',headers:headers()});
     if(!r.ok)throw Error('Deletion failed');await refreshMemories();
    }catch(e){feedback.textContent=e.message}
   });
   card.append(text,remove);target.append(card);
  }
 }catch(e){feedback.textContent=e.message}
}
$('memory-open').addEventListener('click',async()=>{
 $('memory-panel').hidden=!$('memory-panel').hidden;
 if(!$('memory-panel').hidden)await refreshMemories();
});
$('memory-form').addEventListener('submit',async e=>{
 e.preventDefault();const text=$('memory-fact').value.trim();
 try{
  const r=await fetch('/api/voice/memories',{method:'POST',
   headers:{...headers(),'content-type':'application/json'},
   body:JSON.stringify({text})});
  if(!r.ok)throw Error('Could not save memory (check length and content)');
  $('memory-fact').value='';await refreshMemories();
 }catch(error){$('memory-feedback').textContent=error.message}
});
$('memory-clear').addEventListener('click',async()=>{
 if(!window.confirm('Permanently delete all saved memories for this account?'))return;
 try{
  const res=await fetch('/api/voice/memories',{method:'DELETE',headers:headers()});
  if(!res.ok)throw Error('Could not delete saved memories');await refreshMemories();
 }catch(error){$('memory-feedback').textContent=error.message}
});
async function refreshToolCatalog(){
 try{
  const r=await fetch('/api/voice/tools',{headers:headers()});
  if(!r.ok)return;
  const d=await r.json(),t=d.tools||{};
  $('tool-status').textContent='Tools · Web search: '+(t.web_search||'unknown')+
    ' · Verified math: '+(t.symbolic_math||'unknown')+
    ' · Work: '+(t.work_agent||'unknown');
 }catch(_){$('tool-status').textContent='Tools · Verification unavailable'}
}
function toolNotice(msg){
 const panel=$('upload-feedback');if(!panel)return;
 const name={web_search:'Live web search',symbolic_math:'Verified mathematics',
  work_submit:'Work delegation',work_status:'Work status',work_cancel:'Work cancellation'}[msg.tool]||msg.tool;
 panel.textContent=name+(msg.verified?' · verified':' · unavailable or unverified')+
   (Number.isFinite(msg.elapsed_ms)?' · '+Math.round(msg.elapsed_ms)+' ms':'');
}
async function refreshWork(){
 if(!s.workEnabled||(!s.key&&!s.production))return;
 try{
 const response=await fetch('/api/voice/jobs',{headers:headers()});
 if(!response.ok)return;
 const {jobs}=await response.json(),target=$('work-jobs');target.replaceChildren();
 for(const job of jobs.slice(0,6)){
  const card=document.createElement('article');card.className='job-card';
  const heading=document.createElement('strong');heading.textContent='Job '+job.id.slice(0,8)+' · '+job.status;
  const subtitle=document.createElement('p');subtitle.textContent='Stage: '+job.stage+' · '+job.attempts+' worker attempts';
  card.append(heading,subtitle);
  if(['queued','running','completed','failed','cancelled'].includes(job.status)){
    const res=await fetch('/api/voice/jobs/'+encodeURIComponent(job.id),{headers:headers()});
    if(res.ok){
     const detail=await res.json();
     if(detail.plan?.steps?.length){
       const flow=document.createElement('p');flow.className='job-workflow';
       flow.textContent='Plan: '+detail.plan.steps.map(n=>n.tool.replaceAll('_',' ')).join(' · ');
       card.append(flow);
     }
     const agents=document.createElement('p');agents.className='job-agents';
     agents.textContent=detail.agents.map(a=>a.agent.replaceAll('_',' ')+': '+a.status).join(' · ');
     card.append(agents);
     for(const file of detail.artifacts){
      const btn=document.createElement('button');btn.textContent='Download '+file.kind.toUpperCase();
      btn.addEventListener('click',async()=>{
       try{const result=await fetch('/api/voice/artifacts/'+encodeURIComponent(file.id),{headers:headers()});
        if(!result.ok)throw Error('Download unavailable');
        const blob=await result.blob(),url=URL.createObjectURL(blob);
        const a=document.createElement('a');a.href=url;a.download=file.name;a.click();
        setTimeout(()=>URL.revokeObjectURL(url),30000);
       }catch(e){$('upload-feedback').textContent=e.message;}
      });card.append(btn);
     }
    }
  }
  target.append(card);
 }
 }catch(_){/* An offline dashboard must not interrupt the microphone. */}
}
const uploadField=$('data-upload');
uploadField?.addEventListener('change',async()=>{
 const file=uploadField.files?.[0];if(!file)return;
 if(!s.workEnabled||(!s.key&&!s.production)){ $('upload-feedback').textContent='Connect Rizzler before attaching a file.';return;}
 if(!/\.(csv|xlsx)$/i.test(file.name)||file.size>8000000){$('upload-feedback').textContent='Choose a CSV or XLSX under 8 MB.';return;}
 try{const res=await fetch('/api/voice/uploads',{method:'POST',headers:{...headers(),'x-file-name':file.name,'content-type':'application/octet-stream'},body:file});
 if(!res.ok)throw Error('Upload failed ('+res.status+')');
 $('upload-feedback').textContent='Attached '+file.name+'. Now ask Rizzler to analyze it.';
 }catch(e){$('upload-feedback').textContent=e.message;}
});
setInterval(()=>{if(!document.hidden&&s.session&&s.workEnabled)refreshWork()},8000);

$('mute').addEventListener('click',()=>{s.muted=!s.muted;$('mute').textContent=s.muted?'Unmute':'Mute';
 if(s.muted){interrupt();s.recording=false;s.gate.reset();status('muted','Microphone muted')}else status('listening','Speak naturally')});
$('send').addEventListener('click',()=>{if(s.recording){finish();return}if(s.recentBytes<s.rate*2*.35)return;
 start(true);finish()});
$('reset').addEventListener('click',async()=>{interrupt();s.history.clear();s.visualIDs=[];renderVisuals();$('messages').replaceChildren();s.ledger.cancel(s.fence.generation);
 if(!sendWs({type:'new_conversation'}))await fetch('/api/reset',{method:'POST',headers:headers()}).catch(()=>{});
 status('listening','New conversation')});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&s.session&&s.ctx?.state==='suspended')s.ctx.resume().catch(()=>{})});
window.addEventListener('pagehide',()=>{s.ws?.close();s.media?.getTracks().forEach(t=>t.stop())});
})();
