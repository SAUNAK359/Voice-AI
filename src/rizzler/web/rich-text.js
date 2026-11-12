/* Safe rich response renderer: creates DOM nodes, never interprets model HTML. */
(function(root,factory){
 const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;
 else root.RizzlerRich=api;
})(typeof window==='undefined'?globalThis:window,function(){
 'use strict';
 function latex(t){return t.replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g,'($1)⁄($2)')
  .replace(/\\sqrt\{([^{}]+)\}/g,'√($1)').replace(/\\sqrt/g,'√')
  .replace(/\\(?:times|cdot)/g,'×').replace(/\\(?:approx|simeq)/g,'≈')
  .replace(/\\(?:leq|le)/g,'≤').replace(/\\(?:geq|ge)/g,'≥')
  .replace(/\\pm/g,'±').replace(/\\neq/g,'≠')
  .replace(/\^2\b/g,'²').replace(/\^3\b/g,'³')
  .replace(/\\([A-Za-z]+)/g,'$1').replace(/[{}]/g,'');}
 function inline(parent,txt){
  const pattern=/(\$\$?[^$]+\$\$?|\\\([^)]*\\\)|\*\*[^*]+\*\*|\[[^\]]+\]\(https:\/\/[^)]+\))/g;
  let pos=0,match;
  while((match=pattern.exec(txt))){
   if(match.index>pos)parent.append(document.createTextNode(txt.slice(pos,match.index)));
   const term=match[0];
   if(term.startsWith('**')){const strong=document.createElement('strong');strong.textContent=term.slice(2,-2);parent.append(strong);}
   else if(term.startsWith('[')){const m=/^\[([^\]]+)\]\((https:\/\/[^)]+)\)$/.exec(term);
    if(m){const a=document.createElement('a');a.textContent=m[1];a.href=m[2];a.target='_blank';a.rel='noopener noreferrer';parent.append(a);}
    else parent.append(document.createTextNode(term));}
   else{const math=document.createElement('span');math.className='inline-math';
    math.textContent=latex(term.startsWith('\\(')?term.slice(2,-2):term.replace(/^\$+/,'').replace(/\$+$/,''));
    math.setAttribute('aria-label','Mathematical expression: '+math.textContent);parent.append(math);}
   pos=pattern.lastIndex;
  }
  if(pos<txt.length)parent.append(document.createTextNode(txt.slice(pos)));
 }
 function render(target,source){
  const frag=document.createDocumentFragment(),lines=String(source||'').split('\n');
  for(let i=0;i<lines.length;i++){
   const line=lines[i];if(!line.trim())continue;
   if(line.startsWith(String.fromCharCode(96).repeat(3))){
    const code=[],mark=String.fromCharCode(96).repeat(3);
    while(++i<lines.length&&!lines[i].startsWith(mark))code.push(lines[i]);
    const pre=document.createElement('pre');pre.textContent=code.join('\n');frag.append(pre);continue;
   }
   if(/^\|/.test(line)&&i+1<lines.length&&/^\|[\s:|-]+\|?\s*$/.test(lines[i+1])){
    const table=document.createElement('table'),head=document.createElement('thead'),row=document.createElement('tr');
    for(const c of line.split('|').slice(1,-1)){const th=document.createElement('th');inline(th,c.trim());row.append(th);}
    head.append(row);table.append(head);i+=2;const body=document.createElement('tbody');
    while(i<lines.length&&/^\|/.test(lines[i])){const tr=document.createElement('tr');
     for(const c of lines[i].split('|').slice(1,-1)){const td=document.createElement('td');inline(td,c.trim());tr.append(td);}
     body.append(tr);i++;}
    table.append(body);frag.append(table);i--;continue;
   }
   const heading=/^(#{1,4})\s+(.+)$/.exec(line),bullet=/^\s*[-*]\s+(.+)$/.exec(line);
   const node=document.createElement(heading?'h'+Math.min(heading[1].length+2,6):'p');
   if(bullet)node.className='rich-bullet';
   inline(node,heading?heading[2]:bullet?'• '+bullet[1]:line);frag.append(node);
  }
  target.replaceChildren(frag);
 }
 return {render,latex};
});