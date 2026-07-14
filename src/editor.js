import { LitElement, html, css } from 'lit';
import { applyEditorChange, normalizeConfig, THEME_OPTIONS } from './model.js';

export class UninusGreenhouseRollupCardEditor extends LitElement {
  static properties={hass:{attribute:false},_config:{state:true},_openFace:{state:true}};
  static styles=css`
    :host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
    .editor{display:grid;gap:14px;padding:4px}.section{display:grid;gap:11px;padding:14px;border:1px solid var(--divider-color,#ddd);border-radius:14px;background:var(--card-background-color,#fff)}h3{margin:0;font-size:15px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.field{display:grid;gap:5px;min-width:0}.field.full{grid-column:1/-1}label{font-size:11px;color:var(--secondary-text-color)}input,select{width:100%;min-width:0;height:40px;box-sizing:border-box;padding:0 10px;border:1px solid var(--divider-color,#bbb);border-radius:9px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font:inherit}input[type=color]{padding:4px}ha-entity-picker{display:block;min-width:0}.switch{display:flex;align-items:center;justify-content:space-between;gap:10px}.switch input{width:18px;height:18px}.faces{display:grid;gap:9px}.face{border:1px solid var(--divider-color,#ddd);border-radius:12px;overflow:hidden}.face summary{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;cursor:pointer;font-weight:700}.face .body{display:grid;gap:10px;padding:0 12px 12px}@media(max-width:560px){.grid{grid-template-columns:1fr}.field.full{grid-column:auto}}
  `;
  constructor(){super();this._config=normalizeConfig({});this._openFace='east'}
  setConfig(config){this._config=normalizeConfig(config)}
  _emit(change){this._config=normalizeConfig(applyEditorChange(this._config,change));this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._config},bubbles:true,composed:true}))}
  _value(event){return event.detail?.value ?? event.target?.value ?? ''}
  _global(event){const el=event.currentTarget;const property=el.dataset.property;const valueType=el.dataset.valueType;const value=valueType==='boolean'?el.checked:this._value(event);this._emit({property,value,valueType})}
  _face(event){const el=event.currentTarget;let value=this._value(event);if(el.dataset.number==='true')value=Number(value);this._emit({faceKey:el.dataset.face,property:el.dataset.property,value})}
  _text(property,label,value,full=false){return html`<div class=${`field ${full?'full':''}`}><label>${label}</label><input data-property=${property} .value=${value??''} @change=${this._global}></div>`}
  _entity(property,label,value,faceKey=''){
    const attrs={};
    return html`<div class="field"><label>${label}</label>${customElements.get('ha-entity-picker')?html`<ha-entity-picker .hass=${this.hass} .value=${value||''} .label=${label} allow-custom-entity show-entity-id data-property=${property} data-face=${faceKey} @value-changed=${faceKey?this._face:this._global}></ha-entity-picker>`:html`<input placeholder="sensor.example" data-property=${property} data-face=${faceKey} .value=${value||''} @change=${faceKey?this._face:this._global}>`}</div>`;
  }
  _color(property,label,value,faceKey=''){return html`<div class="field"><label>${label}</label><input type="color" data-property=${property} data-face=${faceKey} .value=${value||'#ffd54a'} @change=${faceKey?this._face:this._global}></div>`}
  render(){const c=this._config;return html`<div class="editor">
    <section class="section"><h3>內容與資料來源</h3><div class="grid">
      ${this._text('title','標題',c.title,true)}${this._text('subtitle','副標文字',c.subtitle,true)}
      ${this._entity('subtitle_entity','副標 Entity',c.subtitle_entity)}${this._text('subtitle_attribute','副標 Attribute',c.subtitle_attribute)}
      ${this._text('unit','位置單位',c.unit)}
    </div></section>
    <section class="section"><h3>版面與外觀</h3><div class="grid">
      <div class="field"><label>背景氛圍</label><select data-property="theme" .value=${c.theme} @change=${this._global}>${THEME_OPTIONS.map(o=>html`<option value=${o.value}>${o.label}</option>`)}</select></div>
      ${this._text('background_color','自訂背景色（選填）',c.background_color)}
      ${this._color('status_idle_color','靜止狀態色',c.status_idle_color)}${this._color('status_moving_color','捲動狀態色',c.status_moving_color)}
      ${this._color('closed_color','關閉區域色',c.closed_color)}${this._color('open_color','開啟／捲軸色',c.open_color)}
      <div class="field switch"><label>啟用動畫</label><input type="checkbox" data-property="animation" data-value-type="boolean" .checked=${c.animation} @change=${this._global}></div>
      <div class="field switch"><label>強制 1 × 4 模式</label><input type="checkbox" data-property="force_1x4" data-value-type="boolean" .checked=${c.force_1x4} @change=${this._global}></div>
    </div></section>
    <section class="section"><h3>四面捲揚設定</h3><div class="faces">${c.faces.map(face=>html`<details class="face" ?open=${face.key===this._openFace} @toggle=${e=>{if(e.currentTarget.open)this._openFace=face.key}}><summary><span>${face.compass}・${face.name}</span><span>›</span></summary><div class="body"><div class="grid">
      <div class="field"><label>顯示名稱</label><input data-face=${face.key} data-property="name" .value=${face.name} @change=${this._face}></div>
      ${this._color('accent_color','此面強調色',face.accent_color||c.open_color,face.key)}
      ${this._entity('entity','位置 Entity',face.entity,face.key)}${this._entity('motion_entity','捲動狀態 Entity',face.motion_entity,face.key)}
      ${this._entity('max_entity','最大刻度 Entity（選填）',face.max_entity,face.key)}
      <div class="field"><label>固定最大刻度</label><input type="number" min="1" step="1" data-number="true" data-face=${face.key} data-property="max_value" .value=${String(face.max_value)} @change=${this._face}></div>
    </div></div></details>`)}</div></section>
  </div>`}
}
