// Data ships as application/json, not as JavaScript source. As executable
// source the browser must parse 2.3 MB before it can paint ANYTHING -- the
// page sat blank for 25 s and looked broken. As inert text the parser only
// scans it, the markup above paints immediately, and JSON.parse runs after.
const D=JSON.parse(document.getElementById("d-model").textContent);
D.base=JSON.parse(document.getElementById("d-base").textContent);
const $=id=>document.getElementById(id);
// Errors thrown inside an event handler are invisible from outside a
// cross-origin frame. Put them where they can be read.
window.addEventListener("error",ev=>{
  const h=document.getElementById("modeHint");
  if(h)h.innerHTML='<b style="color:var(--red)">'+(ev.message||"error")+'</b><br>'+
    '<span style="font-size:10px">'+((ev.filename||"").split("/").pop()||"")+':'+(ev.lineno||"")+'</span>';
});
const SC_LABEL={dry:"Dry day, free flow",peak:"Peak hour congestion",flood5:"5-year flood",
  flood25:"25-year flood",flood100:"100-year flood",f2015:"2015 flood replay"};
const BANDS=[["within","--green"],["+2 min","--yellow"],["+2-7 min","--amber"],["beyond","--red"]];
let svc="ems", scen="dry", thrMin=7, kWant=3, picked=[];
let PLACE=false;   // manual site placement mode
const cssv=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const C=D.cells, N=C.lat.length, POP=C.pop, TOTPOP=D.meta.population;
const S=()=>D.services[svc], SS=()=>S().scenarios[scen];
const offsets=D.hex;

// travel budget = threshold minus the service's alarm and turnout (Finding F-03)
const budget=()=>Math.round(thrMin*60 - S().t_alarm_s - S().t_turnout_s);

// ---------- view: Web Mercator, locked to the raster's pixel grid
// Tiles are Web Mercator. The projection must match or the hexagons drift off
// the streets -- across the 55 km this city spans, Mercator and equirectangular
// disagree by about a kilometre. World coordinates here ARE basemap image
// pixels, so alignment is exact by construction rather than by calibration.
let Z=1, PANX=0, PANY=0, BASE=1, BX=0, BY=0;
let W=0,H=0,dpr=1,PX=null,PY=null;
let SEL=[], SCOPE='ward', SELKIND=null, SELKEY=null;   // selection by administrative area
const layers={flood:true,cov:true,st:true,sites:true,zones:true,base:true};
const RM=D.raster;
const mercY=lat=>Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
const MY0=mercY(RM.north), MY1=mercY(RM.south);
const wx=lon=>(lon-RM.west)/(RM.east-RM.west)*RM.width;
const wy=lat=>(MY0-mercY(lat))/(MY0-MY1)*RM.height;

const IMG={};
function loadRaster(cb){
  let n=0; const done=()=>{if(++n===2)cb();};
  for(const k of ["light","dark"]){
    const im=new Image(); im.onload=done; im.onerror=done;
    im.src=D.rasterData[k]; IMG[k]=im;
  }
}
const isDark=()=>{const t=document.documentElement.dataset.theme;
  return t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches);};

function fit(){
  const st=$("stage"); dpr=Math.min(window.devicePixelRatio||1,2);
  W=st.clientWidth; H=st.clientHeight;
  const cv=$("cv"); cv.width=W*dpr; cv.height=H*dpr;
  // frame the GCC outline, not the whole raster
  let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
  for(const ring of D.base.outline) for(const [lo,la] of ring){
    const x=wx(lo),y=wy(la); if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;}
  const pad=20;
  BASE=Math.min((W-2*pad)/(x1-x0),(H-2*pad)/(y1-y0));
  BX=(W-(x1-x0)*BASE)/2-x0*BASE; BY=(H-(y1-y0)*BASE)/2-y0*BASE;
  recalc(); draw();
}
const sc=()=>BASE*Z;
function recalc(){
  const S_=sc(), OX=BX*Z+PANX, OY=BY*Z+PANY;
  PX=new Float32Array(N); PY=new Float32Array(N);
  for(let i=0;i<N;i++){PX[i]=wx(C.lon[i])*S_+OX; PY[i]=wy(C.lat[i])*S_+OY;}
  GRID=null;   // the grid is in screen space, so it dies with the view
}
const px=lon=>wx(lon)*sc()+BX*Z+PANX, py=lat=>wy(lat)*sc()+BY*Z+PANY;

function path(x,seq,close){
  x.beginPath();
  for(const ring of seq){
    if(ring.length<2)continue;
    x.moveTo(px(ring[0][0]),py(ring[0][1]));
    for(let i=1;i<ring.length;i++) x.lineTo(px(ring[i][0]),py(ring[i][1]));
    if(close)x.closePath();
  }
}

// how far past the budget a cell falls: 0 within, 1 up to +2 min, 2 up to +7, 3 beyond
function band(r,b){ if(r<0)return -1; if(r<=b)return 0;
  if(r<=b+120)return 1; if(r<=b+420)return 2; return 3; }

// The shared hexagon is stored as degree offsets from a centroid; convert it
// once per frame into Mercator pixels using a mid-city reference cell.
function hexPx(S_){
  const i0=(N>>1), la=C.lat[i0], lo=C.lon[i0];
  const cx=wx(lo)*S_, cy=wy(la)*S_;
  return D.hex.map(([dx,dy])=>[wx(lo+dx)*S_-cx, wy(la+dy)*S_-cy]);
}

