const test=require('node:test'), assert=require('node:assert/strict');
const rich=require('../src/rizzler/web/rich-text.js');
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this._text='';}
  append(...elements){this.children.push(...elements)}
  replaceChildren(...elements){this.children=elements}
  set textContent(value){this._text=String(value);this.children=[]}
  get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('')}
  setAttribute(k,v){this.attributes[k]=v}
}
global.document={
  createElement:tag=>new Element(tag),
  createTextNode:text=>({textContent:text}),
  createDocumentFragment:()=>new Element('fragment')
};
function all(node){return [node,...(node.children||[]).flatMap(all)]}
test('math is readable and not literal dollar-delimited',()=>{
 const parent=new Element('main');
 rich.render(parent,'The answer is \\(a^2 = 7\\), and $b=2i$.');
 assert.match(parent.textContent,/a² = 7/);
 assert.doesNotMatch(parent.textContent,/\$|\\\(/);
 assert.equal(all(parent).filter(x=>x.className==='inline-math').length,2);
});
test('semantic table is rendered with header and data cells',()=>{
 const parent=new Element('main');
 rich.render(parent,'| Variable | Value |\n| --- | --- |\n| a | \\(1.2\\) |\n| b | \\(2.1i\\) |');
 assert.equal(all(parent).filter(x=>x.tagName==='table').length,1);
 assert.equal(all(parent).filter(x=>x.tagName==='th').length,2);
 assert.equal(all(parent).filter(x=>x.tagName==='td').length,4);
});
test('source links are safe and model HTML remains literal text',()=>{
 const parent=new Element('main');
 rich.render(parent,'<img src=x onerror=alert(1)>\n[Reference](https://example.com/report)');
 assert.match(parent.textContent,/<img/);
 assert.equal(all(parent).filter(x=>x.tagName==='img').length,0);
 const links=all(parent).filter(x=>x.tagName==='a');
 assert.equal(links.length,1);
 assert.equal(links[0].href,'https://example.com/report');
 assert.match(links[0].rel,/noopener/);
});