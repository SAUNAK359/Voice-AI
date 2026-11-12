(()=>{'use strict';const $=id=>document.getElementById(id);
let token='',production=false;
const csrf=()=>decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('rizzler_csrf='))?.split('=').slice(1).join('=')||'');
function el(tag,text){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;return x}
function auth(){
 if(production)return {'x-csrf-token':csrf()};
 token=$('work-token').value.trim();if(!token)throw Error('Work token required');
 return {'Authorization':'Bearer '+token}
}
async function call(path,opts={}){const r=await fetch('/api/work'+path,{...opts,headers:{...auth(),...(opts.headers||{})}});
 if(r.status===401&&production){location.replace('/auth/login');throw Error('Session expired')}
 if(!r.ok)throw Error('Request failed ('+r.status+')');if(r.headers.get('content-type')?.includes('application/json'))return r.json();return r}
function err(x){$('work-error').textContent=x?.message||String(x)}
async function refresh(){try{const data=await call('/jobs');const pane=$('jobs');pane.replaceChildren();
 for(const item of data.jobs){const row=el('p'),btn=el('button',item.status+' · '+item.id.slice(0,8)+' · '+item.stage);
 btn.onclick=()=>details(item.id);row.append(btn);pane.append(row)}}catch(e){err(e)}}
async function details(id){try{const [job,ev,art,agentData]=await Promise.all([
 call('/jobs/'+id),call('/jobs/'+id+'/events'),call('/jobs/'+id+'/artifacts'),call('/jobs/'+id+'/agents')]);
 const pane=$('job-detail');pane.replaceChildren(el('h3',job.status+' · '+job.stage));
 const heading=el('h4','Specialist agents · persisted status and targets');pane.append(heading);
 for(const a of agentData.agents){
   const elapsed=a.finished>0?Math.round(a.finished-a.started)+'s':'active';
   const row=el('p',a.agent+' · '+a.status+' · attempt '+a.attempt+' · '+elapsed+' · target '+a.sla);
   if(a.quality?.passed)row.append(el('span',' · QA passed ('+(a.quality.checks||[]).join(', ')+')'));
   pane.append(row);
 }
 for(const e of ev.events)pane.append(el('p',new Date(e.at*1000).toLocaleString()+' · '+e.stage+' · '+e.message));
 if(job.status==='completed')pane.append(el('p',job.result.slice(0,1500)));
 for(const a of art.artifacts){const btn=el('button','Download '+a.kind+' ('+a.size+' bytes)');
 btn.onclick=async()=>{try{const r=await call('/artifacts/'+a.id);const blob=await r.blob(),url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=a.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000)}catch(e){err(e)}};
 pane.append(btn)}
 const speak=el('button','Speak verified status');
 speak.onclick=async()=>{try{const data=await call('/jobs/'+id+'/voice-status');
 if(!('speechSynthesis' in window))throw Error('Browser speech not supported');
 speechSynthesis.cancel();speechSynthesis.speak(new SpeechSynthesisUtterance(data.text))}
 catch(e){err(e)}};pane.append(speak);
 if(!['completed','failed','cancelled'].includes(job.status)){const b=el('button','Cancel job');b.onclick=async()=>{await call('/jobs/'+id+'/cancel',{method:'POST'});details(id)};pane.append(b)}
 }catch(e){err(e)}}
$('submit-work').onclick=async()=>{try{let uploads=[],file=$('upload').files[0];
 if(file){const result=await call('/uploads',{method:'POST',headers:{'x-file-name':file.name,'content-type':'application/octet-stream'},body:file});uploads=[result.id]}
 const payload={objective:$('objective').value,deliverables:$('deliverables').value.split(',').map(x=>x.trim()).filter(Boolean),uploads};
 const unique=crypto.randomUUID().replaceAll('-','');const item=await call('/jobs',{method:'POST',
 headers:{'idempotency-key':unique,'content-type':'application/json'},body:JSON.stringify(payload)});
 $('work-error').textContent='Queued: '+item.id;refresh();details(item.id)}catch(e){err(e)}};
async function schedules(){try{
 const data=await call('/automation-proposals');
 const p=$('schedules');if(!p)return;p.replaceChildren();
 for(const x of data.proposals){
  const row=el('p',x.status+' · '+x.runs+'/'+x.max_runs+' runs every '+x.cadence_minutes+' min');
  if(x.status==='pending_approval'){const b=el('button','Approve');
   b.onclick=async()=>{await call('/automation-proposals/'+x.id+'/approve',{method:'POST'});schedules()};
   row.append(b)}
  if(['pending_approval','active'].includes(x.status)){const b=el('button','Disable');
   b.onclick=async()=>{await call('/automation-proposals/'+x.id+'/disable',{method:'POST'});schedules()};
   row.append(b)}
  p.append(row)
 }}catch(e){err(e)}}
$('reload-work').onclick=()=>{refresh();schedules()};
(async()=>{
 try{
  const res=await fetch('/api/runtime'),data=await res.json();
  production=data.mode==='production';
  if(production){
   const current=await fetch('/auth/session');
   if(!current.ok){location.replace('/auth/login');return}
   $('work-token').hidden=true;$('work-token-label').hidden=true;
   $('work-auth-hint').textContent='Signed in securely; your jobs and files are private.';
  }
  refresh();schedules();
 }catch(e){err(e)}
})();
})();
