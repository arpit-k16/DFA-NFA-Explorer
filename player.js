export default function({data, parentElement}) {
  const root = parentElement.querySelector('.automata-player');
  const m = data.machine, steps = data.steps, symbols = Array.from(data.text);
  const n = steps.length - 1;
  const el = (tag, attrs={}, content=null) => {
    const node = document.createElement(tag);
    for (const [k,v] of Object.entries(attrs)) node.setAttribute(k,v);
    if (content !== null) node.textContent = content;
    return node;
  };
  const svgEl = (tag, attrs={}) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg',tag);
    for (const [k,v] of Object.entries(attrs)) node.setAttribute(k,v);
    return node;
  };
  const asSet = values => values.length ? '{' + [...values].sort().join(', ') + '}' : '∅';
  // Save local view across unrelated Streamlit rerenders. A new run has a new key.
  const saved = root._playerState || {step:0, positions:null, view:[0,0,1000,460], layout:'Layered'};
  let current = Math.min(saved.step,n), playing=false, timer=null, disposed=false;
  let positions = saved.positions, view = [...saved.view], selected=null, drag=null;
  root.replaceChildren();
  const toolbar = el('div',{class:'toolbar'});
  const button = (label, title, action, cls='') => {
    const b = el('button',{type:'button',title,'aria-label':title,class:cls},label);
    b.onclick=action; return b;
  };
  const first = button('↺','Restart (Home)',()=>go(0));
  const back = button('←','Previous symbol (Left arrow)',()=>go(current-1));
  const play = button('▶ Play','Play or pause (Space)',()=>togglePlay(),'primary');
  const next = button('→','Next symbol (Right arrow)',()=>go(current+1));
  const end = button('⇥','Jump to result (End)',()=>go(n));
  toolbar.append(first,back,play,next,end);
  const speedLabel=el('label',{class:'speed'},'Speed');
  const speed=el('select',{'aria-label':'Playback speed'});
  for (const [label,ms] of [['0.5×',1600],['1×',800],['2×',400],['4×',200]]) {
    const option=el('option',{value:ms},label); if(ms===800) option.selected=true; speed.append(option);
  }
  speed.onchange=()=>{if(playing) schedule()}; speedLabel.append(speed); toolbar.append(speedLabel);
  const scrub=el('div',{class:'scrub'});
  const range=el('input',{type:'range',min:0,max:n,value:current,'aria-label':'Simulation step'});
  range.disabled=n===0;
  const progress=el('span'); range.oninput=()=>go(Number(range.value)); scrub.append(range,progress);
  const tapePanel=el('div',{class:'tape-panel'});
  tapePanel.append(el('div',{class:'eyebrow'},'Input tape'));
  const tape=el('div',{class:'tape'}), tapeFooter=el('div',{class:'tape-footer'});
  tapePanel.append(tape,tapeFooter);
  const panel=el('div',{class:'canvas-panel'}), tools=el('div',{class:'view-tools'});
  const layout=el('select',{'aria-label':'Graph layout'});
  for(const name of ['Layered','Circular']) {
    const option=el('option',{},name); option.selected=name===saved.layout; layout.append(option);
  }
  layout.onchange=()=>{positions=null; arrange(); fit(); draw(); persist()};
  tools.append(layout,button('+','Zoom in',()=>zoom(.8)),button('−','Zoom out',()=>zoom(1.25)),
    button('Fit','Fit graph to view',()=>{fit();draw();persist()}),
    button('Save SVG','Download diagram as SVG',downloadSvg),
    el('span',{class:'hint'},'Drag nodes · drag canvas to pan · scroll to zoom'));
  const stage=el('div',{class:'stage',tabindex:0,'aria-label':'Automaton. Space to play, arrow keys to step.'});
  const svg=svgEl('svg',{class:'graph',role:'img','aria-label':'Interactive finite automaton'});
  stage.append(svg);
  const legend=el('div',{class:'legend'});
  for(const [cls,label] of [['','Live state / symbol move'],['green','Accepting at end'],['amber','ε-move (no input consumed)']]) {
    const item=el('span');item.append(el('i',{class:'dot '+cls}),document.createTextNode(label));legend.append(item);
  }
  legend.append(el('span',{},'◎ accepting · → start'));
  panel.append(tools,stage,legend);
  const status=el('div',{class:'status','aria-live':'polite'});
  const inspector=el('div',{class:'inspector'},'Select a state to inspect its outgoing transitions.');
  const details=el('details');details.append(el('summary',{},'Transition trace · click a row to jump'));
  const traceScroll=el('div',{class:'trace-scroll'}), table=el('table');
  const head=el('thead'), headrow=el('tr');
  for(const name of ['Step','Symbol','Before','After','Explanation']) headrow.append(el('th',{scope:'col'},name));
  head.append(headrow); const body=el('tbody'), traceRows=[];
  steps.forEach((step,i)=>{
    const row=el('tr',{tabindex:0,'aria-label':`Jump to step ${i}`});
    for(const value of [i,step.sym===null?'—':step.sym,i===0?'—':asSet(step.before),asSet(step.after),step.note]) row.append(el('td',{},value));
    row.onclick=()=>go(i);row.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();go(i)}};
    body.append(row);traceRows.push(row);
  });
  table.append(head,body); traceScroll.append(table); details.append(traceScroll);
  root.append(toolbar,scrub,tapePanel,panel,inspector,status,details);

  function arrange() {
    if(positions) return;
    positions=Object.create(null);
    if(layout.value==='Circular') {
      const radius=Math.max(100,m.states.length*24);
      m.states.forEach((s,i)=>{
        const angle=-Math.PI/2+2*Math.PI*i/m.states.length;
        positions[s]=m.states.length===1?[500,230]:[500+radius*Math.cos(angle),230+radius*Math.sin(angle)];
      });
    } else {
      const depth=new Map([[m.start,0]]), queue=[m.start];
      for(let i=0;i<queue.length;i++) {
        for(const [u,,v] of data.edges) if(u===queue[i]&&!depth.has(v)) {depth.set(v,depth.get(u)+1);queue.push(v)}
      }
      const last=Math.max(...depth.values(),0)+1, layers=new Map();
      for(const s of m.states){const d=depth.get(s)??last;if(!layers.has(d))layers.set(d,[]);layers.get(d).push(s)}
      for(const [d,states] of layers) states.forEach((s,i)=>{positions[s]=[140+d*210,230+(i-(states.length-1)/2)*125]});
    }
  }
  function fit() {
    const points=Object.values(positions), xs=points.map(p=>p[0]), ys=points.map(p=>p[1]);
    const left=Math.min(...xs)-130, top=Math.min(...ys)-120;
    const w=Math.max(550,Math.max(...xs)-Math.min(...xs)+260);
    const h=Math.max(350,Math.max(...ys)-Math.min(...ys)+240);
    const ratio=(svg.clientWidth||1000)/(svg.clientHeight||460);
    const width=Math.max(w,h*ratio),height=width/ratio;
    view=[left-(width-w)/2,top-(height-h)/2,width,height];
  }
  function persist(){root._playerState={step:current,positions,view:[...view],layout:layout.value}}
  function zoom(factor,point=null) {
    const width=Math.max(100,Math.min(12000,view[2]*factor)), scale=width/view[2];
    const p=point||[view[0]+view[2]/2,view[1]+view[3]/2];
    view=[p[0]-(p[0]-view[0])*scale,p[1]-(p[1]-view[1])*scale,width,view[3]*scale];
    draw();persist();
  }
  function point(event) {
    const p=svg.createSVGPoint();p.x=event.clientX;p.y=event.clientY;
    const converted=p.matrixTransform(svg.getScreenCTM().inverse());return [converted.x,converted.y];
  }
  const edgeKey=e=>JSON.stringify(e);
  function draw() {
    svg.replaceChildren();svg.setAttribute('viewBox',view.join(' '));
    const defs=svgEl('defs');
    for(const [id,color] of [['normal','#94a3b8'],['live','#6366f1'],['eps','#d97706']]) {
      const marker=svgEl('marker',{id,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:8,markerHeight:8,orient:'auto',markerUnits:'userSpaceOnUse'});
      marker.append(svgEl('path',{d:'M0 0 L10 5 L0 10 Z',fill:color}));defs.append(marker);
    }
    svg.append(defs);
    const step=steps[current], active=new Set([...step.taken,...step.eps].map(edgeKey)), alive=new Set(step.after);
    // Group only equally styled, equally active symbol edges. Epsilon is always
    // independent, so a consuming edge can never falsely appear to be epsilon.
    const groups=new Map();
    for(const edge of data.edges) {
      const [u,a,v]=edge,isActive=active.has(edgeKey(edge));
      const key=JSON.stringify([u,v,a==='ε',isActive]);
      if(!groups.has(key))groups.set(key,{u,v,epsilon:a==='ε',isActive,labels:[]});
      groups.get(key).labels.push(a);
    }
    const pairs=new Map();
    for(const g of groups.values()) {const key=JSON.stringify([g.u,g.v]);if(!pairs.has(key))pairs.set(key,[]);pairs.get(key).push(g)}
    for(const g of groups.values()) {
      const [x,y]=positions[g.u],[tx,ty]=positions[g.v];
      const siblings=pairs.get(JSON.stringify([g.u,g.v])),lane=siblings.indexOf(g);
      const reverse=pairs.has(JSON.stringify([g.v,g.u]));
      let path,lx,ly;
      if(g.u===g.v) {
        const spread=65+lane*38;
        path=`M ${x-22} ${y-22} C ${x-spread} ${y-115-lane*40} ${x+spread} ${y-115-lane*40} ${x+22} ${y-22}`;
        lx=x;ly=y-94-lane*30;
      } else {
        const dx=tx-x,dy=ty-y,len=Math.hypot(dx,dy)||1,ux=dx/len,uy=dy/len;
        // Long edges in layered layouts must route around intermediate states.
        const skipBend=layout.value==='Layered'&&Math.abs(dx)>250?110*Math.sign(dx):0;
        const bend=(reverse?55:skipBend)+(lane-(siblings.length-1)/2)*55;
        const cx=(x+tx)/2-uy*bend,cy=(y+ty)/2+ux*bend;
        const l1=Math.hypot(cx-x,cy-y)||1,l2=Math.hypot(cx-tx,cy-ty)||1;
        const sx=x+(cx-x)/l1*33,sy=y+(cy-y)/l1*33;
        const ex=tx+(cx-tx)/l2*35,ey=ty+(cy-ty)/l2*35;
        path=`M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`;
        lx=.25*sx+.5*cx+.25*ex;ly=.25*sy+.5*cy+.25*ey-10;
      }
      const cls=(g.epsilon?' epsilon':'')+(g.isActive?' active':'');
      const p=svgEl('path',{d:path,class:'edge'+cls,'marker-end':`url(#${g.isActive?(g.epsilon?'eps':'live'):'normal'})`});
      const label=svgEl('text',{x:lx,y:ly,'text-anchor':'middle',class:'edge-label'+cls});label.textContent=g.labels.join(', ');
      svg.append(p,label);
    }
    const [sx,sy]=positions[m.start];
    svg.append(svgEl('path',{d:`M ${sx-95} ${sy} L ${sx-37} ${sy}`,class:'edge','marker-end':'url(#normal)'}));
    const startLabel=svgEl('text',{x:sx-95,y:sy-10,class:'edge-label'});startLabel.textContent='start';svg.append(startLabel);
    for(const state of m.states) {
      const [x,y]=positions[state],live=alive.has(state),finalLive=current===n&&data.accepted&&live&&m.accepts.includes(state);
      const g=svgEl('g',{class:'node'+(live?' live':'')+(finalLive?' final-live':''),transform:`translate(${x} ${y})`,tabindex:0,role:'button','aria-label':`State ${state}${live?', active':''}${m.accepts.includes(state)?', accepting':''}`});
      const title=svgEl('title');title.textContent=state;g.append(title,svgEl('circle',{r:32,class:'outer'}));
      if(m.accepts.includes(state)) g.append(svgEl('circle',{r:26,class:'inner'}));
      const text=svgEl('text',{'text-anchor':'middle',dy:4});text.textContent=state;
      if(state.length>7){text.setAttribute('textLength',51);text.setAttribute('lengthAdjust','spacingAndGlyphs')}
      g.append(text);
      g.onpointerdown=e=>{e.stopPropagation();stage.focus();selected=state;inspect();drag={state,origin:point(e)};svg.setPointerCapture(e.pointerId)};
      g.onkeydown=e=>{if(e.key==='Enter'){selected=state;inspect()}};
      svg.append(g);
    }
  }
  function inspect() {
    const outgoing=data.edges.filter(e=>e[0]===selected).map(([,a,v])=>`${a} → ${v}`);
    inspector.textContent=`${selected}${selected===m.start?' · start':''}${m.accepts.includes(selected)?' · accepting':''} | ${outgoing.length?outgoing.join('   ·   '):'No outgoing transitions'}`;
  }
  function render() {
    const step=steps[current];range.value=current;progress.textContent=`Step ${current} / ${n}`;
    first.disabled=back.disabled=current===0;next.disabled=end.disabled=current===n;play.disabled=n===0;
    tape.replaceChildren();
    if(!symbols.length)tape.append(el('span',{},'ε — empty string'));
    else symbols.forEach((symbol,i)=>{
      const cls=i<current-1?' read':i===current-1?(step.stuck?' failed':' just'):i===current?' next':'';
      tape.append(el('span',{class:'symbol'+cls,title:`Position ${i+1}`},symbol));
    });
    tapeFooter.textContent=`Read: ${symbols.slice(0,current).join('')||'ε'}  ·  Remaining: ${symbols.slice(current).join('')||'ε'}`;
    status.className='status'+(current===n?(data.accepted?' accepted':' rejected'):'');status.replaceChildren();
    status.append(el('strong',{},current===n?(data.accepted?'Accepted':'Rejected'):(current===0?'Ready to explore':`${step.after.length} live state${step.after.length===1?'':'s'}`)),
      el('div',{class:'detail'},current===n?data.explanation:step.note));
    const chips=el('div',{class:'states'});
    for(const s of step.after.length?step.after:['∅'])chips.append(el('span',{class:'state-chip'},s));status.append(chips);
    if(current!==n)status.append(el('div',{class:'inspector'},`Next symbol: ${symbols[current]}`));
    traceRows.forEach((r,i)=>{r.classList.toggle('selected',i===current);r.setAttribute('aria-current',String(i===current))});
    draw();persist();
  }
  function stop(){playing=false;clearTimeout(timer);play.textContent='▶ Play'}
  function schedule(){clearTimeout(timer);timer=setTimeout(()=>{if(disposed)return;current=Math.min(n,current+1);render();if(current===n)stop();else schedule()},Number(speed.value))}
  function togglePlay(){if(playing){stop();return}if(current===n)current=0;playing=true;play.textContent='Ⅱ Pause';render();schedule()}
  function go(step){stop();current=Math.max(0,Math.min(n,step));render()}
  function downloadSvg() {
    const copy=svg.cloneNode(true);
    // Resolve CSS from the actual graph so the exported SVG is standalone.
    const originals=[svg,...svg.querySelectorAll('*')], clones=[copy,...copy.querySelectorAll('*')];
    const properties=['fill','stroke','stroke-width','stroke-dasharray','font-family','font-size','font-weight','paint-order','stroke-linejoin'];
    originals.forEach((node,i)=>{const style=getComputedStyle(node);for(const property of properties)clones[i].style.setProperty(property,style.getPropertyValue(property))});
    copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width','1000');copy.setAttribute('height','460');
    const background=svgEl('rect',{x:view[0],y:view[1],width:view[2],height:view[3],fill:getComputedStyle(root).getPropertyValue('--soft').trim()||'#f6f8fc'});
    copy.insertBefore(background,copy.firstChild);
    const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}));
    const link=el('a',{href:url,download:'automaton.svg'});link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  svg.onpointerdown=e=>{if(e.button!==0)return;stage.focus();drag={state:null,origin:point(e),view:[...view]};svg.setPointerCapture(e.pointerId)};
  svg.onpointermove=e=>{
    if(!drag)return;const p=point(e);
    if(drag.state){positions[drag.state]=p;draw()}
    else {view[0]+=drag.origin[0]-p[0];view[1]+=drag.origin[1]-p[1];svg.setAttribute('viewBox',view.join(' '))}
  };
  svg.onpointerup=svg.onpointercancel=e=>{drag=null;if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);persist()};
  svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.1:1/1.1,point(e))},{passive:false});
  stage.onkeydown=e=>{
    // Native selects and buttons keep their normal keyboard interaction.
    if(e.target!==stage&&e.target.tagName.toLowerCase()!=='svg')return;
    const actions={' ':togglePlay,ArrowRight:()=>go(current+1),ArrowLeft:()=>go(current-1),Home:()=>go(0),End:()=>go(n)};
    if(actions[e.key]){e.preventDefault();actions[e.key]()}
  };
  arrange();if(!saved.positions)fit();render();
  return ()=>{disposed=true;clearTimeout(timer);persist()};
}