function draw(){
  const cv=$("cv"), x=cv.getContext("2d");
  x.setTransform(dpr,0,0,dpr,0,0);
  x.fillStyle=cssv("--sea"); x.fillRect(0,0,W,H);
  const B=D.base, S_=sc();

  // imported basemap: real cartography, drawn as one image
  if(layers.base){
    const im=IMG[isDark()?"dark":"light"];
    if(im&&im.complete&&im.naturalWidth){
      const OX=BX*Z+PANX, OY=BY*Z+PANY;
      x.imageSmoothingQuality="high";
      x.drawImage(im,OX,OY,RM.width*S_,RM.height*S_);
    }
  }

  // flood extent, when the scenario is a wet one
  if(layers.flood&&B.flood[scen]){
    path(x,B.flood[scen],true);
    x.fillStyle=cssv("--floodfill"); x.fill();
    x.strokeStyle=cssv("--floodline"); x.lineWidth=.8; x.stroke();
  }

  // coverage, batched by colour so 3,838 cells cost five fills
  if(layers.cov){
    const resp=SS().resp, b=budget(), hx=hexPx(S_);
    const covered=new Uint8Array(N);
    if(picked.length){
      const {cov_indptr:ip,cov_indices:ix}=SS(), set=new Set(picked);
      for(let i=0;i<N;i++){for(let p=ip[i];p<ip[i+1];p++) if(set.has(ix[p])){covered[i]=1;break;}}
    }
    const buckets=[[],[],[],[],[],[]];   // 0-3 bands, 4 = no route, 5 = newly covered
    for(let i=0;i<N;i++){
      const bd=band(resp[i],b);
      buckets[bd<0?4:(covered[i]&&bd>0?5:bd)].push(i);
    }
    const fills=[cssv("--green"),cssv("--yellow"),cssv("--amber"),cssv("--red"),
                 cssv("--nodata"),cssv("--green")];
    x.globalAlpha=.72;
    buckets.forEach((ids,k)=>{
      if(!ids.length)return;
      x.globalAlpha = k===5?.5:(k===4?.42:.58);
      x.fillStyle=fills[k]; x.beginPath();
      for(const i of ids){
        x.moveTo(PX[i]+hx[0][0],PY[i]+hx[0][1]);
        for(let v=1;v<6;v++) x.lineTo(PX[i]+hx[v][0],PY[i]+hx[v][1]);
        x.closePath();
      }
      x.fill();
    });
    x.globalAlpha=1;
  }

  if(layers.zones){x.strokeStyle=cssv("--zoneline"); x.lineWidth=Math.max(.7,1.1*Z);
    path(x,B.zones,true); x.stroke();}
  x.strokeStyle=cssv("--coast"); x.lineWidth=Math.max(1.2,1.6*Z);
  path(x,B.outline,true); x.stroke();

  if(SELKIND==="ward"&&D.base.ward_rings[String(SELKEY)]){
    path(x,D.base.ward_rings[String(SELKEY)],true);
    x.strokeStyle=cssv("--accent"); x.lineWidth=2.2; x.stroke();
  } else if(SELKIND==="zone"){
    const wm=D.base.ward_meta||{};
    for(const [zid,rg] of Object.entries(D.base.zone_rings||{})){
      const any=Object.entries(wm).find(([,v])=>v.zone===SELKEY);
      if(!any)break;
    }
    // a zone's outline is the union of its wards' rings
    const rs=[];
    for(const [wid,v] of Object.entries(wm)) if(v.zone===SELKEY)
      rs.push(...(D.base.ward_rings[wid]||[]));
    path(x,rs,true); x.strokeStyle=cssv("--accent"); x.lineWidth=1.6; x.stroke();
  }

  if(SEL.length){
    const hx=hexPx(S_);
    x.strokeStyle=cssv("--accent"); x.lineWidth=1.1; x.beginPath();
    for(const i of SEL){
      x.moveTo(PX[i]+hx[0][0],PY[i]+hx[0][1]);
      for(let v=1;v<6;v++) x.lineTo(PX[i]+hx[v][0],PY[i]+hx[v][1]);
      x.closePath();
    }
    x.stroke();
  }

  if(layers.st){
    // 33 identical markers would say all 33 positions are equally trustworthy.
    // They are not: 12 carry an official TNFRS number, 4 came from OSM, 1 is
    // provably a power-station fire post, and 14 are assumed.
    x.strokeStyle="#fff"; x.lineWidth=1.3;
    for(const st of D.stations){
      const X=px(st.lon), Y=py(st.lat), r=Math.max(3.4,4.2*Math.min(Z,1.7));
      x.fillStyle=IDCOL[st.state]||cssv("--navy");
      if(st.state==="unresolved"){
        x.beginPath(); x.moveTo(X,Y-r*1.2); x.lineTo(X+r*1.2,Y+r); x.lineTo(X-r*1.2,Y+r);
        x.closePath(); x.fill(); x.stroke();
      } else {
        x.beginPath(); x.arc(X,Y,r,0,7); x.fill(); x.stroke();
        if(st.state==="assumed"){x.strokeStyle=cssv("--amber"); x.lineWidth=1.6;
          x.beginPath(); x.arc(X,Y,r+2,0,7); x.stroke();
          x.strokeStyle="#fff"; x.lineWidth=1.3;}
      }
    }
  }
  if(layers.sites&&picked.length){
    const cand=S().candidates;
    picked.forEach((j,n)=>{const c=cand[j], X=px(c.lon), Y=py(c.lat);
      x.fillStyle="#7A3FBE"; x.strokeStyle="#fff"; x.lineWidth=1.6;
      x.beginPath(); x.arc(X,Y,Math.max(6,7*Math.min(Z,1.6)),0,7); x.fill(); x.stroke();
      x.fillStyle="#fff"; x.font="600 10px 'IBM Plex Mono',monospace";
      x.textAlign="center"; x.textBaseline="middle"; x.fillText(n+1,X,Y+.5);});
  }
  if(Z>1.35){
    x.fillStyle=cssv("--muted"); x.font="600 10px 'Source Sans 3',sans-serif";
    x.textAlign="center"; x.textBaseline="middle";
    for(const z of D.base.zone_labels) x.fillText(z.n.toUpperCase(),px(z.lon),py(z.lat));
  }
  const km=5, pxkm=(km/111.32)*S_;
  $("sbBar").style.width=Math.max(16,pxkm)+"px"; $("sbTxt").textContent=km+" km";
}

