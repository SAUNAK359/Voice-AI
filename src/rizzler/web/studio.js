/* Rizzler V13: owner-scoped project canvas. Status is read from persisted Work events, not estimated. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const state={auth:null,selected:null,artifact:null,jobs:[],busy:false,lastCompleted:new Set(),sources:[],visualFiles:[],link:null,navigateSlide:null};
const headers=()=>!state.auth?{}:state.auth.production?{'x-csrf-token':decodeURIComponent((document.cookie.split('; ').find(x=>x.startsWith('rizzler_csrf='))||'').split('=').slice(1).join('=')||'')}:{'x-rizzler-key':state.auth.key,'x-session-id':state.auth.sessionId};
function report(msg){$('studio-feedback').textContent=msg;}
async function api(path,options={}){
 const r=await fetch(path,{...options,headers:{...headers(),...(options.headers||{})}});
 if(!r.ok)throw Error('Request unavailable ('+r.status+')');
 return r;
}
const LABELS={research:'Gathering information',sql_analytics:'Exploring your data',orchestrator:'Understanding findings',powerpoint:'Creating slides',word:'Writing the document',excel:'Building the workbook',pdf_visual:'Designing your output',quality:'Checking the result',planning:'Preparing the project',rendering:'Building your artifact',analysis:'Analyzing sources',validating:'Checking quality'};
function progress(job,steps=[]){
 const target=$('studio-progress');target.replaceChildren();
 const stage=job.stage,done=job.status==='completed';
 const known=steps.filter(x=>x.agent!=='quality');
 const stages=known.length?known.map(x=>({name:LABELS[x.agent]||'Processing a source',status:x.status})):
   [{name:'Preparing the project',status:job.status==='queued'?'queued':stage==='planning'?'running':'completed'},
    {name:'Research and analysis',status:['research','analysis'].includes(stage)?'running':'queued'},
    {name:'Creating the deliverable',status:stage==='rendering'?'running':'queued'}];
 stages.push({name:'Checking the result',status:done?'completed':job.status==='failed'?'failed':steps.find(x=>x.agent==='quality')?.status||'queued'});
 stages.push({name:'Ready to preview',status:done?'completed':'queued'});
 for(const step of stages){
  const line=document.createElement('div');line.className='studio-step';line.dataset.state=step.status;
  const mark=document.createElement('span');mark.className='studio-step-icon';
  mark.textContent=step.status==='completed'?'✓':step.status==='running'?'◉':step.status==='failed'?'!':'○';
  const text=document.createElement('span');text.textContent=step.name;
  line.append(mark,text);target.append(line);
 }
}
function renderJobs(){
 const sel=$('studio-job-select'),selected=state.selected||'';
 sel.replaceChildren(new Option('Latest project',''));
 for(const j of state.jobs){
  const label=(j.status==='running'?'● ':j.status==='queued'?'◷ ':j.status==='completed'?'✓ ':'! ')+j.id.slice(0,8)+' · '+j.status;
  sel.append(new Option(label,j.id));
 }
 sel.value=selected;
}
async function inspect(id){
 const [j,a]=await Promise.all([
   api('/api/voice/jobs/'+encodeURIComponent(id)).then(x=>x.json()),
   api('/api/work/jobs/'+encodeURIComponent(id)+'/events').then(x=>x.json()).catch(()=>({events:[]}))
 ]);
 const job=j.job;
 $('studio-status').textContent=
   job.status==='queued'?'In queue — Rizzler is available while this project waits.':
   job.status==='running'?'Building your project. You can keep talking to Rizzler.':
   job.status==='completed'?'Your artifact is ready to explore.':
   job.status==='failed'?'This project needs attention. Its existing work remains recorded.':
   'Project '+job.status;
 progress(job,j.agents||[]);
 if(job.status==='completed'&&j.artifacts?.length){
  const bar=$('studio-artifact-toolbar'),list=$('studio-artifact-list');bar.hidden=false;list.replaceChildren();
  for(const f of j.artifacts){
   const b=document.createElement('button');b.type='button';b.textContent=f.kind.toUpperCase();
   b.setAttribute('aria-pressed',String(state.artifact?.id===f.id));
   b.addEventListener('click',()=>showArtifact(f));list.append(b);
  }
  if(state.artifact&&!j.artifacts.some(f=>f.id===state.artifact.id))state.artifact=null;
  if(!state.artifact)await showArtifact(j.artifacts[0]);
 }else{
  $('studio-artifact-toolbar').hidden=true;
  if(job.status!=='completed'){$('studio-preview').replaceChildren();const p=document.createElement('p');p.className='studio-placeholder';p.textContent=job.status==='queued'?'Your project is waiting in the queue. The preview opens after verification.':'Rizzler is preparing your artifact. Verified output will appear here.';$('studio-preview').append(p)}
 }
 if(job.status==='failed')report('The project could not complete. Ask Rizzler to review or retry it.');
 else if(job.status==='completed')report(j.artifacts?.length+' downloadable artifact(s) available.');
 else report(a.events?.length?'Latest update: '+a.events[a.events.length-1].message:'Project state synchronized.');
}
function table(rows){
 const t=document.createElement('table');for(let i=0;i<Math.min(rows.length,300);i++){
  const tr=document.createElement('tr');
  for(const item of rows[i]){const td=document.createElement(i?'td':'th');td.textContent=String(item??'').slice(0,2000);tr.append(td)}
  t.append(tr);
 }return t;
}
function renderStructured(preview,target){
 state.navigateSlide=null;
 target.replaceChildren();
 if(preview.kind==='pptx'){
  let current=0;
  const nav=document.createElement('div');nav.className='studio-artifact-list';
  const prev=document.createElement('button'),next=document.createElement('button'),label=document.createElement('span');
  prev.textContent='Previous';next.textContent='Next';
  const slide=document.createElement('section');slide.className='studio-slide';
  const show=()=>{
   const item=preview.slides[current];slide.replaceChildren();
   const title=document.createElement('h2');title.textContent=item.title;slide.append(title);
   for(const text of item.lines.slice(1)){
    const p=document.createElement('p');p.textContent=text;slide.append(p);
   }
   label.textContent=(current+1)+' / '+preview.total;
   prev.disabled=current===0;next.disabled=current===preview.slides.length-1;
  };
  prev.onclick=()=>{current--;show()};next.onclick=()=>{current++;show()};
  state.navigateSlide=index=>{
   if(!Number.isInteger(index)||index<1||index>preview.slides.length)return false;
   current=index-1;show();slide.scrollIntoView({block:'nearest'});return true;
  };
  nav.append(prev,label,next);target.append(nav,slide);show();
 }else if(preview.kind==='docx'){
  for(const line of preview.blocks){
   const p=document.createElement('p');p.textContent=line;p.className='studio-doc-block';target.append(p);
  }
 }else if(preview.kind==='xlsx'){
  const select=document.createElement('select');
  preview.sheets.forEach((sh,i)=>select.append(new Option(sh.name,String(i))));
  const body=document.createElement('div');
  const show=()=>{body.replaceChildren(table(preview.sheets[+select.value].rows));
   if(preview.sheets[+select.value].truncated){const notice=document.createElement('p');notice.textContent='Preview shows the first 160 rows. Download the workbook for all data.';body.append(notice)}};
  select.onchange=show;target.append(select,body);select.value='0';show();
 }
 const note=document.createElement('small');note.className='studio-preview-note';note.textContent='Structured content preview; native document layout may differ. Download to view the original formatting.';
 target.append(note);
}
async function showPages(f,target){
 const record=await api('/api/work/artifacts/'+encodeURIComponent(f.id)+'/pages').then(r=>r.json());
 const nav=document.createElement('div');nav.className='studio-artifact-list';
 const prev=document.createElement('button'),next=document.createElement('button');
 const label=document.createElement('span'),picture=document.createElement('img');
 prev.textContent='Previous';next.textContent='Next';picture.alt='Rendered artifact page';
 picture.style.cssText='width:100%;height:auto;max-height:none;object-fit:contain';
 let current=1,activeUrl=null;
 const update=async page=>{
  if(page<1||page>record.pages)return false;
  const response=await api('/api/work/artifacts/'+encodeURIComponent(f.id)+'/pages/'+page);
  const url=URL.createObjectURL(await response.blob());
  const old=activeUrl;activeUrl=url;picture.src=url;
  if(old)URL.revokeObjectURL(old);
  current=page;label.textContent=page+' / '+record.pages;
  prev.disabled=current===1;next.disabled=current===record.pages;
  return true;
 };
 prev.onclick=()=>update(current-1).catch(e=>report(e.message));
 next.onclick=()=>update(current+1).catch(e=>report(e.message));
 nav.append(prev,label,next);target.replaceChildren(nav,picture);
 state.navigateSlide=update;
 const note=document.createElement('small');note.className='studio-preview-note';
 note.textContent='Rendered from the original file. Office font and pagination differences may occur.';
 target.append(note);
 await update(1);
 return true;
}
async function showArtifact(f){
 state.artifact=f;state.navigateSlide=null;state.dashboard=null;
 const target=$('studio-preview');target.replaceChildren();
 const loading=document.createElement('p');loading.textContent='Opening '+f.name+'…';target.append(loading);
 try{
  if(f.kind.toLowerCase()==='csv'){
   state.dashboard=await window.RizzlerDashboard.open(f,target,api);
   return;
  }
  if(f.kind.toLowerCase()==='xlsx'){
   const switcher=document.createElement('div');switcher.className='studio-artifact-list';
   const dashboardButton=document.createElement('button'),pageButton=document.createElement('button');
   dashboardButton.textContent='Interactive dashboard';pageButton.textContent='Original pages';
   target.append(switcher);
   const holder=document.createElement('div');target.append(holder);
   switcher.append(dashboardButton,pageButton);
   dashboardButton.onclick=async()=>{holder.replaceChildren();state.dashboard=await window.RizzlerDashboard.open(f,holder,api);
      dashboardButton.setAttribute('aria-pressed','true');pageButton.setAttribute('aria-pressed','false')};
   pageButton.onclick=async()=>{holder.replaceChildren();await showPages(f,holder);
      dashboardButton.setAttribute('aria-pressed','false');pageButton.setAttribute('aria-pressed','true')};
   await dashboardButton.onclick();return;
  }
  if(['pdf','pptx','docx'].includes(f.kind.toLowerCase())){
   try{
    await showPages(f,target);
   }catch(e){
    if(f.kind.toLowerCase()==='pdf')throw e;
    report('Visual renderer unavailable; using structured document preview.');
    const record=await api('/api/work/artifacts/'+encodeURIComponent(f.id)+'/preview').then(r=>r.json());
    renderStructured(record,target);
   }
   for(const b of $('studio-artifact-list').querySelectorAll('button'))
    b.setAttribute('aria-pressed',String(b.textContent===f.kind.toUpperCase()));
   return;
  }
  const r=await api('/api/voice/artifacts/'+encodeURIComponent(f.id));
  const blob=await r.blob();
  if(blob.size>35_000_000)throw Error('Preview too large; use Download.');
  target.replaceChildren();const kind=f.kind.toLowerCase();
  if(['txt','md','json','csv','svg'].includes(kind)){
   const raw=await blob.text();if(kind==='csv'){const rows=raw.split(/\r?\n/).slice(0,301).filter(Boolean).map(s=>s.split(','));target.append(table(rows))}
   else{const pre=document.createElement('pre');pre.textContent=raw.slice(0,300000);target.append(pre)}
  }else if(['png','jpg','jpeg','webp'].includes(kind)){
   const img=new Image();const url=URL.createObjectURL(blob);img.onload=()=>URL.revokeObjectURL(url);img.onerror=()=>{URL.revokeObjectURL(url);report('Image could not be previewed.')};img.src=url;img.alt=f.name;target.append(img);
  }else if(kind==='pdf'){
   const url=URL.createObjectURL(blob);const frame=document.createElement('iframe');
   frame.title=f.name;frame.src=url+'#toolbar=0';frame.setAttribute('sandbox','');frame.addEventListener('load',()=>setTimeout(()=>URL.revokeObjectURL(url),120000),{once:true});target.append(frame);
  }else if(kind==='html'){
   const frame=document.createElement('iframe');frame.title=f.name;
   frame.setAttribute('sandbox','');frame.srcdoc=await blob.text();target.append(frame);
  }else{
   const p=document.createElement('p');p.textContent=f.kind.toUpperCase()+' is ready. Open or download the verified file. An interactive renderer for this file type is not yet installed.';target.append(p);
  }
  for(const b of $('studio-artifact-list').querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.textContent===kind.toUpperCase()));
 }catch(e){report(e.message);const p=document.createElement('p');p.textContent='Preview could not be loaded. Try downloading the artifact.';target.replaceChildren(p)}
}
async function refresh(prefer){
 if(!state.auth||state.busy)return;state.busy=true;
 try{
  const response=await api('/api/voice/jobs').then(r=>r.json());
  state.jobs=response.jobs||[];
  if(prefer)state.selected=prefer;
  if(state.selected&&!state.jobs.some(x=>x.id===state.selected)){state.selected=null;state.artifact=null}
  renderJobs();
  const selected=state.selected||state.jobs[0]?.id;
  if(selected)await inspect(selected);
 }catch(e){report('Workspace temporarily unavailable: '+e.message)}
 finally{state.busy=false}
}
async function uploadFile(file){
 if(!state.auth)throw Error('Connect Rizzler first.');
 const name=file.name,ext=name.split('.').pop().toLowerCase();
 if(['png','jpg','jpeg','webp'].includes(ext)){
  if(file.size>8_000_000)throw Error('Image exceeds the current 8 MB visual attachment limit.');
  const res=await api('/api/visual/attachments',{method:'POST',
    headers:{'x-file-name':name,'content-type':'application/octet-stream'},body:file});
  const record=await res.json();state.visualFiles=[...state.visualFiles,{name:record.name,id:record.id}].slice(-4);
  renderSources();report('Image attached to the private Live session.');return;
 }
 if(!['txt','md','json','csv','xlsx','pdf','docx','pptx','db','sqlite','sqlite3'].includes(ext))
  throw Error('Unsupported document type: '+ext);
 if(!file.size||file.size>200_000_000)throw Error('Sources must be between 1 byte and 200 MB.');
 let item;
 if(file.size<=8_000_000){
  item=await api('/api/work/sources',{method:'POST',headers:{
   'x-file-name':name,'content-type':'application/octet-stream'},body:file}).then(r=>r.json());
 }else{
  if(!crypto?.subtle)throw Error('HTTPS is required for integrity-checked large uploads.');
  const transfer=await api('/api/work/sources/transfers',{method:'POST',
   headers:{'content-type':'application/json'},
   body:JSON.stringify({name,bytes:file.size,sha256:''})}).then(r=>r.json());
  let offset=transfer.offset||0;
  const chunkSize=transfer.chunk_size;
  while(offset<file.size){
   const buf=await file.slice(offset,Math.min(offset+chunkSize,file.size)).arrayBuffer();
   const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buf)))
      .map(v=>v.toString(16).padStart(2,'0')).join('');
   let result;
   for(let attempt=0;attempt<3;attempt++){
    try{
     result=await api('/api/work/sources/transfers/'+encodeURIComponent(transfer.id)+'/chunks',{
      method:'PUT',headers:{'x-chunk-offset':String(offset),'x-chunk-sha256':digest,
       'content-type':'application/octet-stream'},body:buf}).then(r=>r.json());
     break;
    }catch(error){
     if(attempt===2)throw error;
     const position=await api('/api/work/sources/transfers/'+encodeURIComponent(transfer.id)).then(r=>r.json());
     if(position.offset>offset){result={offset:position.offset};break;}
    }
   }
   offset=result.offset;
   report('Uploading '+name+' — '+Math.round(100*offset/file.size)+'%');
  }
  report('Validating and indexing '+name+'; large files may take longer…');
  item=await api('/api/work/sources/transfers/'+encodeURIComponent(transfer.id)+'/complete',
    {method:'POST'}).then(r=>r.json());
 }
 state.sources=[...state.sources,{name,id:item.id,kind:ext}].slice(-8);
 await api('/api/source/selection',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({source_ids:state.sources.map(x=>x.id)})});
 // The legacy tabular specialist remains limited to small datasets. The full
 // source index is available to Live and to source-grounded Work objectives.
 if(['csv','xlsx'].includes(ext)&&file.size<=8_000_000){
  await api('/api/voice/uploads',{method:'POST',headers:{
   'x-file-name':name,'content-type':'application/octet-stream'},body:file});
 }
 renderSources();
 const coverage=item.metadata?.coverage||'bounded indexed passages';
 report(name+' indexed: '+item.passages+' passages ('+coverage+'). Ready for Rizzler.');
}

function renderSources(){
 const panel=$('workspace-attachment-status');panel.replaceChildren();
 for(const source of [...state.sources,...state.visualFiles]){
  const el=document.createElement('span');el.className='workspace-chip';el.textContent=source.name;
  panel.append(el);
 }
 if(state.link){const el=document.createElement('span');el.className='workspace-chip';el.textContent=state.link;panel.append(el)}
}
$('studio-job-select')?.addEventListener('change',e=>{state.selected=e.target.value||null;state.artifact=null;refresh()});
$('studio-download')?.addEventListener('click',async()=>{
 if(!state.artifact)return;try{
  const r=await api('/api/voice/artifacts/'+encodeURIComponent(state.artifact.id));
  const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=state.artifact.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
 }catch(e){report(e.message)}
});
$('workspace-files')?.addEventListener('change',async e=>{
 const input=e.target;
 for(const file of [...input.files]){
  try{await uploadFile(file)}catch(err){report(err.message)}
 }
 input.value='';
});
$('attach-link')?.addEventListener('click',()=>{$('link-entry').hidden=!$('link-entry').hidden});
$('link-add')?.addEventListener('click',async e=>{
 e.preventDefault();
 try{
  if(!state.auth)throw Error('Connect Rizzler before adding a source.');
  const url=new URL($('link-input').value);
  if(url.protocol!=='https:'||url.username||url.password)throw Error('Only public HTTPS links are supported.');
  report('Retrieving and indexing the public source…');
  const response=await api('/api/work/sources/url',{method:'POST',
    headers:{'content-type':'application/json'},body:JSON.stringify({url:url.toString()})});
  const item=await response.json();
  state.sources=[...state.sources,{name:item.url,id:item.id,kind:'url'}].slice(-8);
  await api('/api/source/selection',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({source_ids:state.sources.map(x=>x.id)})});
  state.link=item.url;renderSources();
  const input=$('agent-text');
  if(!input.value.includes(item.url))input.value=(input.value+'\nSource URL: '+item.url).trim();
  report('Web source indexed: '+item.passages+' passages. Rizzler can inspect its evidence.');
  $('link-entry').hidden=true;
 }catch(err){report(err.message)}
});

async function applyActions(actions){
 for(const action of actions||[]){
  if(!action?.job_id||!['open','slide','highlight'].includes(action.kind))continue;
  state.selected=action.job_id;state.artifact=null;
  await refresh();
  if(action.kind==='slide'){
   const detail=await api('/api/voice/jobs/'+encodeURIComponent(action.job_id)).then(r=>r.json());
   const presentation=(detail.artifacts||[]).find(x=>x.kind==='pptx');
   if(presentation&&state.artifact?.id!==presentation.id)await showArtifact(presentation);
   if(!state.navigateSlide?.(action.slide))report('Slide unavailable in this preview.');
  }else if(action.kind==='highlight'){
   const needle=String(action.text||'').trim().toLowerCase();
   if(!needle)continue;
   const walker=document.createTreeWalker($('studio-preview'),NodeFilter.SHOW_TEXT);
   let node;
   while((node=walker.nextNode())){
    const index=(node.nodeValue||'').toLowerCase().indexOf(needle);
    if(index<0)continue;
    const start=node.nodeValue.slice(0,index),match=node.nodeValue.slice(index,index+needle.length),end=node.nodeValue.slice(index+needle.length);
    const mark=document.createElement('mark');mark.textContent=match;
    const fragment=document.createDocumentFragment();fragment.append(document.createTextNode(start),mark,document.createTextNode(end));
    node.parentNode.replaceChild(fragment,node);mark.scrollIntoView({block:'center'});
    break;
   }
  }
 }
}
window.RizzlerStudio={setAuth(auth){state.auth=auth;refresh()},refresh,showArtifact,inspect,applyActions,
  configureDashboard:async action=>{
    const detail=await api('/api/voice/jobs/'+encodeURIComponent(action.job_id)).then(r=>r.json());
    const f=(detail.artifacts||[]).find(item=>['csv','xlsx'].includes(item.kind));
    if(!f)throw Error('Project has no tabular dashboard');
    state.selected=action.job_id;await showArtifact(f);
    await state.dashboard?.configure(action);
  }
};
setInterval(()=>{if(state.auth&&!document.hidden)refresh()},5000);
})();