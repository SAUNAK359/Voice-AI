(()=>{'use strict';const $=id=>document.getElementById(id);
let token='';function el(tag,text){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;return x}
function auth(){token=$('work-token').value.trim();if(!token)throw Error('Work token required');return {'Authorization':'Bearer '+token}}
async function call(path,opts={}){const r=await fetch('/api/work'+path,{...opts,headers:{...auth(),...(opts.headers||{})}});
 if(!r.ok)throw Error('Request failed ('+r.status+')');if(r.headers.get('content-type')?.includes('application/json'))return r.json();return r}
function err(x){$('work-error').textContent=x?.message||String(x)}
async function refresh(){try{const data=await call('/jobs');const pane=$('jobs');pane.replaceChildren();
 for(const item of data.jobs){const row=el('p'),btn=el('button',item.status+' · '+item.id.slice(0,8)+' · '+item.stage);
 btn.onclick=()=>details(item.id);row.append(btn);pane.append(row)}}catch(e){err(e)}}
async function details(id){try{const [job,ev,art]=await Promise.all([
 call('/jobs/'+id),call('/jobs/'+id+'/events'),call('/jobs/'+id+'/artifacts')]);const pane=$('job-detail');pane.replaceChildren(el('h3',job.status+' · '+job.stage));
 for(const e of ev.events)pane.append(el('p',new Date(e.at*1000).toLocaleString()+' · '+e.stage+' · '+e.message));
 if(job.status==='completed')pane.append(el('p',job.result.slice(0,1500)));
 for(const a of art.artifacts){const btn=el('button','Download '+a.kind+' ('+a.size+' bytes)');
 btn.onclick=async()=>{try{const r=await call('/artifacts/'+a.id);const blob=await r.blob(),url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=a.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000)}catch(e){err(e)}};
 pane.append(btn)}
 if(!['completed','failed','cancelled'].includes(job.status)){const b=el('button','Cancel job');b.onclick=async()=>{await call('/jobs/'+id+'/cancel',{method:'POST'});details(id)};pane.append(b)}
 }catch(e){err(e)}}
$('submit-work').onclick=async()=>{try{let uploads=[],file=$('upload').files[0];
 if(file){const result=await call('/uploads',{method:'POST',headers:{'x-file-name':file.name,'content-type':'application/octet-stream'},body:file});uploads=[result.id]}
 const payload={objective:$('objective').value,deliverables:$('deliverables').value.split(',').map(x=>x.trim()).filter(Boolean),uploads};
 const unique=crypto.randomUUID().replaceAll('-','');const item=await call('/jobs',{method:'POST',
 headers:{'idempotency-key':unique,'content-type':'application/json'},body:JSON.stringify(payload)});
 $('work-error').textContent='Queued: '+item.id;refresh();details(item.id)}catch(e){err(e)}};
$('reload-work').onclick=refresh;
})();
