/* Native Gemini Live: real PCM microphone input, streamed model speech and
   model-directed Work/preview events. The Gemini key stays on the server. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const state={socket:null,context:null,media:null,source:null,worklet:null,muted:false,
  silence:null,playbacks:[],scheduled:0,seq:800000,connected:false};
function bubble(role,text){
 if(!text)return;
 const id=role+':native';let node=state.last?.[id];
 if(!node){
  document.querySelector('#messages .empty')?.remove();
  node=document.createElement('article');node.className='bubble '+role;
  const label=document.createElement('small');label.textContent=role==='user'?'You':'Rizzler';
  const body=document.createElement('div');node.append(label,body);
  $('messages').append(node);if(!state.last)state.last={};state.last[id]=node;
 }
 node.lastChild.textContent+=(node.lastChild.textContent?' ':'')+text;
 $('messages').scrollTop=$('messages').scrollHeight;
}
function newTurn(){state.last={};}
function stopPlaying(){
 for(const source of state.playbacks)try{source.stop()}catch(_){}
 state.playbacks=[];state.scheduled=state.context?.currentTime||0;
}
function hear(blob){
 if(!state.context||state.muted||!blob.byteLength)return;
 const ctx=state.context;
 const data=new Int16Array(blob.slice(0));
 const buffer=ctx.createBuffer(1,data.length,24000),channel=buffer.getChannelData(0);
 for(let i=0;i<data.length;i++)channel[i]=data[i]/32768;
 const sound=ctx.createBufferSource();sound.buffer=buffer;sound.connect(ctx.destination);
 const start=Math.max(ctx.currentTime+0.03,state.scheduled);
 state.scheduled=start+buffer.duration;
 sound.onended=()=>{state.playbacks=state.playbacks.filter(x=>x!==sound)};
 state.playbacks.push(sound);sound.start(start);
}
function convertPcm(raw,inputRate){
 // Preserve continuity across frames, including fractional device rates.
 const ratio=inputRate/16000;
 let position=state.readPosition||0;
 const samples=[];
 while(position<raw.length){
  const i=Math.floor(position),end=Math.min(raw.length,Math.floor(position+ratio));
  let sum=0,n=0;
  for(let k=i;k<=end&&k<raw.length;k++){sum+=raw[k];n++}
  if(n)samples.push(Math.round(sum/n));
  position+=ratio;
 }
 state.readPosition=position-raw.length;
 return new Int16Array(samples);
}
async function connect(key,sessionId,production){
 if(state.connected)return;
 if(!window.isSecureContext)throw Error('Microphone requires HTTPS or localhost.');
 const stream=await navigator.mediaDevices.getUserMedia({audio:{
  echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
 const ctx=new AudioContext({sampleRate:48000});
 try{
  await ctx.audioWorklet.addModule('/static/capture.js');
  const socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/live');
  socket.binaryType='arraybuffer';
  await new Promise((resolve,reject)=>{
   let ready=false;
   const timeout=setTimeout(()=>{if(!ready){socket.close();reject(Error('Native Live connection timed out'))}},12000);
   socket.onopen=()=>socket.send(JSON.stringify({type:'auth',token:key,client_id:sessionId}));
   socket.onmessage=ev=>{
    if(typeof ev.data==='string'){
     let msg;try{msg=JSON.parse(ev.data)}catch(_){return}
     if(msg.type==='ready'){
      ready=true;clearTimeout(timeout);resolve();
      $('connection').textContent='Gemini Live · Connected';
     }else if(msg.type==='transcript'){
      bubble(msg.role||'assistant',msg.text);
     }else if(msg.type==='turn_complete'){newTurn()}
     else if(msg.type==='interrupted'){stopPlaying();newTurn()}
     else if(msg.type==='job'){window.RizzlerStudio?.refresh(msg.job?.id)}
     else if(msg.type==='preview_actions')window.RizzlerStudio?.applyActions(msg.ui_actions||[]);
     else if(msg.type==='error')$('detail').textContent=msg.message;
    }else{
     hear(ev.data);
    }
   };
   socket.onerror=()=>{if(!ready){clearTimeout(timeout);reject(Error('Native Live socket unavailable'))}};
   socket.onclose=()=>{if(!ready){clearTimeout(timeout);reject(Error('Native Live socket closed'))}
    else if(state.connected){state.connected=false;stopPlaying();$('detail').textContent='Gemini Live disconnected. Reconnect to continue.'}};
  });
  const source=ctx.createMediaStreamSource(stream);
  const worklet=new AudioWorkletNode(ctx,'rizzler-capture');
  const silence=ctx.createGain();silence.gain.value=0;
  worklet.port.onmessage=evt=>{
   if(state.muted||socket.readyState!==WebSocket.OPEN)return;
   const pcm=convertPcm(evt.data,ctx.sampleRate);
   if(pcm.length&&socket.bufferedAmount<500000)socket.send(pcm.buffer);
  };
  source.connect(worklet);worklet.connect(silence);silence.connect(ctx.destination);
  await ctx.resume();
  Object.assign(state,{socket,context:ctx,media:stream,source,worklet,silence,connected:true,readPosition:0,scheduled:ctx.currentTime});
  $('send').hidden=true;
 }catch(e){stream.getTracks().forEach(t=>t.stop());await ctx.close();throw e}
}
function textSend(text){
 if(!state.connected||state.socket.readyState!==WebSocket.OPEN)throw Error('Live session is disconnected.');
 newTurn();bubble('user',text);
 state.socket.send(JSON.stringify({type:'text',text}));
}
function setMuted(value){state.muted=!!value;if(state.muted)stopPlaying()}
async function disconnect(){
 state.connected=false;stopPlaying();state.socket?.close();
 state.source?.disconnect();state.worklet?.disconnect();state.silence?.disconnect();
 state.media?.getTracks().forEach(t=>t.stop());
 if(state.context)await state.context.close().catch(()=>{});
 state.socket=state.media=state.context=state.source=state.worklet=state.silence=null;
 state.readPosition=0;$('send').hidden=false;
}
$('agent-chat')?.addEventListener('submit',event=>{
 if(!state.connected)return;
 event.preventDefault();event.stopImmediatePropagation();
 const input=$('agent-text');const text=input.value.trim();
 if(!text)return;
 try{textSend(text);input.value='';$('agent-feedback').textContent='Sent to Gemini Live';}
 catch(e){$('agent-feedback').textContent=e.message}
},true);
window.RizzlerNative={connect,disconnect,setMuted,sendText:textSend,
 get connected(){return state.connected}};
})();