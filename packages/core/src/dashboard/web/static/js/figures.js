import { $, storage, setText } from './shared.js';

export class RunFigureViewer {
  constructor(host, runId) {
    this.host=host; this.runId=runId; this.key=`figures.${runId}`;
    const saved=storage.get(this.key,{});
    this.state={selected:saved?.selected||'',zoom:saved?.zoom&&typeof saved.zoom==='object'?saved.zoom:{}};
    host.innerHTML='<div class="figure-tabs" role="tablist" aria-label="Run figures"></div><section class="figure-panel" role="tabpanel"><div class="toolbar figure-controls"><button type="button" class="secondary figure-zoom-out">Zoom out</button><output class="figure-zoom-level" aria-live="polite">100%</output><button type="button" class="secondary figure-zoom-in">Zoom in</button><button type="button" class="secondary figure-zoom-reset">Fit / reset</button><a class="button secondary figure-original" target="_blank" rel="noopener">Open original</a></div><figure><figcaption class="figure-caption"></figcaption><p class="figure-source hint"></p><div class="figure-viewport" tabindex="0" aria-label="Figure viewport; scroll to pan when zoomed"><div class="figure-canvas"></div></div><p class="figure-help hint">Zoom to enlarge; scroll to pan. Interactive 3D figures also support dragging to rotate.</p><p class="figure-error notice" role="status" hidden></p></figure></section><p class="figure-empty" hidden>No analysis graphs yet. Use the analysis buttons to generate results.</p>';
    this.tabs=$('.figure-tabs',host);this.panel=$('.figure-panel',host);
    this.panel.id=`figure-panel-${runId}`;
    this.viewport=$('.figure-viewport',host);this.canvas=$('.figure-canvas',host);
    $('.figure-zoom-in',host).onclick=()=>this.setZoom(this.zoom*1.25);
    $('.figure-zoom-out',host).onclick=()=>this.setZoom(this.zoom/1.25);
    $('.figure-zoom-reset',host).onclick=()=>{this.setZoom(1);this.viewport.scrollTo(0,0);};
    this.observer=new ResizeObserver(()=>this.layout());this.observer.observe(this.viewport);
  }
  destroy(){this.observer.disconnect();}
  update(artifacts) {
    const signature=JSON.stringify(artifacts.map(a=>[a.path,a.bytes,a.modified_at]));
    if(signature===this.signature)return;
    this.signature=signature;this.artifacts=artifacts;
    this.tabs.replaceChildren();
    this.panel.hidden=!artifacts.length;this.tabs.hidden=!artifacts.length;$('.figure-empty',this.host).hidden=!!artifacts.length;
    if(!artifacts.length){this.canvas.replaceChildren();this.active='';return;}
    const labels=artifacts.map(a=>a.path.split('/').at(-1).replace(/\.(svg|png|html)$/i,'').replace(/[_-]+/g,' '));
    const counts=new Map();labels.forEach(label=>counts.set(label,(counts.get(label)||0)+1));
    this.labels=labels;
    this.metadata=artifacts.map(a=>a.metadata || null);
    artifacts.forEach((artifact,index)=>{
      const tab=document.createElement('button');tab.type='button';tab.role='tab';tab.id=`figure-tab-${this.runId}-${index}`;
      tab.setAttribute('aria-controls',this.panel.id);tab.textContent=labels[index]+(counts.get(labels[index])>1?` · ${index+1}`:'');tab.title=artifact.path;
      tab.onclick=()=>this.select(artifact.path);
      tab.onkeydown=event=>{
        let next;
        if(event.key==='ArrowRight')next=(index+1)%artifacts.length;
        if(event.key==='ArrowLeft')next=(index+artifacts.length-1)%artifacts.length;
        if(event.key==='Home')next=0;
        if(event.key==='End')next=artifacts.length-1;
        if(next!==undefined){event.preventDefault();this.select(artifacts[next].path);this.tabs.children[next].focus();}
      };
      this.tabs.append(tab);
    });
    this.select(artifacts.some(a=>a.path===this.state.selected)?this.state.selected:artifacts[0].path);
  }
  select(path) {
    const index=this.artifacts.findIndex(a=>a.path===path);if(index<0)return;
    Array.from(this.tabs.children).forEach((tab,i)=>{tab.setAttribute('aria-selected',String(i===index));tab.tabIndex=i===index?0:-1;});
    this.panel.setAttribute('aria-labelledby',this.tabs.children[index].id);
    this.state.selected=path;storage.set(this.key,this.state);
    if(this.active===path)return; // Preserve an iframe's camera and image scroll on refresh.
    this.active=path;
    const saved=Number(this.state.zoom[path]);this.zoom=Number.isFinite(saved)&&saved>=.25&&saved<=4?saved:1;
    const caption=this.figureCaption(this.labels[index],path,this.metadata?.[index]);$('.figure-caption',this.host).innerHTML=caption.title+(caption.help?`<small>${caption.help}</small>`:'');setText($('.figure-source',this.host),path);
    this.panel.classList.toggle('score-figure', /score|matrix/i.test(this.labels[index]));
    const url=`/api/jobs/${this.runId}/artifacts/${path.split('/').map(encodeURIComponent).join('/')}?inline=1`;
    $('.figure-original',this.host).href=url;$('.figure-error',this.host).hidden=true;
    this.interactive=path.endsWith('.html');this.media=document.createElement(this.interactive?'iframe':'img');
    this.media.className='figure-media';this.media.src=url;
    if(this.interactive){this.media.title=this.labels[index];this.media.setAttribute('sandbox','allow-scripts');}
    else {this.media.alt=this.labels[index];this.media.onload=()=>this.layout();this.media.onerror=()=>{setText($('.figure-error',this.host),'Could not load this figure. Open the original to inspect the artifact.');$('.figure-error',this.host).hidden=false;};}
    this.canvas.replaceChildren(this.media);this.viewport.scrollTo(0,0);this.layout();
  }
  figureCaption(label,path,metadata=null) {
    const lower=(label+' '+path).toLowerCase();
    if(metadata && !metadata.legacy) {
      const help=[metadata.units_or_direction, metadata.ideal_result].filter(Boolean).join(' · ');
      return {title:metadata.title || label,help};
    }
    const legacy='Legacy caption · ';
    if(lower.includes('stratified')&&lower.includes('distance')) return {title:legacy+'Stratified physical distance matrix',help:'This matrix is recalculated from the expanded-ring AA reference using Wasserstein distance in nm. Lower values are better. Virtual-site pairs are masked and reported separately because they are derived sites, not independent bonded distances.'};
    if(lower.includes('score')||lower.includes('matrix')) return {title:legacy+'Score matrix',help:'Lower mismatch is better: 0 means identical distributions; values approaching 1 indicate poor overlap.'};
    if(lower.includes('interaction')||lower.includes('bond')||lower.includes('angle')||lower.includes('dihedral')) return {title:legacy+'Interaction distributions',help:'Agreement of peak positions, widths, and populations is desired; any reported mismatch score is lower-is-better.'};
    if(lower.includes('distance')) return {title:legacy+'Distance distributions',help:'Agreement of distributions is desired. Deliberate 15% ring expansion can create a systematic raw-AA difference.'};
    if(lower.includes('sasa')) return {title:legacy+'SASA over time',help:'AA and CG means and variability should agree; SASA is not universally better when larger or smaller.'};
    if(lower.includes('surface')) return {title:legacy+'AA/CG surface comparison',help:'Similar aligned envelopes are desired; this is a snapshot or cached surface diagnostic.'};
    return {title:legacy+label};
  }
  setZoom(value){this.zoom=Math.min(4,Math.max(.25,value));this.state.zoom[this.active]=this.zoom;storage.set(this.key,this.state);this.layout();}
  layout(){
    if(!this.media)return;
    const width=this.viewport.clientWidth;if(!width)return;
    const height=this.interactive?780:(this.media.naturalWidth?width*this.media.naturalHeight/this.media.naturalWidth:400);
    this.media.style.width=`${width}px`;this.media.style.height=`${height}px`;this.media.style.transform=`scale(${this.zoom})`;
    this.canvas.style.width=`${width*this.zoom}px`;this.canvas.style.height=`${height*this.zoom}px`;
    setText($('.figure-zoom-level',this.host),`${Math.round(this.zoom*100)}%`);
    $('.figure-zoom-out',this.host).disabled=this.zoom<=.25;$('.figure-zoom-in',this.host).disabled=this.zoom>=4;
  }
}