// ---------- pan and zoom
let drag=null;
const cvEl=()=>$("cv");
cvEl().addEventListener("wheel",e=>{
  e.preventDefault();
  const r=cvEl().getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0016), nz=Math.min(14,Math.max(1,Z*f)), k=nz/Z;
  PANX=mx-(mx-PANX-BX*Z)*k-BX*nz; PANY=my-(my-PANY-BY*Z)*k-BY*nz;
  Z=nz; if(Z<=1.001){Z=1;PANX=0;PANY=0;}
  recalc(); draw();
},{passive:false});
let rect=null;
cvEl().addEventListener("mousedown",e=>{
  const r=cvEl().getBoundingClientRect();
  if(e.shiftKey){ rect={x0:e.clientX-r.left,y0:e.clientY-r.top,x1:0,y1:0};
    $("selbox").style.display="block"; return; }
  drag={x:e.clientX,y:e.clientY,px:PANX,py:PANY,moved:false};
  cvEl().style.cursor="grabbing";});
window.addEventListener("mouseup",e=>{
  if(rect){
    const x0=Math.min(rect.x0,rect.x1),x1=Math.max(rect.x0,rect.x1);
    const y0=Math.min(rect.y0,rect.y1),y1=Math.max(rect.y0,rect.y1);
    SEL=[]; for(let i=0;i<N;i++) if(PX[i]>=x0&&PX[i]<=x1&&PY[i]>=y0&&PY[i]<=y1) SEL.push(i);
    rect=null; $("selbox").style.display="none"; paintSel(); return;
  }
  if(drag&&!drag.moved){
    const r=cvEl().getBoundingClientRect();
    const mx=e.clientX-r.left, my=e.clientY-r.top;
    // Manual placement: click a candidate site to add or remove it by hand, and
    // every statistic recomputes off the same coverage matrix the optimiser
    // uses. Without this the console can only show what the optimiser chose --
    // and per ADR-005 the optimiser's list is not identified at current
    // positional accuracy, so being able to ask "what if we put one HERE"
    // is the honest interaction.
    if(PLACE){
      const j=nearestCandidate(mx,my);
      if(j>=0){
        const at=picked.indexOf(j);
        if(at>=0) picked.splice(at,1); else picked.push(j);
        paintSites(); draw(); paint();
        $("copyMsg").textContent=(at>=0?"removed ":"added ")+"candidate "+j+" (manual)";
        setTimeout(()=>{if($("copyMsg").textContent.endsWith("(manual)"))
          $("copyMsg").textContent="";},2200);
      } else $("copyMsg").textContent="no candidate site near that point";
      drag=null; return;
    }
    const i=nearestCell(mx,my);
    if(i<0){SEL=[];SELKIND=null;paintSel();}
    else if(SCOPE==="cell") selectArea("cell",i);
    else if(SCOPE==="zone"){
      const wm=D.base.ward_meta||{}, z=(wm[String(C.ward[i])]||{}).zone;
      z?selectArea("zone",z):selectArea("cell",i);
    } else selectArea("ward",C.ward[i]);
  }
  drag=null; cvEl().style.cursor="crosshair";});
window.addEventListener("mousemove",e=>{
  const r=cvEl().getBoundingClientRect();
  if(rect){
    rect.x1=e.clientX-r.left; rect.y1=e.clientY-r.top;
    const b=$("selbox");
    b.style.left=Math.min(rect.x0,rect.x1)+"px"; b.style.top=Math.min(rect.y0,rect.y1)+"px";
    b.style.width=Math.abs(rect.x1-rect.x0)+"px"; b.style.height=Math.abs(rect.y1-rect.y0)+"px";
    return;
  }
  if(!drag)return;
  if(Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y)>3) drag.moved=true;
  PANX=drag.px+(e.clientX-drag.x); PANY=drag.py+(e.clientY-drag.y);
  recalc(); draw();});
document.addEventListener("keydown",e=>{if(e.key==="Escape"){SEL=[];paintSel();}});

