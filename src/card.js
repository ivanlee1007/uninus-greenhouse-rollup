import { coverServiceForAction, GRID_OPTIONS, normalizeConfig, resolveFaceState, resolveSubtitle, resolveThemeTokens, selectLayout } from './model.js';

const escapeHtml=(value)=>String(value??'').replace(/[&<>"']/g,(char)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const rollupName=(value)=>{const name=String(value??'').trim();return name.endsWith('捲揚')||/\broll[ -]?up\b/i.test(name)?name:`${name}捲揚`};

export class UninusGreenhouseRollupCard extends HTMLElement {

  static styles = `
    :host{display:block;min-width:0;container-type:inline-size}
    .rollup-card{display:block;position:relative;width:100%;min-height:190px;box-sizing:border-box;overflow:hidden;padding:clamp(12px,2.5cqw,20px);border-radius:22px;background:var(--rollup-bg);color:var(--rollup-text);border:1px solid color-mix(in srgb,var(--rollup-text) 10%,transparent);box-shadow:0 14px 38px rgba(0,0,0,.24)}
    .header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin:0 2px 14px;text-align:left}.header h2{margin:0;font-size:clamp(16px,3.8cqw,21px);line-height:1.2;letter-spacing:.035em}.header p{margin:5px 0 0;color:var(--rollup-muted);font-size:clamp(9px,2cqw,11px);overflow-wrap:anywhere}.system{display:inline-flex;align-items:center;gap:6px;padding:6px 9px;border:1px solid color-mix(in srgb,var(--rollup-moving) 28%,transparent);border-radius:999px;color:var(--rollup-moving);font-size:8px;font-weight:800;white-space:nowrap}.system i{width:6px;height:6px;border-radius:50%;background:#64d9a0;box-shadow:0 0 8px #64d9a0}
    .faces{display:grid;gap:clamp(8px,1.8cqw,13px);min-width:0}.columns-4 .faces{grid-template-columns:repeat(4,minmax(0,1fr))}.columns-3 .faces{grid-template-columns:repeat(3,minmax(0,1fr))}.columns-2 .faces{grid-template-columns:repeat(2,minmax(0,1fr))}.columns-1 .faces{grid-template-columns:minmax(0,1fr)}
    .face{min-width:0;padding:clamp(8px,1.8cqw,13px);border-radius:17px;background:var(--rollup-surface);border:1px solid color-mix(in srgb,var(--rollup-text) 9%,transparent);box-shadow:inset 0 1px color-mix(in srgb,var(--rollup-text) 5%,transparent),0 7px 18px rgba(0,0,0,.17)}
    .face-head{display:grid;grid-template-columns:28px minmax(0,1fr) auto;align-items:center;gap:7px;margin-bottom:9px}.compass{display:grid;place-items:center;width:28px;height:28px;border-radius:9px;background:color-mix(in srgb,var(--face-accent) 13%,transparent);border:1px solid color-mix(in srgb,var(--face-accent) 25%,transparent);color:var(--face-accent);font-size:10px;font-weight:900}.name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:clamp(10px,2.5cqw,13px);font-weight:800}.motion{display:inline-flex;align-items:center;gap:5px;padding:5px 7px;border-radius:999px;background:color-mix(in srgb,var(--status-color) 13%,transparent);border:1px solid color-mix(in srgb,var(--status-color) 32%,transparent);color:var(--status-color);font-size:clamp(8px,1.8cqw,10px);font-weight:800;white-space:nowrap}.motion i{width:6px;height:6px;border-radius:50%;background:var(--status-color)}.moving .motion i{box-shadow:0 0 9px var(--status-color);animation:pulse 1s ease-in-out infinite}
    .scene{position:relative;height:clamp(96px,24cqw,132px);overflow:hidden;border-radius:11px;background:var(--rollup-frame);border:1px solid color-mix(in srgb,var(--rollup-text) 15%,transparent);box-shadow:inset 0 0 0 3px rgba(0,0,0,.12),inset 0 0 22px rgba(0,0,0,.22)}.opening{position:absolute;left:4px;right:4px;bottom:4px;height:max(0px,calc(var(--open) - 4px));overflow:hidden;background:linear-gradient(145deg,color-mix(in srgb,var(--open-color) 36%,white),var(--open-color));box-shadow:inset 0 0 23px rgba(255,255,220,.15),0 0 20px color-mix(in srgb,var(--open-color) 35%,transparent);transition:height .65s cubic-bezier(.2,.8,.2,1),background .65s}.curtain{position:absolute;left:4px;right:4px;top:4px;height:max(0px,calc(100% - var(--open) - 4px));overflow:hidden;background:linear-gradient(90deg,color-mix(in srgb,var(--closed-color) 72%,black),var(--closed-color) 28%,color-mix(in srgb,var(--closed-color) 82%,black) 52%,color-mix(in srgb,var(--closed-color) 88%,white) 74%,color-mix(in srgb,var(--closed-color) 68%,black));border-bottom:1px solid rgba(255,255,255,.14);transition:height .65s cubic-bezier(.2,.8,.2,1)}.curtain b{position:absolute;top:0;bottom:0;width:1px;background:rgba(255,255,255,.07)}.curtain b:first-of-type{left:34%}.curtain b:last-of-type{left:67%}.shine{position:absolute;inset:0 auto 0 -35%;width:30%;transform:skewX(-16deg);background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent)}
    .roller{position:absolute;z-index:5;left:1px;right:1px;bottom:clamp(4px,calc(var(--open) - 5px),calc(100% - 14px));height:11px;display:flex;align-items:center;transition:bottom .65s cubic-bezier(.2,.8,.2,1)}.roller span{flex:1;height:9px;border-radius:999px;border:1px solid rgba(255,240,170,.46);background:repeating-linear-gradient(90deg,#705714 0,var(--face-accent) 5px,#aa7b13 10px,#fff0a0 15px);box-shadow:0 2px 6px rgba(0,0,0,.5),0 0 10px color-mix(in srgb,var(--face-accent) 30%,transparent)}.roller i{width:7px;height:11px;border-radius:3px;background:#adb7ba}.moving.animated .roller span{animation:roll .43s linear infinite}.moving.animated .shine{animation:sweep 1.35s ease-in-out infinite}
    .rollup-air{position:absolute;left:-45%;width:44%;height:2px;border-radius:999px;opacity:0;background:linear-gradient(90deg,transparent,rgba(225,252,255,.95),transparent)}.rollup-air:nth-child(1){bottom:25%}.rollup-air:nth-child(2){bottom:50%;animation-delay:.18s!important}.rollup-air:nth-child(3){bottom:75%;animation-delay:.36s!important}.moving.animated .rollup-air{animation:airflow 1.45s ease-in-out infinite}.ray{position:absolute;top:-20%;width:12px;height:145%;opacity:.23;transform:rotate(20deg);background:linear-gradient(transparent,rgba(255,255,230,.9),transparent)}.ray.one{left:25%}.ray.two{left:68%}
    .scale{position:absolute;z-index:6;right:5px;color:rgba(255,255,255,.52);font-size:7px;text-shadow:0 1px 2px #000}.scale.top{top:6px}.scale.mid{top:calc(50% - 4px)}.scale.bottom{bottom:5px}.percent{position:absolute;z-index:7;left:7px;bottom:6px;padding:3px 5px;border-radius:6px;background:rgba(0,0,0,.4);color:#fff;font-size:8px;font-weight:900}.unknown .scene::after{content:'位置未知';position:absolute;z-index:6;inset:0;display:grid;place-items:center;background:repeating-linear-gradient(135deg,rgba(255,255,255,.035) 0 8px,rgba(0,0,0,.055) 8px 16px);color:rgba(255,255,255,.72);font-size:9px;font-weight:800;letter-spacing:.08em}
    .foot{display:flex;align-items:end;justify-content:space-between;gap:7px;margin-top:8px;text-align:left}.more-info{all:unset;box-sizing:border-box;display:flex;align-items:end;justify-content:space-between;gap:7px;width:100%;border-radius:6px;cursor:pointer}.more-info:focus-visible{outline:2px solid var(--face-accent);outline-offset:2px}.copy{display:grid;min-width:0;gap:2px}.copy strong,.copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.copy strong{font-size:clamp(9px,2.2cqw,11px)}.copy small{color:var(--rollup-muted);font-size:clamp(8px,1.7cqw,9px)}.foot em{color:var(--face-accent);font-size:clamp(10px,2.5cqw,13px);font-style:normal;font-weight:900}
    .controls{display:grid;grid-template-columns:repeat(var(--control-count,3),minmax(0,1fr));gap:5px;margin-top:8px}.controls button{min-width:0;padding:6px 4px;border:1px solid color-mix(in srgb,var(--face-accent) 30%,transparent);border-radius:8px;background:color-mix(in srgb,var(--face-accent) 11%,transparent);color:var(--rollup-text);font:inherit;font-size:9px;font-weight:800;cursor:pointer}.controls button:hover{background:color-mix(in srgb,var(--face-accent) 22%,transparent)}.controls button:focus-visible{outline:2px solid var(--face-accent);outline-offset:1px}.controls button:disabled{cursor:not-allowed;opacity:.38}.controls .stop{border-color:color-mix(in srgb,var(--rollup-moving) 35%,transparent)}
    .columns-3 .face,.columns-4 .face{padding:clamp(6px,1cqw,9px)}.columns-3 .face-head,.columns-4 .face-head{grid-template-columns:22px minmax(0,1fr);grid-template-areas:'compass name' 'motion motion';gap:4px;margin-bottom:6px}.columns-3 .compass,.columns-4 .compass{grid-area:compass;width:22px;height:22px}.columns-3 .name,.columns-4 .name{grid-area:name}.columns-3 .motion,.columns-4 .motion{grid-area:motion;justify-content:center;padding:4px 6px}.columns-3 .scene,.columns-4 .scene{height:clamp(64px,12cqw,88px)}.columns-3 .foot,.columns-4 .foot{display:grid;margin-top:6px}.columns-3 .foot em,.columns-4 .foot em{display:none}
    .columns-1 .faces{gap:8px}.columns-1 .scene{height:clamp(72px,28cqw,112px)}.columns-1 .face{padding:9px}.columns-1 .face-head{margin-bottom:6px}.columns-1 .foot{margin-top:6px}
    @keyframes roll{to{background-position:30px 0}}@keyframes sweep{0%{left:-40%;opacity:0}35%{opacity:1}100%{left:120%;opacity:0}}@keyframes airflow{0%{left:-45%;opacity:0}25%{opacity:.9}100%{left:110%;opacity:0}}@keyframes pulse{0%,100%{opacity:.55;transform:scale(.85)}50%{opacity:1;transform:scale(1.2)}}
    @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
  `;

  constructor(){super();this.attachShadow({mode:'open'});this._config=normalizeConfig({});this._layout='columns-2';this._observer=null;this._lastRect={width:0,height:0};this._hass=null;this._pendingActions=new Map()}
  set hass(value){this._hass=value;this._render()}
  get hass(){return this._hass}
  setConfig(config){this._config=normalizeConfig(config);this._measure();this._render()}
  connectedCallback(){this._observe();this._measure();this._render()}
  disconnectedCallback(){this._observer?.disconnect()}
  _observe(){if(!globalThis.ResizeObserver)return;if(!this._observer)this._observer=new ResizeObserver((entries)=>{const r=entries[0]?.contentRect;if(r)this._setLayout(r.width,r.height)});this._observer.disconnect();this._observer.observe(this)}
  _measure(){const r=this.getBoundingClientRect?.();if(r)this._setLayout(r.width,r.height)}
  _setLayout(width,height){this._lastRect={width,height};const next=selectLayout({width,itemsPerRow:this._config.items_per_row});if(next!==this._layout){this._layout=next;this._render()}}
  _moreInfo(entityId){if(!entityId)return;this.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId},bubbles:true,composed:true}))}
  async _control(event){
    event.stopPropagation();
    const button=event.currentTarget;const entityId=button?.dataset?.entity;const action=button?.dataset?.action;const service=coverServiceForAction(action);
    if(!entityId||!service||!this.hass?.callService)return;
    const pending=this._pendingActions.get(entityId)??new Set();
    if((action==='stop'&&pending.has('stop'))||(action!=='stop'&&pending.size))return;
    pending.add(action);this._pendingActions.set(entityId,pending);this._render();
    try{await this.hass.callService('cover',service,{entity_id:entityId})}
    catch(error){this.dispatchEvent(new CustomEvent('hass-notification',{detail:{message:`${this._config.title}控制失敗：${error?.message??error}`},bubbles:true,composed:true}))}
    finally{pending.delete(action);if(!pending.size)this._pendingActions.delete(entityId);this._render()}
  }

  _render(){
    if(!this.shadowRoot)return;
    if(!this.hass){this.shadowRoot.innerHTML=`<style>${this.constructor.styles}</style><div class="rollup-card"><div>等待 Home Assistant 狀態資料…</div></div>`;return}
    const tokens=resolveThemeTokens(this._config);const subtitle=resolveSubtitle(this._config,this.hass.states);
    const style=`--rollup-bg:${tokens.background};--rollup-surface:${tokens.surface};--rollup-text:${tokens.text};--rollup-muted:${tokens.muted};--rollup-frame:${tokens.frame};--rollup-moving:${this._config.status_moving_color};--rollup-idle:${this._config.status_idle_color};--closed-color:${this._config.closed_color}`;
    this.shadowRoot.innerHTML=`<style>${this.constructor.styles}</style><div class="rollup-card ${escapeHtml(this._layout)}" style="${escapeHtml(style)}" aria-label="${escapeHtml(`${this._config.title}，${subtitle}`)}">
      <header class="header"><div><h2>${escapeHtml(this._config.title)}</h2>${subtitle?`<p>${escapeHtml(subtitle)}</p>`:''}</div><span class="system"><i></i>GREENHOUSE VENTILATION</span></header>
      <section class="faces">${this._config.faces.map((face)=>this._renderFace(face)).join('')}</section>
    </div>`;
    this.shadowRoot.querySelectorAll('.face').forEach((element)=>element.addEventListener('click',()=>this._moreInfo(element.dataset.entity)));
    this.shadowRoot.querySelectorAll('.more-info').forEach((button)=>button.addEventListener('click',(event)=>{event.stopPropagation();this._moreInfo(button.dataset.entity)}));
    this.shadowRoot.querySelectorAll('.controls button').forEach((button)=>button.addEventListener('click',(event)=>this._control(event)));
  }

  _renderFace(face){
    const state=resolveFaceState(face,this.hass.states);const displayName=rollupName(face.name);const visualPercent=state.positionKnown?state.percent:50;const accent=face.accent_color||this._config.open_color;const status=state.commandState==='conflict'?'#ff6b6b':state.moving?this._config.status_moving_color:this._config.status_idle_color;const light=18+visualPercent*.48;const open=face.accent_color||`hsl(43 96% ${light}%)`;const cls=`face ${state.moving?'moving':'idle'} ${state.positionKnown?'':'unknown'} ${state.commandState==='conflict'?'conflict':''} ${this._config.animation?'animated':''}`;
    const detail=state.integration?[state.commandLabel,state.confidenceLabel].filter(Boolean).join(' · '):state.available?`${Math.round(state.value)} ${this._config.unit} / ${state.maximum} ${this._config.unit}`:face.entity||'尚未設定實體';
    const pending=this._pendingActions.get(state.controlEntity)??new Set();const directionDisabled=!state.available||state.commandState==='conflict'||pending.size>0;const stopDisabled=!state.available||pending.has('stop');
    const controlCount=['open','stop','close'].filter((action)=>state.supports?.[action]!==false).length;
    const controls=state.integration&&controlCount?`<div class="controls" role="group" style="--control-count:${controlCount}" aria-label="${escapeHtml(`${displayName}控制`)}">
      ${state.supports?.open!==false?`<button type="button" data-action="open" data-entity="${escapeHtml(state.controlEntity)}" ${directionDisabled?'disabled':''} aria-label="開啟${escapeHtml(displayName)}">▲ 開啟</button>`:''}
      ${state.supports?.stop!==false?`<button type="button" class="stop" data-action="stop" data-entity="${escapeHtml(state.controlEntity)}" ${stopDisabled?'disabled':''} aria-label="停止${escapeHtml(displayName)}">■ 停止</button>`:''}
      ${state.supports?.close!==false?`<button type="button" data-action="close" data-entity="${escapeHtml(state.controlEntity)}" ${directionDisabled?'disabled':''} aria-label="關閉${escapeHtml(displayName)}">▼ 關閉</button>`:''}
    </div>`:'';
    return `<article class="${escapeHtml(cls)}" data-entity="${escapeHtml(state.controlEntity)}" style="--open:${visualPercent}%;--face-accent:${escapeHtml(accent)};--status-color:${escapeHtml(status)};--open-color:${escapeHtml(open)}">
      <div class="face-head"><span class="compass">${escapeHtml(face.compass)}</span><span class="name">${escapeHtml(displayName)}</span><span class="motion"><i></i>${escapeHtml(state.motionLabel)}</span></div>
      <div class="scene" role="img" aria-label="${escapeHtml(`${displayName}，${state.positionLabel}，${state.motionLabel}`)}">
        <div class="opening"><b class="ray one"></b><b class="ray two"></b><i class="rollup-air"></i><i class="rollup-air"></i><i class="rollup-air"></i></div>
        <div class="curtain"><i class="shine"></i><b></b><b></b></div><div class="roller"><i></i><span></span><i></i></div>
        <span class="scale top">100</span><span class="scale mid">50</span><span class="scale bottom">0</span><strong class="percent">${state.positionKnown?`${state.percent}%`:'—'}</strong>
      </div>
      <footer class="foot"><button type="button" class="more-info" data-entity="${escapeHtml(state.controlEntity)}" aria-label="開啟${escapeHtml(displayName)}詳細資料"><span class="copy"><strong>${escapeHtml(state.positionLabel)}</strong><small>${escapeHtml(detail)}</small></span><em>${state.positionKnown?`${state.percent}%`:'N/A'}</em></button></footer>
      ${controls}
    </article>`;
  }

  _layoutColumns(){return Number(this._layout.split('-').at(-1))||1}
  getCardSize(){return Math.max(4,Math.ceil(4/this._layoutColumns())*4)}
  getGridOptions(){return GRID_OPTIONS}
  static getStubConfig(){return normalizeConfig({faces:[{key:'east',entity_mode:'cover_entity'},{key:'south',entity_mode:'cover_entity'},{key:'west',entity_mode:'cover_entity'},{key:'north',entity_mode:'cover_entity'}]})}
  static async getConfigElement(){await customElements.whenDefined('uninus-greenhouse-rollup-card-editor');return document.createElement('uninus-greenhouse-rollup-card-editor')}
}
