import { applyEditorChange, configForSave, normalizeConfig, THEME_OPTIONS } from './model.js';

const escapeHtml=(value)=>String(value??'').replace(/[&<>"']/g,(char)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const DEFAULT_FACE_NAMES={east:'東側',south:'南側',west:'西側',north:'北側'};
const isCoverEntity=(value)=>/^cover\.[a-z0-9_]+$/.test(String(value??''));

export class UninusGreenhouseRollupCardEditor extends HTMLElement {
  static styles=`
    :host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
    .editor{display:grid;gap:14px;padding:4px}.section{display:grid;gap:11px;padding:14px;border:1px solid var(--divider-color,#ddd);border-radius:14px;background:var(--card-background-color,#fff)}h3{margin:0;font-size:15px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.field{display:grid;gap:5px;min-width:0}.field.full{grid-column:1/-1}label{font-size:11px;color:var(--secondary-text-color)}input,select{width:100%;min-width:0;height:40px;box-sizing:border-box;padding:0 10px;border:1px solid var(--divider-color,#bbb);border-radius:9px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font:inherit}input[type=color]{padding:4px}ha-entity-picker{display:block;min-width:0}.validation{grid-column:1/-1;margin:0;color:var(--error-color,#db4437);font-size:12px}.switch{display:flex;align-items:center;justify-content:space-between;gap:10px}.switch input{width:18px;height:18px}.faces{display:grid;gap:9px}.face{border:1px solid var(--divider-color,#ddd);border-radius:12px;overflow:hidden}.face summary{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;cursor:pointer;font-weight:700}.face .body{display:grid;gap:10px;padding:0 12px 12px}@media(max-width:560px){.grid{grid-template-columns:1fr}.field.full{grid-column:auto}}
  `;
  constructor(){super();this.attachShadow({mode:'open'});this._config=normalizeConfig({});this._hass=null;this._boundChange=(event)=>this._handleChange(event);this._boundEntity=(event)=>this._handleChange(event)}
  set hass(value){const first=!this._hass;this._hass=value;if(first)this._render();else this.shadowRoot?.querySelectorAll('ha-entity-picker').forEach((picker)=>picker.hass=value)}
  get hass(){return this._hass}
  setConfig(config){this._config=normalizeConfig(config);this._render()}
  connectedCallback(){this._render()}
  _handleChange(event){
    const element=event.target.closest?.('[data-property]')||event.target;if(!element?.dataset?.property)return;
    const valueType=element.dataset.valueType;let value=event.detail?.value??(valueType==='boolean'?element.checked:element.value??'');if(element.dataset.number==='true')value=Number(value);
    const change={property:element.dataset.property,value,valueType};if(element.dataset.face)change.faceKey=element.dataset.face;
    let next=applyEditorChange(this._config,change);
    if(change.property==='cover_entity'&&change.faceKey){const current=this._config.faces.find((face)=>face.key===change.faceKey);const friendly=this.hass?.states?.[value]?.attributes?.friendly_name;if(friendly&&(!current?.name||current.name===DEFAULT_FACE_NAMES[change.faceKey]))next=applyEditorChange(next,{faceKey:change.faceKey,property:'name',value:String(friendly)})}
    this._config=normalizeConfig(next);
    this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:configForSave(this._config)},bubbles:true,composed:true}));
  }
  _text(property,label,value,full=false,extra=''){return `<div class="field ${full?'full':''}"><label>${escapeHtml(label)}</label><input data-property="${property}" value="${escapeHtml(value)}" ${extra}></div>`}
  _entity(property,label,value,face='',domains=[]){const domainData=escapeHtml(domains.join(','));const allowCustom=domains.length?'':'allow-custom-entity';return customElements.get('ha-entity-picker')?`<div class="field"><ha-entity-picker data-property="${property}" data-face="${face}" data-value="${escapeHtml(value)}" data-label="${escapeHtml(label)}" data-domains="${domainData}" ${allowCustom} show-entity-id></ha-entity-picker></div>`:`<div class="field"><label>${escapeHtml(label)}</label><input data-property="${property}" data-face="${face}" value="${escapeHtml(value)}" placeholder="sensor.example"></div>`}
  _color(property,label,value,face=''){return `<div class="field"><label>${escapeHtml(label)}</label><input type="color" data-property="${property}" data-face="${face}" value="${escapeHtml(value||'#ffd54a')}"></div>`}
  _render(){
    if(!this.shadowRoot)return;const c=this._config;const hasLegacy=c.faces.some((face)=>face.entity_mode==='position_entity');
    this.shadowRoot.removeEventListener('change',this._boundChange);this.shadowRoot.removeEventListener('value-changed',this._boundEntity);
    this.shadowRoot.innerHTML=`<style>${this.constructor.styles}</style><div class="editor">
      <section class="section"><h3>內容與資料來源</h3><div class="grid">
        ${this._text('title','標題',c.title,true)}${this._text('subtitle','副標文字',c.subtitle,true)}
        ${this._entity('subtitle_entity','副標 Entity',c.subtitle_entity)}${this._text('subtitle_attribute','副標 Attribute',c.subtitle_attribute)}${hasLegacy?this._text('unit','舊版位置值單位',c.unit):''}
      </div></section>
      <section class="section"><h3>版面與外觀</h3><div class="grid">
        <div class="field"><label>背景氛圍</label><select data-property="theme">${THEME_OPTIONS.map((option)=>`<option value="${option.value}" ${option.value===c.theme?'selected':''}>${escapeHtml(option.label)}</option>`).join('')}</select></div>
        ${this._text('background_color','自訂背景色（選填）',c.background_color)}
        ${this._color('status_idle_color','靜止狀態色',c.status_idle_color)}${this._color('status_moving_color','捲動狀態色',c.status_moving_color)}
        ${this._color('closed_color','關閉區域色',c.closed_color)}${this._color('open_color','開啟／捲軸色',c.open_color)}
        <div class="field"><label>每列捲揚數量（最多 4 個）</label><select data-property="items_per_row" data-number="true">${[1,2,3,4].map((count)=>`<option value="${count}" ${count===c.items_per_row?'selected':''}>${count} 個</option>`).join('')}</select></div>
        <div class="field switch"><label>啟用動畫</label><input type="checkbox" data-property="animation" data-value-type="boolean" ${c.animation?'checked':''}></div>
      </div></section>
      <section class="section"><h3>四面捲揚設定</h3><div class="faces">${c.faces.map((face,index)=>`<details class="face face-editor" ${index===0?'open':''}><summary><span>${escapeHtml(face.compass)}・${escapeHtml(face.name)}</span><span>›</span></summary><div class="body"><div class="grid">
        <div class="field"><label>顯示名稱</label><input data-face="${face.key}" data-property="name" value="${escapeHtml(face.name)}"></div>
        ${this._color('accent_color','此面強調色',face.accent_color||c.open_color,face.key)}
        <div class="field"><label>資料模式</label><select data-face="${face.key}" data-property="entity_mode"><option value="cover_entity" ${face.entity_mode==='cover_entity'?'selected':''}>標準 Cover</option><option value="position_entity" ${face.entity_mode==='position_entity'?'selected':''}>舊版位置 Entity</option></select></div>
        ${face.entity_mode==='cover_entity'
          ?`${this._entity('cover_entity','標準 Cover Entity',face.cover_entity,face.key,['cover'])}${isCoverEntity(face.cover_entity)?'':'<p class="validation" role="alert">請選擇有效的 cover.* 標準 Cover Entity。</p>'}`
          :`${this._entity('entity','舊版位置 Entity',face.entity,face.key,['sensor','input_number'])}${this._entity('motion_entity','舊版捲動狀態 Entity',face.motion_entity,face.key,['binary_sensor','sensor','input_boolean'])}${this._entity('max_entity','最大刻度 Entity（選填）',face.max_entity,face.key,['sensor','input_number'])}<div class="field"><label>固定最大刻度</label><input type="number" min="1" step="1" data-number="true" data-face="${face.key}" data-property="max_value" value="${face.max_value}"></div>`}
      </div></div></details>`).join('')}</div></section>
    </div>`;
    this.shadowRoot.addEventListener('change',this._boundChange);this.shadowRoot.addEventListener('value-changed',this._boundEntity);
    this.shadowRoot.querySelectorAll('ha-entity-picker').forEach((picker)=>{picker.hass=this.hass;picker.value=picker.dataset.value||'';picker.label=picker.dataset.label||'';const domains=(picker.dataset.domains||'').split(',').filter(Boolean);if(domains.length)picker.includeDomains=domains});
  }
}
