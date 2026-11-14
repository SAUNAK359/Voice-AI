/* In-app interactive analytics: actual owner-authorized artifact data, not
   a fabricated screenshot or executable third-party HTML. No remote scripts. */
(()=>{'use strict';
const el=(tag,props={})=>{const n=document.createElement(tag);for(const [k,v] of Object.entries(props)){if(k==='text')n.textContent=String(v);else if(k==='class')n.className=v;else n.setAttribute(k,v)}return n};
let current=null;
function numeric(v){if(typeof v==='number')return Number.isFinite(v)?v:null;const s=String(v??'').trim().replace(/[,$]/g,'');return s&&/^-?\d+(?:\.\d+)?$/.test(s)?Number(s):null}
function select(label,items,value,change){
 const box=el('label',{class:'dashboard-control'});box.append(el('span',{text:label}));
 const sel=el('select');
 items.forEach(x=>{const o=el('option',{text:String(x)});o.value=String(x);sel.append(o)});
 if(value!=null)sel.value=String(value);
 sel.onchange=()=>change(sel.value);box.append(sel);return box;
}
function range(rows,cols,col,mode){
 const x=cols.indexOf(col);if(x<0)return [];
 const m=new Map();
 for(const row of rows){const k=String(row[x]??'').slice(0,80);if(!m.has(k))m.set(k,[]);
  m.get(k).push(row)}
 const entries=[];
 for(const [name,group] of m){
  const values=group.map(row=>numeric(row[cols.indexOf(mode)]?.toString())).filter(v=>v!==null);
  entries.push({name,count:group.length,value:values.reduce((a,b)=>a+b,0)});
 }
 return entries;
}
function render(data,target,actions={}){
 if(!Array.isArray(data.rows)||!Array.isArray(data.columns)||data.columns.length>50||data.rows.length>10000)
   throw Error('Dashboard data contract invalid');
 target.replaceChildren();
 const columns=data.columns,rows=data.rows;
 const state={group:actions.group_by||columns[0],metric:actions.metric||'Count',
              chart:['bar','line','scatter'].includes(actions.chart)?actions.chart:'bar',
              filterCol:'All',filter:'',sort:'Highest first',rowSort:null,ascending:true,search:'',page:0};
 const top=el('div',{class:'dashboard-top'});
 const name=el('h3',{text:data.sheet?data.sheet+' · Interactive Dashboard':'Interactive Data Dashboard'});
 const count=el('p',{class:'dashboard-metadata',text:rows.length+' source rows · '+columns.length+' columns · filter, group, drill down'});
 top.append(name,count);target.append(top);
 const controls=el('div',{class:'dashboard-controls'});target.append(controls);
 const chartRoot=el('div',{class:'dashboard-chart'}),summary=el('div',{class:'dashboard-summary'});
 target.append(chartRoot,summary);
 const details=el('div',{class:'dashboard-data'});target.append(details);
 function filtered(){
  const pos=columns.indexOf(state.filterCol);
  return rows.filter(row=>(pos<0||String(row[pos]??'').toLowerCase().includes(state.filter.toLowerCase()))&&
    (!state.search||row.some(v=>String(v??'').toLowerCase().includes(state.search.toLowerCase()))));
 }
 function update(){
  controls.replaceChildren();
  const filteredRows=filtered();
  let metricOptions=['Count',...columns.filter((_,j)=>rows.some(r=>numeric(r[j])!==null))];
  if(!metricOptions.includes(state.metric))state.metric='Count';
  controls.append(select('Group by',columns,state.group,v=>{state.group=v;state.page=0;update()}),
    select('Value',metricOptions,state.metric,v=>{state.metric=v;update()}),
    select('Chart',['bar','line','scatter'],state.chart,v=>{state.chart=v;update()}),
    select('Filter column',['All',...columns],state.filterCol,v=>{state.filterCol=v;update()}),
    select('Group order',['Highest first','Lowest first','Alphabetical'],state.sort,v=>{state.sort=v;update()}));
  const query=el('input',{placeholder:'Filter value…','aria-label':'Filter value'});query.value=state.filter;
  query.oninput=()=>{state.filter=query.value;state.page=0;draw()};
  controls.append(query);
  const search=el('input',{placeholder:'Search all rows…','aria-label':'Search all rows'});search.value=state.search;
  search.oninput=()=>{state.search=search.value;state.page=0;draw()};
  controls.append(search);
  const exportBtn=el('button',{type:'button',text:'Export selected rows'});
  exportBtn.onclick=()=>{
    const values=[columns,...filtered()],escaped=values.map(row=>row.map(cell=>{
      const val=String(cell??'').replace(/"/g,'""');
      return '"'+val+'"';
    }).join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([escaped],{type:'text/csv;charset=utf-8'}));
    const link=el('a',{download:'rizzler-filtered-analysis.csv'});link.href=url;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),15000);
  };
  controls.append(exportBtn);
  const sheetNames=data.sheets||[];
  if(sheetNames.length){controls.append(select('Worksheet',sheetNames,data.sheet,async v=>{
    try{const updated=await current.loadSheet(v);render(updated,target,{group_by:state.group,metric:state.metric,chart:state.chart})}
    catch(err){const note=el('p',{text:'Worksheet could not load: '+err.message});target.append(note)}
  }))}
  draw();
 }
 function draw(){
  const subset=filtered(),groupIndex=columns.indexOf(state.group),valueIndex=columns.indexOf(state.metric);
  let grouped=new Map();
  for(const row of subset){
   const label=String(row[groupIndex]??'Unknown').slice(0,70);
   const prev=grouped.get(label)||{label,sum:0,count:0,values:[]};
   prev.count+=1;
   const value=valueIndex<0?1:numeric(row[valueIndex]);
   if(value!=null){prev.sum+=value;prev.values.push(value)}
   grouped.set(label,prev);
  }
  let items=[...grouped.values()].map(x=>({...x,value:state.metric==='Count'?x.count:x.sum}));
  if(state.sort==='Alphabetical')items.sort((a,b)=>a.label.localeCompare(b.label));
  else items.sort((a,b)=>state.sort==='Lowest first'?a.value-b.value:b.value-a.value);
  const visible=items.slice(0,24),maximum=Math.max(1,...visible.map(x=>Math.abs(x.value)));
  chartRoot.replaceChildren();
  if(!subset.length){chartRoot.append(el('p',{text:'No matching records.'}));}
  else{
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
   svg.setAttribute('viewBox','0 0 720 340');svg.setAttribute('role','img');
   svg.setAttribute('aria-label',state.chart+' chart grouped by '+state.group);
   svg.style.cssText='width:100%;height:auto;min-height:220px';
   const add=(tag,attrs,txt)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);
     Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));
     if(txt!==undefined)n.textContent=String(txt);svg.append(n);return n};
   add('line',{x1:80,y1:18,x2:80,y2:300,stroke:'#80909a','stroke-width':1});
   add('line',{x1:80,y1:300,x2:700,y2:300,stroke:'#80909a','stroke-width':1});
   const width=600/Math.max(1,visible.length);
   if(state.chart==='bar'){
    visible.forEach((item,i)=>{
     const h=Math.max(1,Math.abs(item.value)/maximum*245),x=86+i*width;
     const bar=add('rect',{x,y:299-h,width:Math.max(4,width-5),height:h,rx:3,fill:'#438cb4'});
     bar.setAttribute('tabindex','0');
     bar.setAttribute('role','button');
     bar.setAttribute('aria-label',item.label+': '+item.value);
     const chosen=()=>{state.filterCol=state.group;state.filter=item.label;state.page=0;update()};
     bar.addEventListener('click',chosen);bar.addEventListener('keydown',ev=>{if(ev.key==='Enter')chosen()});
     add('title',{},item.label+': '+item.value);
     if(i<12)add('text',{x:x+3,y:318,'font-size':9,fill:'#475568',transform:'rotate(-25 '+(x+3)+' 318)'},item.label.slice(0,16));
    });
   }else{
    const pts=visible.map((item,i)=>({x:94+i*(590/Math.max(1,visible.length-1)),y:299-Math.abs(item.value)/maximum*245,label:item.label,value:item.value}));
    if(state.chart==='line')add('polyline',{points:pts.map(p=>p.x+','+p.y).join(' '),fill:'none',stroke:'#438cb4','stroke-width':3});
    pts.forEach(p=>{
     const dot=add('circle',{cx:p.x,cy:p.y,r:6,fill:'#438cb4',tabindex:0,role:'button','aria-label':p.label+': '+p.value});
     const choose=()=>{state.filterCol=state.group;state.filter=p.label;state.page=0;update()};
     dot.addEventListener('click',choose);dot.addEventListener('keydown',e=>{if(e.key==='Enter')choose()});
     add('title',{},p.label+': '+p.value);
    });
   }
   chartRoot.append(svg);
  }
  summary.replaceChildren();
  summary.append(el('span',{text:subset.length+' / '+rows.length+' matching records'}),
                 el('span',{text:items.length+' groups'}));
  details.replaceChildren();
  const nav=el('div',{class:'dashboard-pagination'}),pagenum=Math.floor(subset.length/50)+1;
  const prev=el('button',{text:'Previous'}),next=el('button',{text:'Next'});
  prev.disabled=state.page===0;next.disabled=(state.page+1)*50>=subset.length;
  prev.onclick=()=>{state.page--;draw()};next.onclick=()=>{state.page++;draw()};
  nav.append(prev,el('span',{text:'Page '+(state.page+1)+' / '+Math.max(1,Math.ceil(subset.length/50))}),next);
  details.append(nav);
  const table=el('table'),head=el('tr');
  columns.forEach(c=>{
    const title=el('th',{text:c+(state.rowSort===c?(state.ascending?' ▲':' ▼'):'')});
    title.tabIndex=0;title.setAttribute('role','button');title.setAttribute('aria-label','Sort by '+c);
    const sort=()=>{if(state.rowSort===c)state.ascending=!state.ascending;
      else {state.rowSort=c;state.ascending=true}state.page=0;draw()};
    title.addEventListener('click',sort);title.addEventListener('keydown',evt=>{if(evt.key==='Enter')sort()});
    head.append(title);
  });table.append(head);
  let ordered=subset;
  if(state.rowSort){
    const col=columns.indexOf(state.rowSort);
    ordered=[...subset].sort((a,b)=>{
      const na=numeric(a[col]),nb=numeric(b[col]);
      const cmp=na!==null&&nb!==null?na-nb:String(a[col]??'').localeCompare(String(b[col]??''));
      return state.ascending?cmp:-cmp;
    });
  }
  ordered.slice(state.page*50,(state.page+1)*50).forEach(row=>{
   const tr=el('tr');row.forEach(v=>tr.append(el('td',{text:String(v??'').slice(0,450)})));table.append(tr);
  });
  details.append(table);
 }
 update();
 return {configure:async args=>{
  if(args.group_by&&columns.includes(args.group_by))state.group=args.group_by;
  if(args.metric&&(args.metric==='Count'||columns.includes(args.metric)))state.metric=args.metric;
  if(['bar','line','scatter'].includes(args.chart))state.chart=args.chart;
  if(args.filter_column&&columns.includes(args.filter_column))state.filterCol=args.filter_column;
  if(args.filter_value!==undefined)state.filter=String(args.filter_value);
  state.page=0;update();
 }};
}
window.RizzlerDashboard={
 async open(f,target,api,config={}){
  const loadSheet=sheet=>api('/api/work/artifacts/'+encodeURIComponent(f.id)+'/dashboard'+
     (sheet?'?sheet='+encodeURIComponent(sheet):'')).then(r=>r.json());
  current={loadSheet};const data=await loadSheet();
  return render(data,target,config);
 }
};
})();