// ---------- coverage readout, exact from the response array
function stats(){
  const resp=SS().resp, b=budget();
  let cov=0, unreach=0, reach=0, sum=0, arr=[];
  const set=new Set(picked); const {cov_indptr:ip,cov_indices:ix}=SS();
  for(let i=0;i<N;i++){
    const r=resp[i], p=POP[i];
    if(r<0){unreach+=p; continue;}
    reach+=p; sum+=r*p; arr.push([r,p]);
    let ok = r<=b;
    if(!ok&&set.size){for(let q=ip[i];q<ip[i+1];q++) if(set.has(ix[q])){ok=true;break;}}
    if(ok)cov+=p;
  }
  arr.sort((a,c)=>a[0]-c[0]);
  let acc=0,p50=0,p90=0;
  for(const [r,p] of arr){acc+=p;
    if(!p50&&acc>=reach*.5)p50=r; if(!p90&&acc>=reach*.9){p90=r;break;}}
  return {share:cov/TOTPOP,cov,unreach,mean:sum/reach,p50,p90};
}

// ---------- greedy MCLP, run live over the embedded sparse matrix
function greedy(k){
  const {cov_indptr:ip,cov_indices:ix}=SS(), resp=SS().resp, b=budget();
  const nC=S().candidates.length;
  const open=[]; for(let i=0;i<N;i++) if(!(resp[i]>=0&&resp[i]<=b)) open.push(i);
  const chosen=[], done=new Uint8Array(N);
  for(let step=0;step<k;step++){
    const gain=new Float64Array(nC);
    for(const i of open){ if(done[i])continue;
      for(let p=ip[i];p<ip[i+1];p++) gain[ix[p]]+=POP[i]; }
    let best=-1,bv=0;
    for(let j=0;j<nC;j++) if(gain[j]>bv&&!chosen.includes(j)){bv=gain[j];best=j;}
    if(best<0||bv<=0)break;
    chosen.push(best);
    for(const i of open){ if(done[i])continue;
      for(let p=ip[i];p<ip[i+1];p++) if(ix[p]===best){done[i]=1;break;} }
  }
  return chosen;
}

const IDCOL={confirmed:"#1F7A4D",corroborated:"#2E9E63",osm_source:"#2E9E63",
  assumed:"#8E9BA8",unresolved:"#D64545"};
const IDTXT={confirmed:"official TNFRS number matched",corroborated:"OSM feature nearby",
  osm_source:"OSM-matched from the start",assumed:"identity assumed, unchecked",
  unresolved:"not a municipal station"};

function idLegend(){
  const c={}; for(const s of D.stations) c[s.state]=(c[s.state]||0)+1;
  $("idLegend").innerHTML=Object.keys(IDCOL).filter(k=>c[k]).map(k=>
    `<span class="idrow"><i style="background:${IDCOL[k]}"></i>${IDTXT[k]}<span class="c">${c[k]}</span></span>`).join("");
}

// Cells indexed by the administrative areas a planner actually works in.
const BY_WARD={}, BY_ZONE={};
(()=>{
  const wm=D.base.ward_meta||{};
  for(let i=0;i<N;i++){
    const w=String(C.ward[i]); (BY_WARD[w]||(BY_WARD[w]=[])).push(i);
    const z=D.wards&&D.wards[C.ward[i]]?D.wards[C.ward[i]].zone:(wm[w]||{}).zone;
    if(z)(BY_ZONE[z]||(BY_ZONE[z]=[])).push(i);
  }
})();

function selectArea(kind,key){
  SELKIND=kind; SELKEY=key;
  SEL = kind==="ward" ? (BY_WARD[String(key)]||[])
      : kind==="zone" ? (BY_ZONE[key]||[])
      : [key];
  paintSel();
}

function buildPicker(){
  const wm=D.base.ward_meta||{};
  const zones=[...new Set(Object.values(wm).map(v=>v.zone))].sort();
  const wards=Object.keys(wm).map(k=>({id:+k,...wm[k]})).sort((a,b)=>a.no-b.no);
  $("areaPick").innerHTML='<option value="">Jump to a ward or zone…</option>'+
    '<optgroup label="Zones">'+zones.map(z=>
      `<option value="zone:${z}">${z.replace(/_/g," ")}</option>`).join("")+'</optgroup>'+
    '<optgroup label="Wards">'+wards.map(w=>
      `<option value="ward:${w.id}">Ward ${w.no} · ${w.zone.replace(/_/g," ")}</option>`).join("")+
    '</optgroup>';
}

// ---------- who responds here
// The map knows the best response time everywhere; a min() cannot say WHO
// provides it. top_who / top_s carry the three fastest stations per cell, so a
// selection can be answered the way a dispatcher would ask it.
// A linear scan over 3,838 cells ran on EVERY mousemove, rebuilding the tooltip
// each time -- enough to make the whole page feel stuck. Coarse spatial grid
// instead, rebuilt only when the view actually changes.
let GRID=null, GRIDCELL=48;
function buildGrid(){
  GRID=new Map();
  for(let i=0;i<N;i++){
    const k=((PX[i]/GRIDCELL)|0)+","+((PY[i]/GRIDCELL)|0);
    (GRID.get(k)||GRID.set(k,[]).get(k)).push(i);
  }
}
function nearestCell(mx,my){
  if(!GRID)buildGrid();
  const gx=(mx/GRIDCELL)|0, gy=(my/GRIDCELL)|0;
  let best=-1,bd=1e18;
  for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
    const b=GRID.get((gx+dx)+","+(gy+dy)); if(!b)continue;
    for(const i of b){const d=(PX[i]-mx)**2+(PY[i]-my)**2; if(d<bd){bd=d;best=i;}}
  }
  return bd<=Math.max(400,900/(Z*Z))?best:-1;
}

