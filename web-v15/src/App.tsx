import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactFlow, { Background, Controls } from '@xyflow/react';
import { Activity, ArrowUpRight, BrainCircuit, CheckCircle2, CircleAlert,
         Download, FileText, Mic2, Plus, RefreshCw, ShieldCheck } from 'lucide-react';
import { WorkApi, type Auth, type Artifact, type Job, type Plan, type Agent } from './api';
import { executionGraph } from './graph';

const FORMATS = ['pptx','pdf','docx','xlsx','md','json','html','txt','zip','research'];
const visible = (value: unknown) => value instanceof Error ? value.message : 'Unable to complete request';

function Login({onConnect}: {onConnect: (value: Auth) => Promise<void>}) {
  const [accessKey,setAccessKey] = useState('');
  const [sessionId,setSessionId] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  return <main className="login-shell">
    <section className="login-card">
      <div className="logo"><BrainCircuit size={27}/> RIZZLER <span>V15</span></div>
      <div className="eyebrow">COGNITIVE WORK INTELLIGENCE</div>
      <h1>Your work, one intelligent workspace.</h1>
      <p>Connect to your existing Rizzler session to inspect real jobs, model-selected agent workflows and verified deliverables.</p>
      <form onSubmit={async e => {
        e.preventDefault();setBusy(true);setError('');
        try {await onConnect({accessKey:accessKey.trim(),sessionId:sessionId.trim()});}
        catch (err) {setError(visible(err));} finally {setBusy(false);}
      }}>
        <label>Private access key <small>(leave empty for authenticated production cookie)</small>
          <input autoComplete="off" type="password" value={accessKey} onChange={e=>setAccessKey(e.target.value)} placeholder="Enter demo access key"/>
        </label>
        <label>Session ID <small>(same session as Voice + Work)</small>
          <input autoComplete="off" value={sessionId} onChange={e=>setSessionId(e.target.value)} placeholder="Existing session identifier"/>
        </label>
        {error && <div role="alert" className="notice bad">{error}</div>}
        <button className="primary" type="submit" disabled={busy || (!!accessKey && !sessionId)}>
          {busy?'Connecting…':'Connect Work Studio'} <ArrowUpRight size={17}/>
        </button>
      </form>
      <div className="fine"><ShieldCheck size={15}/> Credentials stay in session memory, never local storage.</div>
    </section>
  </main>;
}

function NewTask({api,onCreated}: {api: WorkApi;onCreated:(job:Job)=>void}) {
  const [objective,setObjective]=useState('');
  const [formats,setFormats]=useState<string[]>(['pptx']);
  const submit=useMutation({mutationFn:()=>api.submit(objective.trim(),formats),
                           onSuccess:job=>{setObjective('');onCreated(job);}});
  const ready=objective.trim().length>=3 && formats.length>0 && !(formats.length===1 && formats[0]==="zip");
  const toggle=(item:string)=>setFormats(prev=>prev.includes(item)?
     prev.filter(x=>x!==item):[...prev,item]);
  return <section className="panel new-task">
    <div className="section-title"><div><div className="eyebrow">AUTONOMOUS WORK</div><h2>What should Rizzler create?</h2></div><Plus size={22}/></div>
    <form onSubmit={e=>{e.preventDefault();if(ready)submit.mutate();}}>
      <textarea value={objective} onChange={e=>setObjective(e.target.value)} maxLength={7900}
        placeholder="Describe the objective, intended audience, evidence requirements and expected result. Gemini will plan the workflow…"
        aria-label="Work objective" rows={4}/>
      <div className="format-row" role="group" aria-label="Requested deliverable formats">
        {FORMATS.map(f=><button key={f} type="button" className={'format '+(formats.includes(f)?'selected':'')}
           aria-pressed={formats.includes(f)} onClick={()=>toggle(f)}>{f.toUpperCase()}</button>)}
      </div>
      {submit.isError && <p className="notice bad" role="alert">{visible(submit.error)}</p>}
      <div className="action-row">
        <span className="muted">Model-authored plan · Independent QA · Dataset-only formats use the existing source uploader</span>
        <button className="primary" type="submit" disabled={submit.isPending || !ready}>
          {submit.isPending?'Submitting…':'Create work'} <ArrowUpRight size={16}/>
        </button>
      </div>
    </form>
  </section>;
}

