import { UninusGreenhouseRollupCard } from './card.js';
import { UninusGreenhouseRollupCardEditor } from './editor.js';

const CARD_TAG='uninus-greenhouse-rollup-card';
const EDITOR_TAG='uninus-greenhouse-rollup-card-editor';
const VERSION=__CARD_VERSION__;
if(!customElements.get(EDITOR_TAG))customElements.define(EDITOR_TAG,UninusGreenhouseRollupCardEditor);
if(!customElements.get(CARD_TAG))customElements.define(CARD_TAG,UninusGreenhouseRollupCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(card=>card.type===CARD_TAG))window.customCards.push({
  type:CARD_TAG,
  name:'UNiNUS Greenhouse Rollup Card',
  description:'Responsive four-face greenhouse roll-up curtain status card with animation and visual editor.',
  preview:true,
  documentationURL:'https://github.com/ivanlee1007/uninus-greenhouse-rollup',
});
console.info(`%c UNiNUS GREENHOUSE ROLLUP CARD %c v${VERSION} `,'color:#10241d;background:#ffd54a;font-weight:800;padding:3px 6px','color:#fff;background:#18382e;padding:3px 6px');
