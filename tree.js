export default function({data, parentElement}) {
  const root = parentElement.querySelector('.computation-tree');
  const nodes = data.nodes, text = Array.from(data.text), n = text.length;
  const accepts = new Set(data.accepts);
  const el = (tag, attrs={}, content=null) => {
    const node = document.createElement(tag);
    for (const [k,v] of Object.entries(attrs)) node.setAttribute(k,v);
    if (content !== null) node.textContent = content;
    return node;
  };
  const svgEl = (tag, attrs={}) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k,v] of Object.entries(attrs)) node.setAttribute(k,v);
    return node;
  };

  // ---- Layout: columns follow input position, ε-hops shift right a little ----
  const COL = 170, EPS_SHIFT = 85, ROW = 70;
  const byId = new Map(nodes.map(nd => [nd.id, {...nd, children: []}]));
  for (const nd of byId.values()) if (nd.parent !== null) byId.get(nd.parent).children.push(nd);
  const rootNode = byId.get(0);
  let leafRow = 0;
  (function place(nd, epsRun) {
    nd.eps = nd.via === 'ε' ? epsRun + 1 : 0;
    nd.x = 60 + nd.pos * COL + nd.eps * EPS_SHIFT;
    if (!nd.children.length) { nd.y = 50 + leafRow++ * ROW; return; }
    for (const c of nd.children) place(c, nd.eps);
    nd.y = (nd.children[0].y + nd.children[nd.children.length - 1].y) / 2;
  })(rootNode, 0);
  const all = [...byId.values()];
  const maxX = Math.max(...all.map(d => d.x)) + 80, maxY = Math.max(...all.map(d => d.y)) + 60;

  // A node is visible at step k when the symbols it needed have been read.
  const visibleAt = nd => nd.pos;
  // When a node's final status becomes known.
  const settledAt = nd => nd.status === 'dead' ? nd.pos + 1 : nd.status === 'inner' ? Infinity : n;

  const saved = root._treeState || {step: 0, view: null};
  let current = Math.min(saved.step, n), playing = false, timer = null;
  let view = saved.view || [0, 0, Math.max(maxX, 900), Math.max(maxY, 300)];

  root.replaceChildren();
  const toolbar = el('div', {class: 'toolbar'});
  const button = (label, title, action, cls='') => {
    const b = el('button', {type: 'button', title, 'aria-label': title, class: cls}, label);
    b.onclick = action; return b;
  };
  const play = button('▶ Play', 'Play or pause', () => togglePlay(), 'primary');
  toolbar.append(button('↺', 'Restart', () => go(0)), button('←', 'Previous symbol', () => go(current - 1)),
                 play, button('→', 'Next symbol', () => go(current + 1)), button('⇥', 'Jump to result', () => go(n)));
  const speed = el('select', {'aria-label': 'Playback speed'});
  for (const [label, ms] of [['0.5×', 1800], ['1×', 900], ['2×', 450], ['4×', 225]]) {
    const o = el('option', {value: ms}, label); if (ms === 900) o.selected = true; speed.append(o);
  }
  const speedLabel = el('label', {class: 'speed'}, 'Speed'); speedLabel.append(speed);
  toolbar.append(speedLabel);

  const tape = el('div', {class: 'tape'});
  const status = el('div', {class: 'status'});
  const panel = el('div', {class: 'canvas-panel'});
  const tools = el('div', {class: 'view-tools'});
  const pathToggle = el('input', {type: 'checkbox', id: 'pathToggle'}); pathToggle.checked = true;
  const pathLabel = el('label', {for: 'pathToggle', class: 'toggle'}); pathLabel.append(pathToggle, ' Highlight accepting path');
  pathToggle.onchange = () => draw();
  tools.append(button('Fit', 'Fit tree to view', () => { fit(); draw(); }),
               button('+', 'Zoom in', () => zoom(.8)), button('−', 'Zoom out', () => zoom(1.25)),
               pathLabel, el('span', {class: 'hint'}, 'Drag to pan · scroll to zoom'));
  const svg = svgEl('svg', {class: 'tree', role: 'img', 'aria-label': 'Computation tree'});
  panel.append(tools, svg);
  const legend = el('div', {class: 'legend'});
  for (const [cls, label] of [['live', 'Live branch'], ['accept', 'Accepts'], ['reject', 'Ends in non-final state'],
                              ['dead', 'Dies (no move)'], ['eps', 'ε-move']])
    { const item = el('span'); item.append(el('i', {class: cls}), label); legend.append(item); }
  const verdict = el('div', {class: 'verdict'});
  root.append(toolbar, tape, status, panel, legend, verdict);

  const defs = svgEl('defs');
  for (const [id, color] of [['arr', '#94a3b8'], ['arrLive', '#6366f1'], ['arrOk', '#16a34a'], ['arrEps', '#d97706']]) {
    const m = svgEl('marker', {id: id + data.uid, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 11, markerHeight: 11, markerUnits: 'userSpaceOnUse', orient: 'auto-start-reverse'});
    m.append(svgEl('path', {d: 'M0,0 L10,5 L0,10 z', fill: color})); defs.append(m);
  }

  function fit() { view = [0, 0, Math.max(maxX, 900), Math.max(maxY, 300)]; }
  function zoom(f, cx = view[0] + view[2] / 2, cy = view[1] + view[3] / 2) {
    view = [cx - (cx - view[0]) * f, cy - (cy - view[1]) * f, view[2] * f, view[3] * f]; draw();
  }
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    zoom(e.deltaY > 0 ? 1.1 : .9, view[0] + (e.clientX - r.left) / r.width * view[2],
         view[1] + (e.clientY - r.top) / r.height * view[3]);
  }, {passive: false});
  let drag = null;
  svg.onpointerdown = e => { drag = {x: e.clientX, y: e.clientY, v: [...view]}; svg.setPointerCapture(e.pointerId); };
  svg.onpointermove = e => {
    if (!drag) return;
    const r = svg.getBoundingClientRect();
    view[0] = drag.v[0] - (e.clientX - drag.x) / r.width * view[2];
    view[1] = drag.v[1] - (e.clientY - drag.y) / r.height * view[3]; draw();
  };
  svg.onpointerup = () => { drag = null; root._treeState = {step: current, view}; };

  function draw() {
    svg.replaceChildren(defs);
    svg.setAttribute('viewBox', view.join(' '));
    const showPath = pathToggle.checked && current === n;
    // Column guides labelled with the symbol read to enter them.
    for (let p = 0; p <= n; p++) {
      const x = 60 + p * COL - 30;
      if (p > 0) svg.append(svgEl('line', {x1: x, y1: 10, x2: x, y2: maxY, class: 'guide' + (p === current ? ' now' : '')}));
      const t = svgEl('text', {x: 60 + p * COL, y: 22, class: 'col-label' + (p === current ? ' now' : '')});
      t.textContent = p === 0 ? 'start' : `read “${text[p - 1]}”`; svg.append(t);
    }
    for (const nd of all) {
      if (nd.parent === null || visibleAt(nd) > current) continue;
      const p = byId.get(nd.parent);
      const ok = showPath && nd.on_accept_path, eps = nd.via === 'ε';
      const live = !ok && nd.pos === current && current < n;
      const cls = ok ? 'edge ok' : eps ? 'edge eps' : live ? 'edge live' : 'edge';
      const mk = ok ? 'arrOk' : eps ? 'arrEps' : live ? 'arrLive' : 'arr';
      const x1 = p.x + 20, x2 = nd.x - 22, mx = (x1 + x2) / 2;
      svg.append(svgEl('path', {d: `M${x1},${p.y} C${mx},${p.y} ${mx},${nd.y} ${x2},${nd.y}`, class: cls, 'marker-end': `url(#${mk}${data.uid})`}));
      const lbl = svgEl('text', {x: mx, y: (p.y + nd.y) / 2 - 6, class: 'edge-label' + (eps ? ' eps' : '')});
      lbl.textContent = nd.via; svg.append(lbl);
    }
    for (const nd of all) {
      if (visibleAt(nd) > current) continue;
      const settled = settledAt(nd) <= current;
      let cls = 'node';
      if (showPath && nd.on_accept_path) cls += ' ok';
      if (settled) cls += ' ' + nd.status;
      else if (nd.pos === current) cls += ' live';
      const g = svgEl('g', {class: cls, transform: `translate(${nd.x},${nd.y})`});
      g.append(svgEl('circle', {r: 20, class: 'outer'}));
      if (accepts.has(nd.state)) g.append(svgEl('circle', {r: 15.5, class: 'inner'}));
      const t = svgEl('text', {y: 4, 'text-anchor': 'middle'}); t.textContent = nd.state; g.append(t);
      if (settled && ['dead', 'reject', 'accept', 'cut'].includes(nd.status)) {
        const tag = svgEl('text', {x: 28, y: 4, class: 'tag'});
        tag.textContent = {dead: '✗ stuck', reject: '✗ not final', accept: '✓ accept', cut: '… (limit)'}[nd.status];
        g.append(tag);
      }
      const title = svgEl('title');
      title.textContent = `${nd.state} after reading “${text.slice(0, nd.pos).join('') || 'ε'}”`;
      g.append(title); svg.append(g);
    }
  }

  function render() {
    tape.replaceChildren();
    text.forEach((ch, i) => tape.append(el('span', {class: 'symbol' + (i < current ? ' read' : '') + (i === current - 1 ? ' just' : '')}, ch)));
    if (!n) tape.append(el('span', {class: 'symbol just'}, 'ε'));
    const live = all.filter(d => d.pos === current && settledAt(d) > current).length;
    const died = all.filter(d => settledAt(d) <= current && d.status === 'dead').length;
    status.textContent = current < n
      ? `Step ${current} / ${n} · ${live} live branch${live === 1 ? '' : 'es'}${died ? ` · ${died} died so far` : ''}`
      : `Step ${n} / ${n} · input fully read`;
    const s = data.summary;
    verdict.className = 'verdict' + (current === n ? (data.accepted ? ' yes' : ' no') : '');
    verdict.textContent = current < n ? 'Play to the end to see the verdict.'
      : data.accepted
        ? `ACCEPTED — ${s.accepting} of ${s.branches} branch${s.branches === 1 ? '' : 'es'} end${s.branches === 1 ? 's' : ''} in an accepting state. One accepting branch is enough.`
        : `REJECTED — none of the ${s.branches} branch${s.branches === 1 ? '' : 'es'} accept (${s.dead} died, ${s.rejecting} ended in a non-final state${s.cut ? `, ${s.cut} cut off` : ''}).`;
    draw();
    root._treeState = {step: current, view};
  }
  function stop() { playing = false; clearTimeout(timer); play.textContent = '▶ Play'; }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { current = Math.min(n, current + 1); render(); if (current === n) stop(); else schedule(); }, Number(speed.value));
  }
  function togglePlay() {
    if (playing) { stop(); return; }
    if (current === n) current = 0;
    playing = true; play.textContent = 'Ⅱ Pause'; render(); schedule();
  }
  function go(step) { stop(); current = Math.max(0, Math.min(n, step)); render(); }
  render();
  return () => { clearTimeout(timer); };
}