function FlowPanel({plan,agents}: {plan:Plan|undefined;agents:Agent[]}) {
  const graph=useMemo(()=>executionGraph(plan||{status:'planning',steps:[]},agents),[plan,agents]);
  return <section className="panel flow-panel">
    <div className="section-title"><div><div className="eyebrow">REAL WORK GRAPH</div><h2>Agent execution</h2></div><Activity size={20}/></div>
    {graph.nodes.length===0?<p className="muted">Awaiting the model-authored execution graph.</p>:
      <div className="graph-canvas" aria-label="Persisted specialist dependency graph">
        <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView fitViewOptions={{padding:0.25}}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={true}
          minZoom={0.35} maxZoom={1.5} proOptions={{hideAttribution:true}}>
          <Background color="#2f425e" gap={18} size={1}/>
          <Controls showInteractive={false}/>
        </ReactFlow>
      </div>}
    {agents.length>0 && <div className="agent-status">
      {agents.map(a=><div className="agent-line" key={a.agent}>
        <strong>{a.agent.replaceAll('_',' ')}</strong>
        <span className={'chip '+a.status}>{a.status} · attempt {a.attempt||0}</span>
        {a.error_code && <small className="muted">{a.error_code}</small>}
      </div>)}
    </div>}
  </section>;
}

function ArtifactViewer({api,artifact}: {api:WorkApi;artifact:Artifact}) {
  const [page,setPage]=useState(1);
  const [image,setImage]=useState<string|null>(null);
  const [fallback,setFallback]=useState('');
  const supported=['pptx','pdf','docx'].includes(artifact.kind);
  const info=useQuery({queryKey:['pages',artifact.id],queryFn:()=>api.pages(artifact.id),
    enabled:supported,retry:false,staleTime:120_000});
  const structured=useQuery({queryKey:['structured',artifact.id],queryFn:()=>api.preview(artifact.id),
    enabled:!supported,retry:false,staleTime:120_000});
  useEffect(()=>{setPage(1);setFallback('');},[artifact.id]);
  useEffect(()=>{
    if(!supported || !info.data || page>info.data.pages)return;
    let cancelled=false;
    let activeUrl:string|null=null;
    setImage(null);
    api.image(artifact.id,page).then(blob=>{
      if(cancelled)return;
      activeUrl=URL.createObjectURL(blob);
      setImage(activeUrl);
    }).catch(()=>{if(!cancelled)setFallback('Original-page preview unavailable; use verified download.');});
    return ()=>{
      cancelled=true;
      if(activeUrl)URL.revokeObjectURL(activeUrl);
    };
  },[api,artifact.id,info.data,page,supported]);
  return <div className="artifact-viewer">
    <div className="artifact-top">
      <div><strong>{artifact.name}</strong><small>{artifact.kind.toUpperCase()} · {(artifact.size/1024).toFixed(1)} KB</small></div>
      <button className="ghost" onClick={()=>api.download(artifact)}><Download size={16}/> Download</button>
    </div>
    {supported?
      <>
        {info.isError?<p className="notice">Rendered-page preview unavailable; the verified native file can still be downloaded.</p>:
        <div className="page-stage">
          {image?<img alt={'Rendered '+artifact.kind+' page '+page} src={image}/>:
             <div className="muted">Rendering original page…</div>}
        </div>}
        {fallback&&<p className="notice">{fallback}</p>}
        {info.data && <div className="page-controls">
           <button className="ghost" onClick={()=>setPage(x=>Math.max(1,x-1))} disabled={page===1}>Previous</button>
           <span>Page {page} of {info.data.pages} · {info.data.fidelity}</span>
           <button className="ghost" onClick={()=>setPage(x=>Math.min(info.data!.pages,x+1))}
             disabled={page>=info.data.pages}>Next</button>
        </div>}
      </>:
      <div className="structured-preview">
        {structured.isError?<p className="muted">Structured preview unavailable. Download the native file.</p>:
          <pre>{structured.data?JSON.stringify(structured.data,null,2).slice(0,15000):'Loading preview…'}</pre>}
      </div>}
  </div>;
}