// Candidate sites in screen space. Same projection as paintSites uses, so what
// the pointer hits is what the eye sees.
function nearestCandidate(mx,my){
  const cand=S().candidates; let best=-1,bd=1e18;
  for(let j=0;j<cand.length;j++){
    const d=(px(cand[j].lon)-mx)**2+(py(cand[j].lat)-my)**2;
    if(d<bd){bd=d;best=j;}
  }
  return bd<=Math.max(900,2500/(Z*Z))?best:-1;
}

function selectionStats(){
  const sd=SS(), K=sd.topk||3, resp=sd.resp, b=budget();
  let pop=0, cov=0, unreach=0, best={};
  for(const i of SEL){
    const p=POP[i]; pop+=p;
    if(resp[i]<0){unreach+=p; continue;}
    if(resp[i]<=b)cov+=p;
    const who=sd.top_who[i*K], t=sd.top_s[i*K];
    if(who>=0){const e=best[who]||(best[who]={pop:0,wt:0}); e.pop+=p; e.wt+=t*p;}
  }
  const rows=Object.entries(best).map(([w,e])=>
    ({st:+w,pop:e.pop,mean:e.wt/Math.max(e.pop,1)})).sort((a,c)=>c.pop-a.pop);
  return {pop,cov,unreach,rows};
}

function paintSel(){
  const P=$("selPanel");
  if(!SEL.length){P.style.display="none"; draw(); return;}
  P.style.display="block";
  const s=selectionStats(), sd=SS(), K=sd.topk||3;
  const wm=D.base.ward_meta||{};
  $("selTitle").textContent =
    SELKIND==="ward" ? `Ward ${(wm[String(SELKEY)]||{}).no ?? SELKEY} · ${((wm[String(SELKEY)]||{}).zone||"").replace(/_/g," ")}`
  : SELKIND==="zone" ? `${String(SELKEY).replace(/_/g," ")} zone`
  : `Ward ${C.ward[SEL[0]]} · one cell`;
  $("selSum").innerHTML=`${Math.round(s.pop).toLocaleString()} residents · `+
    `<b style="color:var(--${s.cov/Math.max(s.pop,1)>=.6?"green":"amber"})">`+
    `${(100*s.cov/Math.max(s.pop,1)).toFixed(0)}%</b> reached within ${thrMin} min`+
    (s.unreach>0?` · <b style="color:var(--red)">${Math.round(s.unreach).toLocaleString()} with no route</b>`:"");

  if(SELKIND==="cell"&&SEL.length===1){
    // one cell: the actual ranked queue for that spot
    const i=SEL[0];
    $("respBody").innerHTML=Array.from({length:K},(_,r)=>{
      const w=sd.top_who[i*K+r], t=sd.top_s[i*K+r];
      if(w<0)return "";
      const st=D.stations[w];
      return `<tr><td><span class="rk" style="background:${r?"var(--muted)":IDCOL[st.state]||"var(--navy)"}">${r+1}</span>${st.name}</td>`+
        `<td class="t">—</td><td class="t">${(t/60).toFixed(1)} min</td></tr>`;}).join("");
    $("selHint").innerHTML=`Ranked by travel time on the ${SC_LABEL[scen].toLowerCase()} network, `+
      `including the ${S().t_alarm_s+S().t_turnout_s}s alarm and turnout offsets. `+
      `Station colour marks how well its position is verified.`;
  } else {
    $("respBody").innerHTML=s.rows.slice(0,6).map((r,n)=>{
      const st=D.stations[r.st];
      return `<tr><td><span class="rk" style="background:${IDCOL[st.state]||"var(--navy)"}">${n+1}</span>${st.name}</td>`+
        `<td class="t">${(100*r.pop/Math.max(s.pop,1)).toFixed(0)}%</td>`+
        `<td class="t">${(r.mean/60).toFixed(1)} min</td></tr>`;}).join("")
      ||`<tr><td colspan="3" style="color:var(--red)">No station reaches any of this area.</td></tr>`;
    $("selHint").innerHTML=`Each station is credited with the residents for whom it is the `+
      `FASTEST responder, and the time shown is its population-weighted mean over those. `+
      `Switch scope to Cell for a single hex and its full queue.`;
  }
  draw();
}

// ---------- render side panels
function paint(){
  const s=stats(), b=budget();
  $("covPct").textContent=(s.share*100).toFixed(1)+"%";
  $("covPct").className="big "+(s.share>=.6?"g":"a");
  $("covCap").textContent=`${s.cov.toLocaleString()} of ${TOTPOP.toLocaleString()} residents `+
    `within ${thrMin} min · ${SC_LABEL[scen]}`;
  $("stats").innerHTML=[
    ["Travel budget",`${b} s`],["Mean travel",`${(s.mean/60).toFixed(1)} min`],
    ["Median (P50)",`${(s.p50/60).toFixed(1)} min`],["P90",`${(s.p90/60).toFixed(1)} min`],
    ["Unreachable",`${s.unreach.toLocaleString()}`+(s.unreach?" ⚠":"")],
  ].map(([k,v])=>`<span class="k">${k}</span><span class="v${
    k==="Unreachable"&&s.unreach?" warn":""}">${v}</span>`).join("");
  $("budgetNote").textContent=`travel budget ${b}s = ${thrMin} min − ${S().t_alarm_s}s alarm − ${S().t_turnout_s}s turnout`;
  $("legend").innerHTML=BANDS.map(([t,v],i)=>
    `<span class="lg"><i class="sw" style="background:${cssv(v)}"></i>${
      i===0?`within ${thrMin} min`:t==="+2 min"?`+ up to 2 min`:t==="+2-7 min"?`+ 2–7 min`:`beyond`}</span>`).join("")
    +`<span class="lg"><i class="sw" style="background:${cssv("--nodata")}"></i>no route at all</span>`;
  $("nSites").textContent=S().candidates.length+" feasible";
  bracket(s.share); wardTable(); compare(); if(SEL.length)paintSel();
  const sd=SS();
  $("caveat").innerHTML=`<b>${sd.report_only?"Reported, not optimised against":
    "Design basis, weight "+sd.weight.toFixed(2)}.</b> ${
    D.meta.basis_line}. The optimiser runs at the ${S().standard} standard, not at the
    slider — the slider re-reads coverage from exact per-cell response times.`;
}

