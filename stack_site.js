(function(){'use strict';
var start=document.getElementById('start'),status=document.getElementById('status'),timer=document.getElementById('timer'),frame=document.getElementById('live');
var colab=document.getElementById('colab');if(colab.getAttribute('href')==='#demo')colab.hidden=true;
function clock(s){var m=Math.floor(Math.max(0,s)/60),sec=Math.max(0,s)%60;return String(m).padStart(2,'0')+':'+String(sec).padStart(2,'0')}
function show(data){var s=data.status||'idle',remain=data.seconds_left||0;timer.textContent=clock(remain)+' / DEMO';start.disabled=!data.launch_enabled||s==='starting'||s==='running'||s==='busy'||s==='stopping';
if(s==='running'&&data.live){status.textContent='GPU ready. Connect your microphone inside the demo.';if(frame.hidden){frame.src='/live/';frame.hidden=false}return}
if(!frame.hidden){frame.src='about:blank';frame.hidden=true}
if(s==='starting'){status.textContent='Starting the private AI session. Preparing GPU resources…';return}
if(s==='busy'){status.textContent='Someone is trying Rizzler right now. This single-GPU demo will free up soon.';return}
if(s==='stopping'){status.textContent='Session complete. Releasing temporary GPU resources…';return}
if(s==='expired'||s==='ended'){status.textContent='Hope you enjoyed the experience! You can restart the demo if you wanna go for another spin.';start.disabled=s==='expired';start.textContent='Take another spin →';return}
if(s==='failed'){status.textContent='The runtime could not start. Please retry later.';return}
status.textContent=data.launch_enabled?'Ready when you are.':'Automated GPU launch is not configured on this host yet.'}
async function refresh(){try{var r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('bad');show(await r.json())}catch(e){status.textContent='Connection unavailable. Check again shortly.'}}
start.addEventListener('click',async function(){start.disabled=true;status.textContent='Requesting a private GPU session…';try{var r=await fetch('/api/start',{method:'POST',headers:{'x-rizzler-action':'start'}}),data=await r.json();if(!r.ok)throw Error(data.detail||'Unavailable');show(data)}catch(e){status.textContent=e.message||'Unable to start';await refresh()}});
refresh();setInterval(function(){if(!document.hidden)refresh()},3000);
var obs=('IntersectionObserver' in window)?new IntersectionObserver(function(entries){entries.forEach(function(e){if(e.isIntersecting){e.target.classList.add('visible');obs.unobserve(e.target)}})},{threshold:.12}):null;
document.querySelectorAll('.reveal').forEach(function(node){if(obs)obs.observe(node);else node.classList.add('visible')});
})();