function JobWorkspace({api,id}: {api:WorkApi;id:string}) {
  const job=useQuery({queryKey:['job',id],queryFn:()=>api.job(id),
    refetchInterval:query=>['queued','running'].includes(query.state.data?.status||'')?2500:10000});
  const plan=useQuery({queryKey:['plan',id],queryFn:()=>api.plan(id),refetchInterval:6000,retry:false});
  const agents=useQuery({queryKey:['agents',id],queryFn:()=>api.agents(id),refetchInterval:3500});
  const artifacts=useQuery({queryKey:['artifacts',id],queryFn:()=>api.artifacts(id),
    enabled:job.data?.status==='completed'});
  const quality=useQuery({queryKey:['quality',id],queryFn:()=>api.quality(id),
    enabled:job.data?.status==='completed'});
  const [selected,setSelected]=useState('');
  useEffect(()=>setSelected(''),[id]);
  const files=artifacts.data?.artifacts||[];
  const chosen=files.find(x=>x.id===selected)||files[0];
  return <div className="workspace">
    <div className="work-header">
      <div><div className="eyebrow">ACTIVE WORKSPACE / {id.slice(0,12)}</div>
        <h1>Execution & deliverables</h1>
        <p className="muted">Actual persisted state. No simulated progress or fabricated artifacts.</p></div>
      <div className={'chip '+(job.data?.status||'queued')}>{job.data?.status||'loading'}</div>
    </div>
    {job.isError && <p className="notice bad" role="alert">{visible(job.error)}</p>}
    {job.data?.status==='failed' && <p className="notice bad">
      <CircleAlert size={17}/> Work stopped: {job.data.error_code||'unknown_error'}.
      Saved checkpoints remain available for a confirmed retry.</p>}
    <FlowPanel plan={plan.data} agents={agents.data?.agents||[]}/>
    <section className="panel">
      <div className="section-title"><div><div className="eyebrow">VERIFIED RELEASE</div><h2>Artifacts</h2></div><FileText size={21}/></div>
      {job.data?.status!=='completed'?
        <p className="muted">Artifacts are published only after the job and its quality gate complete.</p>:
        files.length===0?<p className="notice">No downloadable artifact records were returned.</p>:
        <>
          <div className="artifact-tabs">{files.map(a=><button type="button" key={a.id}
            className={'tab '+(chosen?.id===a.id?'current':'')}
            onClick={()=>setSelected(a.id)}>{a.kind.toUpperCase()}</button>)}</div>
          {chosen&&<ArtifactViewer key={chosen.id} api={api} artifact={chosen}/>}
        </>}
      <details className="quality"><summary><CheckCircle2 size={17}/> Independent QA and job diagnostics</summary>
        <pre>{JSON.stringify({quality:quality.data,plan:plan.data,agents:agents.data},null,2).slice(0,25000)}</pre>
      </details>
    </section>
  </div>;
}

export default function App() {
  const [auth,setAuth]=useState<Auth|null>(null);
  const [selected,setSelected]=useState('');
  const qc=useQueryClient();
  const api=useMemo(()=>auth?new WorkApi(auth):null,[auth]);
  const jobs=useQuery({queryKey:['work-list',auth?.sessionId],
    enabled:!!api,queryFn:()=>api!.jobs(),refetchInterval:5000});
  useEffect(()=>{
    if(!selected && jobs.data?.jobs?.length)setSelected(jobs.data.jobs[0].id);
  },[selected,jobs.data]);
  if(!api) return <Login onConnect={async credentials=>{
    const candidate=new WorkApi(credentials);
    await candidate.jobs();
    setAuth(credentials);
  }}/>;
  return <div className="studio-root">
    <aside className="sidebar">
      <div className="logo"><BrainCircuit size={26}/> RIZZLER <span>V15</span></div>
      <div className="sidebar-caption">YOUR PROJECTS <button title="Refresh jobs"
        onClick={()=>qc.invalidateQueries({queryKey:['work-list']})}><RefreshCw size={15}/></button></div>
      <nav aria-label="Work projects">
        {jobs.data?.jobs.map(job=><button key={job.id} className={'project '+(selected===job.id?'active':'')}
          onClick={()=>setSelected(job.id)}>
          <span><span className={'dot '+job.status}/> Job {job.id.slice(0,10)}</span>
          <small>{job.status} · {job.stage}</small>
        </button>)}
        {jobs.data?.jobs.length===0 && <p className="muted">No Work jobs in this session.</p>}
        {jobs.isError && <p className="notice bad">Unable to refresh private jobs.</p>}
      </nav>
      <div className="sidebar-bottom">
        <div className="side-note"><Mic2 size={17}/> Voice remains available in the existing Rizzler interface.</div>
        <button className="ghost" onClick={()=>{setAuth(null);setSelected('');qc.clear();}}>Disconnect</button>
      </div>
    </aside>
    <main className="content">
      <NewTask api={api} onCreated={job=>{
        setSelected(job.id);
        qc.invalidateQueries({queryKey:['work-list']});
      }}/>
      {selected?<JobWorkspace key={selected} api={api} id={selected}/>:
        <section className="panel empty"><BrainCircuit size={30}/><h2>Ready to create</h2>
          <p>Describe a task above and Rizzler will build its agent workflow.</p></section>}
    </main>
  </div>;
}