// E-11g: the tight interval assumes all 29 Maps POIs name the right station.
// Fifteen are unchecked, so the wide one is shown alongside rather than buried.
function bracket(share){
  const u=S().uncertainty||{}, a=u.assumed_correct, w=u.if_unconfirmed_wrong;
  if(!a){$("band").textContent="";$("errbar").innerHTML="";return;}
  const pct=share*100, half=x=>x/2;
  const lo=pct-half(w?w.spread_points:a.spread_points), hi=pct+half(w?w.spread_points:a.spread_points);
  const span=Math.max(hi-lo,1e-6), pos=v=>((v-lo)/span*100).toFixed(1)+"%";
  const tl=pct-half(a.spread_points), th=pct+half(a.spread_points);
  $("errbar").innerHTML=
    `<i class="wideb" style="left:0;right:0"></i>`+
    `<i class="tight" style="left:${pos(tl)};right:${(100-parseFloat(pos(th)))}%"></i>`+
    `<i class="pt" style="left:${pos(pct)}"></i>`;
  $("band").innerHTML=
    `<span class="rng">±${a.spread_points.toFixed(1)} pts</span> if all 29 station POIs `+
    `name the right station — <span class="rng wide">±${w?w.spread_points.toFixed(1):"?"} pts</span> `+
    `if the 15 unconfirmed ones are no better than the geocode they replaced. `+
    `Both from ${a.draws} draws (E-11g).`;
}

function wardTable(){
  const resp=SS().resp, b=budget(), agg={};
  for(let i=0;i<N;i++){
    const w=C.ward[i], p=POP[i]; if(!p)continue;
    const a=agg[w]||(agg[w]={p:0,c:0});
    a.p+=p; if(resp[i]>=0&&resp[i]<=b)a.c+=p;
  }
  const rows=Object.entries(agg).map(([w,a])=>[+w,a.c/a.p,a.p])
    .sort((x,y)=>x[1]-y[1]).slice(0,8);
  $("wardBody").innerHTML=rows.map(([w,sh,p])=>{
    const meta=(D.wards||{})[w]||{};
    return `<tr data-ward="${w}" style="cursor:pointer"><td class="n">${meta.no??w}</td>`+
      `<td>${(meta.zone||"—").replace(/^Zone \d+\s*/,"").replace(/_/g," ")}</td>`+
      `<td style="text-align:right" class="${sh<=0.0001?"bad":""}">${(sh*100).toFixed(0)}%</td></tr>`;}).join("");
  document.querySelectorAll("[data-ward]").forEach(tr=>tr.onclick=()=>{
    SCOPE="ward";
    document.querySelectorAll("[data-scope]").forEach(o=>
      o.setAttribute("aria-pressed",o.dataset.scope==="ward"));
    $("areaPick").value="ward:"+tr.dataset.ward;
    selectArea("ward", +tr.dataset.ward);});
}

function compare(){
  const ex=(S().exact||{})[String(kWant)];
  if(!ex){$("cmp").innerHTML="";return;}
  const mine=picked.length?stats().share:null;
  $("cmp").innerHTML=
    `<span>Exact MCLP, k=${kWant}</span><span class="v">${(ex.share*100).toFixed(1)}%</span>`+
    `<span>Pipeline greedy</span><span class="v">${(ex.greedy*100).toFixed(1)}%</span>`+
    (mine!==null?`<span>This run (in-browser greedy)</span><span class="v">${(mine*100).toFixed(1)}%</span>`:"")+
    `<span style="color:var(--muted);grid-column:1/-1;margin-top:3px">`+
    `Exact is proven optimal${ex.proven?"":" — NOT proven at this k"}; it solves at the `+
    `${S().standard} standard on the dry network, so it will not track the slider.</span>`;
}

function paintSites(){
  const cand=S().candidates;
  $("siteList").innerHTML=picked.map((j,n)=>{const c=cand[j];
    return `<div class="site"><span class="n">${n+1}</span>
      <span>Candidate ${j}</span>
      <span class="c">${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}</span></div>`;}).join("");
  $("clear").style.display=picked.length?"block":"none";
}

