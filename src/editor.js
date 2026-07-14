import { applyEditorChange, normalizeConfig, THEME_OPTIONS } from './model.js';

const escapeHtml=(value)=>String(value??'').replace(/[&<>"']/g,(char)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export class UninusGreenhouseRollupCardEditor extends HTMLElement {
  static styles=`
    :host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
    .editor{display:grid;gap:14px;padding:4px}.section{display:grid;gap:11px;padding:14px;border:1px solid var(--divider-color,#ddd);border-radius:14px;background:var(--card-background-color,#fff)}h3{margin:0;font-size:15px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.field{display:grid;gap:5px;min-width:0}.field.full{grid-column:1/-1}label{font-size:11px;color:var(--secondary-text-color)}input,select{width:100%;min-width:0;height:40px;box-sizing:border-box;padding:0 10px;border:1px solid var(--divider-color,#bbb);border-radius:9px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font:inherit}input[type=color]{padding:4px}ha-entity-picker{display:block;min-width:0}.switch{display:flex;align-items:center;justify-content:space-between;gap:10px}.switch input{width:18px;height:18px}.faces{display:grid;gap:9px}.face{border:1px solid var(--divider-color,#ddd);border-radius:12px;overflow:hidden}.face summary{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;cursor:pointer;font-weight:700}.face .body{display:grid;gap:10px;padding:0 12px 12px}@media(max-width:560px){.grid{grid-template-columns:1fr}.field.full{grid-column:auto}}
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
    this._config=normalizeConfig(applyEditorChange(this._config,change));
    this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._config},bubbles:true,composed:true}));
  }
  _text(property,label,value,full=false,extra=''){return `<div class="field ${full?'full':''}"><label>${escapeHtml(label)}</label><input data-property="${property}" value="${escapeHtml(value)}" ${extra}></div>`}
  _entity(property,label,value,face=''){return `<div class="field"><label>${escapeHtml(label)}</label>${customElements.get('ha-entity-picker')?`<ha-entity-picker data-property="${property}" data-face="${face}" data-value="${escapeHtml(value)}" data-label="${escapeHtml(label)}" allow-custom-entity show-entity-id></ha-entity-picker>`:`<input data-property="${property}" data-face="${face}" value="${escapeHtml(value)}" placeholder="sensor.example">`}</div>`}
  _color(property,label,value,face=''){return `<div class="field"><label>${escapeHtml(label)}</label><input type="color" data-property="${property}" data-face="${face}" value="${escapeHtml(value||'#ffd54a')}"></div>`}
  _render(){
    if(!this.shadowRoot)return;const c=this._config;
    this.shadowRoot.removeEventListener('change',this._boundChange);this.shadowRoot.removeEventListener('value-changed',this._boundEntity);
    this.shadowRoot.innerHTML=`<style>${this.constructor.styles}</style><div class="editor">
      <section class="section"><h3>內容與資料來源</h3><div class="grid">
        ${this._text('title','標題',c.title,true)}${this._text('subtitle','副標文字',c.subtitle,true)}
        ${this._entity('subtitle_entity','副標 Entity',c.subtitle_entity)}${this._text('subtitle_attribute','副標 Attribute',c.subtitle_attribute)}${this._text('unit','位置單位',c.unit)}
      </div></section>
      <section class="section"><h3>版面與外觀</h3><div class="grid">
        <div class="field"><label>背景氛圍</label><select data-property="theme">${THEME_OPTIONS.map((option)=>`<option value="${option.value}" ${option.value===c.theme?'selected':''}>${escapeHtml(option.label)}</option>`).join('')}</select></div>
        ${this._text('background_color','自訂背景色（選填）',c.background_color)}
        ${this._color('status_idle_color','靜止狀態色',c.status_idle_color)}${this._color('status_moving_color','捲動狀態色',c.status_moving_color)}
        ${this._color('closed_color','關閉區域色',c.closed_color)}${this._color('open_color','開啟／捲軸色',c.open_color)}
        <div class="field switch"><label>啟用動畫</label><input type="checkbox" data-property="animation" data-value-type="boolean" ${c.animation?'checked':''}></div>
        <div class="field switch"><label>強制 1 × 4 模式</label><input type="checkbox" data-property="force_1x4" data-value-type="boolean" ${c.force_1x4?'checked':''}></div>
      </div></section>
      <section class="section"><h3>四面捲揚設定</h3><div class="faces">${c.faces.map((face,index)=>`<details class="face" ${index===0?'open':''}><summary><span>${escapeHtml(face.compass)}・${escapeHtml(face.name)}</span><span>›</span></summary><div class="body"><div class="grid">
        <div class="field"><label>顯示名稱</label><input data-face="${face.key}" data-property="name" value="${escapeHtml(face.name)}"></div>
        ${this._color('accent_color','此面強調色',face.accent_color||c.open_color,face.key)}
        ${this._entity('entity','位置 Entity',face.entity,face.key)}${this._entity('motion_entity','捲動狀態 Entity',face.motion_entity,face.key)}
        ${this._entity('max_entity','最大刻度 Entity（選填）',face.max_entity,face.key)}
        <div class="field"><label>固定最大刻度</label><input type="number" min="1" step="1" data-number="true" data-face="${face.key}" data-property="max_value" value="${face.max_value}"></div>
      </div></div></details>`).join('')}</div></section>
    </div>`;
    this.shadowRoot.addEventListener('change',this._boundChange);this.shadowRoot.addEventListener('value-changed',this._boundEntity);
    this.shadowRoot.querySelectorAll('ha-entity-picker').forEach((picker)=>{picker.hass=this.hass;picker.value=picker.dataset.value||'';picker.label=picker.dataset.label||''});
  }
}