// ---------- scenario buttons
function buildScen(){
  $("scenOpts").innerHTML=Object.keys(S().scenarios).map(id=>{
    const d=S().scenarios[id];
    return `<button class="opt${d.report_only?" report":""}" data-scen="${id}"
      aria-pressed="${id===scen}">${SC_LABEL[id]}
      <small>${d.report_only?"report":"w "+d.weight.toFixed(2)}</small></button>`;}).join("");
  document.querySelectorAll("[data-scen]").forEach(el=>el.onclick=()=>{
    scen=el.dataset.scen; picked=[];
    document.querySelectorAll("[data-scen]").forEach(o=>
      o.setAttribute("aria-pressed",o.dataset.scen===scen));
    paintSites(); draw(); paint();});
}

// ---------- events
$("svcSeg").onclick=e=>{const b=e.target.closest("[data-svc]"); if(!b)return;
  svc=b.dataset.svc; picked=[];
  document.querySelectorAll("[data-svc]").forEach(o=>
    o.setAttribute("aria-pressed",o.dataset.svc===svc));
  buildScen(); paintSites(); draw(); paint();};
$("thr").oninput=e=>{thrMin=+e.target.value; $("thrVal").textContent=thrMin;
  draw(); paint();};
$("k").oninput=e=>{kWant=+e.target.value; $("kVal").textContent=kWant; compare();};
$("opt").onclick=()=>{
  try{
    const t0=performance.now();
    picked=greedy(kWant);
    paintSites(); draw(); paint();
    const d=$("diag"); if(d)d.textContent=
      `optimise: ${picked.length} sites in ${(performance.now()-t0).toFixed(0)} ms`+
      ` (k=${kWant}, candidates ${S().candidates.length})`;
  }catch(err){const d=$("diag"); if(d)d.textContent="optimise failed: "+(err&&err.message||err);}
};
$("clear").onclick=()=>{picked=[]; paintSites(); draw(); paint();};
[["tgStations","st"],["tgSites","sites"],["tgBase","base"],
 ["tgZones","zones"],["tgFlood","flood"],["tgCov","cov"]].forEach(([id,key])=>{
  if(!$(id))return;
  $(id).onclick=e=>{layers[key]=!layers[key];
    e.currentTarget.setAttribute("aria-pressed",layers[key]); draw();};});
$("reset").onclick=()=>{Z=1;PANX=0;PANY=0;recalc();draw();};
$("selClear").onclick=()=>{SEL=[];SELKIND=null;$("areaPick").value="";paintSel();};
$("scopeSeg").onclick=e=>{const b=e.target.closest("[data-scope]"); if(!b)return;
  SCOPE=b.dataset.scope;
  document.querySelectorAll("[data-scope]").forEach(o=>
    o.setAttribute("aria-pressed",o.dataset.scope===SCOPE));
  $("modeHint").innerHTML = SCOPE==="cell"
    ? "Click a single demand cell for its full responder queue."
    : `Click the map to select the ${SCOPE} under the pointer, or pick one below. `+
      "Emergency planning is done by ward and zone, so those are the units here.";
  if(SEL.length&&SELKIND&&SELKIND!==SCOPE&&SCOPE!=="cell"){
    const i=SEL[0], wm=D.base.ward_meta||{};
    SCOPE==="ward"?selectArea("ward",C.ward[i]):selectArea("zone",(wm[String(C.ward[i])]||{}).zone);
  }};
$("areaPick").onchange=e=>{
  const v=e.target.value; if(!v){SEL=[];SELKIND=null;paintSel();return;}
  const [kind,key]=v.split(":");
  SCOPE=kind;
  document.querySelectorAll("[data-scope]").forEach(o=>
    o.setAttribute("aria-pressed",o.dataset.scope===kind));
  selectArea(kind, kind==="ward"?+key:key);};
$("copy").onclick=async()=>{
  const s=stats();
  const payload={generated:new Date().toISOString(),
    PROVISIONAL:!!D.meta.PROVISIONAL,
    publication_basis:D.meta.publication_basis,
    basis:D.meta.basis_line, waiver:D.meta.waiver||null,
    service:svc,scenario:scen,
    threshold_min:thrMin,travel_budget_s:budget(),coverage_share:+s.share.toFixed(4),
    population_covered:Math.round(s.cov),unreachable_population:Math.round(s.unreach),
    mean_travel_s:Math.round(s.mean),p90_travel_s:Math.round(s.p90),
    proposed_sites:picked.map((j,n)=>({rank:n+1,candidate:j,...S().candidates[j]})),
    calibration:{trip_overhead_s:D.meta.trip_overhead_s,
      junction_delay_scale:D.meta.junction_delay_scale},
    stations_signature:D.meta.stations_signature};
  try{await navigator.clipboard.writeText(JSON.stringify(payload,null,2));
    $("copyMsg").textContent="Copied — includes the publication basis";}
  catch(e){$("copyMsg").textContent="Clipboard blocked";}
  setTimeout(()=>$("copyMsg").textContent="",2600);};

// Manual placement mode. Off by default: the map's primary interaction is
// selecting an area, and silently changing what a click does is worse than an
// explicit mode.
$("place").onclick=()=>{
  PLACE=!PLACE;
  $("place").setAttribute("aria-pressed",String(PLACE));
  $("place").textContent=PLACE?"Manual placement: ON":"Place a site by hand";
  cvEl().style.cursor=PLACE?"copy":"crosshair";
  $("modeHint").textContent=PLACE
    ? "Click a candidate site to add or remove it. Every statistic recomputes live."
    : "Click the map to select the ward under the pointer.";
};

// Export the brief the deck promises. A report that only reaches a clipboard is
// not an export -- a planner needs a file they can attach.
$("export").onclick=()=>{
  const s=stats(), cand=S().candidates, u=S().uncertainty||{};
  const rows=[
    "# Chennai emergency response — coverage brief",
    "# BASIS: "+D.meta.basis_line,
    "# generated "+new Date().toISOString(),
    "# stations_signature "+D.meta.stations_signature,
    "",
    "## Settings",
    "service,"+svc, "scenario,"+scen, "threshold_min,"+thrMin,
    "travel_budget_s,"+budget(),
    "",
    "## Coverage",
    "coverage_share,"+(100*s.share).toFixed(2)+"%",
    "population_covered,"+Math.round(s.cov),
    "unreachable_population,"+Math.round(s.unreach),
    "mean_travel_s,"+Math.round(s.mean),
    "p90_travel_s,"+Math.round(s.p90),
    "",
    "## Uncertainty (E-11g) — the interval, not just the point estimate",
    "interval_if_unconfirmed_pois_correct_points,"+(u.assumed_correct||{}).spread_points,
    "interval_if_unconfirmed_pois_wrong_points,"+(u.if_unconfirmed_wrong||{}).spread_points,
    "",
    "## Proposed sites ("+(PLACE?"includes manual placements":"as selected")+")",
    "rank,candidate_id,lat,lon",
    ...picked.map((j,n)=>[n+1,j,cand[j].lat.toFixed(6),cand[j].lon.toFixed(6)].join(",")),
    "",
    "## Stated assumptions",
    "trip_overhead_s,"+D.meta.trip_overhead_s,
    "junction_delay_scale,"+D.meta.junction_delay_scale,
    "note,\"Coverage is population-weighted on the real directed road network. "+
      "EMS is modelled from fire-station bases; no 108 standby-point inventory exists. "+
      "Site lists are not identified at current positional accuracy (ADR-005).\"",
  ].join("\n");

  const blob=new Blob([rows],{type:"text/csv"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download=`chennai-ers-${svc}-${scen}-${thrMin}min.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  $("copyMsg").textContent="Exported "+a.download;
  setTimeout(()=>$("copyMsg").textContent="",2600);
};

// hover readout
const cv=$("cv"), tip=$("tip");
let hoverPend=false, lastHover=-2;
cv.onmousemove=e=>{
  if(hoverPend)return; hoverPend=true;
  requestAnimationFrame(()=>{hoverPend=false;});
  const r=cv.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  let best=-1,bd=1e9;
  for(let i=0;i<N;i++){const d=(PX[i]-mx)**2+(PY[i]-my)**2; if(d<bd){bd=d;best=i;}}
  if(bd>Math.max(400,900/(Z*Z))){tip.classList.remove("on");return;}
  if(best===lastHover){tip.style.left=Math.min(mx+14,r.width-232)+"px";
    tip.style.top=(my+14)+"px"; return;}
  lastHover=best;
  const rs=SS().resp[best];
  tip.innerHTML=`<b>Ward ${C.ward[best]}</b> · ${POP[best].toLocaleString()} residents<br>`+
    (rs<0?"<b>No route from any station</b>":
      `${(rs/60).toFixed(1)} min travel · ${(rs+S().t_alarm_s+S().t_turnout_s)>thrMin*60?
        "outside":"within"} ${thrMin} min`);
  tip.style.left=Math.min(mx+14,r.width-232)+"px"; tip.style.top=(my+14)+"px";
  tip.classList.add("on");};
cv.onmouseleave=()=>tip.classList.remove("on");
window.addEventListener("resize",fit);
$("stamp").textContent=(D.meta.publication_basis==="waived" ? "Under waiver · "
  : D.meta.publication_basis==="surveyed" ? "Surveyed · " : "Provisional · ")
  +D.meta.stations_signature.slice(0,8);
$("attrib").textContent=D.raster.attribution;

// Does a click even reach this document? Capture phase on window, so nothing
// downstream can swallow it. If this counter never moves, the problem is not in
// any handler -- it is that the frame is not delivering pointer events at all.
let CLICKS=0;
const diag=()=>{const d=$("diag"); if(!d)return;
  d.textContent=`clicks ${CLICKS} · wards ${Object.keys(BY_WARD).length}`+
    ` · cov ${(SS().cov_indptr||[]).length} · k ${kWant} · picked ${picked.length}`+
    ` · sel ${SEL.length}`;};
window.addEventListener("click",()=>{CLICKS++;diag();},true);

// Paint the whole interface FIRST, then let the basemap arrive. Blocking first
// paint on two JPEG decodes leaves the page looking broken for as long as they
// take, and everything except the street map is ready before them.
// The console is sandboxed in a cross-origin frame, so a thrown error is
// invisible from outside. Surface it on the page itself rather than leaving a
// blank screen that looks like a slow load.
try{
  idLegend(); buildPicker(); buildScen(); fit(); paint(); paintSites();
  const _b=$("boot"); if(_b)_b.remove();
  loadRaster(()=>draw());
  diag();
}catch(err){
  const b=$("boot");
  if(b)b.innerHTML='<div style="max-width:620px;text-align:left">'+
    '<b>Console failed to start</b>'+
    '<pre style="white-space:pre-wrap;font-size:11px;color:var(--red);'+
    'font-family:ui-monospace,monospace">'+(err&&err.stack||err)+'</pre></div>';
  throw err;
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",draw);
