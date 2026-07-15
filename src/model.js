export const FACE_KEYS = ['east', 'south', 'west', 'north'];

const FACE_DEFAULTS = {
  east: { key: 'east', compass: 'E', name: '東側' },
  south: { key: 'south', compass: 'S', name: '南側' },
  west: { key: 'west', compass: 'W', name: '西側' },
  north: { key: 'north', compass: 'N', name: '北側' },
};

const THEMES = new Set(['dark', 'light', 'greenhouse', 'sand']);
const COLOR_PATTERN = /^(#[0-9a-f]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\)|[a-z]+)$/i;

export const DEFAULT_CONFIG = Object.freeze({
  type: 'custom:uninus-greenhouse-rollup-card',
  title: '溫室側簾捲揚',
  subtitle: '四向開啟位置・透光／通風狀態・即時運轉監測',
  subtitle_entity: '',
  subtitle_attribute: '',
  theme: 'dark',
  items_per_row: 2,
  animation: true,
  unit: '秒',
  status_idle_color: '#8798a2',
  status_moving_color: '#ffd54a',
  closed_color: '#3d4b52',
  open_color: '#ffd54a',
  background_color: '',
});

export const GRID_OPTIONS = Object.freeze({ columns: 'full', min_columns: 6 });

export function isValidColor(value) {
  return typeof value === 'string' && COLOR_PATTERN.test(value.trim()) && !/url|javascript|expression/i.test(value);
}

function normalizeFace(input, key) {
  const base = FACE_DEFAULTS[key];
  const value = input && typeof input === 'object' ? input : {};
  return {
    ...base,
    entity: '',
    motion_entity: '',
    max_entity: '',
    ...value,
    key,
    name: String(value.name ?? base.name),
    max_value: Number.isFinite(Number(value.max_value)) && Number(value.max_value) > 0 ? Number(value.max_value) : 120,
    accent_color: isValidColor(value.accent_color) ? value.accent_color : '',
  };
}

export function normalizeConfig(raw = {}) {
  const input = raw && typeof raw === 'object' ? raw : {};
  const { force_1x4: legacyForceOneByFour, ...config } = input;
  const suppliedFaces = Array.isArray(config.faces) ? config.faces : [];
  const byKey = new Map(suppliedFaces.map((face) => [face?.key, face]));
  const normalized = {
    ...DEFAULT_CONFIG,
    ...config,
    type: DEFAULT_CONFIG.type,
    theme: THEMES.has(config.theme) ? config.theme : DEFAULT_CONFIG.theme,
    items_per_row: Number.isFinite(Number(config.items_per_row))
      ? Math.max(1, Math.min(4, Math.floor(Number(config.items_per_row))))
      : legacyForceOneByFour === true ? 4 : DEFAULT_CONFIG.items_per_row,
    animation: config.animation !== false,
    faces: FACE_KEYS.map((key, index) => normalizeFace(byKey.get(key) ?? suppliedFaces[index], key)),
  };
  for (const key of ['status_idle_color', 'status_moving_color', 'closed_color', 'open_color']) {
    if (!isValidColor(config[key])) normalized[key] = DEFAULT_CONFIG[key];
  }
  normalized.background_color = isValidColor(config.background_color) ? config.background_color : '';
  return normalized;
}

function numericState(entityId, states) {
  if (!entityId || !states?.[entityId]) return Number.NaN;
  return Number(states[entityId].state);
}

export function resolveFaceState(face, states = {}) {
  const raw = numericState(face.entity, states);
  const maxFromEntity = numericState(face.max_entity, states);
  const maximum = Number.isFinite(maxFromEntity) && maxFromEntity > 0
    ? maxFromEntity
    : Number.isFinite(Number(face.max_value)) && Number(face.max_value) > 0 ? Number(face.max_value) : 120;
  const available = Number.isFinite(raw);
  const value = available ? raw : 0;
  const percent = Math.max(0, Math.min(100, Math.round((value / maximum) * 100)));
  const motionState = face.motion_entity ? states?.[face.motion_entity] : undefined;
  const state = String(motionState?.state ?? '').toLowerCase();
  const direction = String(motionState?.attributes?.direction ?? state).toLowerCase();
  const moving = state === 'on' || state === 'opening' || state === 'closing' || state === 'moving';
  const motion = !moving ? 'idle' : direction === 'closing' ? 'closing' : direction === 'opening' ? 'opening' : 'moving';
  const motionLabel = motion === 'idle' ? '靜止' : motion === 'opening' ? '開啟中' : motion === 'closing' ? '關閉中' : '捲動中';
  const positionLabel = !available ? '位置資料不可用' : percent <= 0 ? '全閉' : percent >= 100 ? '全開' : `局部開啟 ${percent}%`;
  return { available, value, maximum, percent, moving, motion, motionLabel, positionLabel };
}

export function resolveSubtitle(config, states = {}) {
  const entity = config.subtitle_entity ? states?.[config.subtitle_entity] : undefined;
  if (entity && config.subtitle_attribute) {
    const value = entity.attributes?.[config.subtitle_attribute];
    if (value !== undefined && value !== null && value !== '') return String(value);
  }
  if (entity && !config.subtitle_attribute && entity.state !== undefined) return String(entity.state);
  return String(config.subtitle ?? '');
}

export function selectLayout({ itemsPerRow = DEFAULT_CONFIG.items_per_row } = {}) {
  const requested = Math.max(1, Math.min(4, Math.floor(Number(itemsPerRow)) || DEFAULT_CONFIG.items_per_row));
  return `columns-${requested}`;
}

export function updateFaceConfig(config, faceKey, property, value) {
  return {
    ...config,
    faces: config.faces.map((face) => face.key === faceKey ? { ...face, [property]: value } : face),
  };
}

export function applyEditorChange(config, { faceKey, property, value, valueType } = {}) {
  const nextValue = valueType === 'boolean' ? value === true : value;
  if (faceKey) return updateFaceConfig(config, faceKey, property, nextValue);
  return { ...config, [property]: nextValue };
}

const THEME_TOKENS = Object.freeze({
  dark: { background: 'linear-gradient(145deg,#172229,#080e12)', surface: 'rgba(39,52,60,.92)', text: '#f5f8fa', muted: 'rgba(218,230,236,.58)', frame: '#111c22' },
  light: { background: 'linear-gradient(145deg,#f7faf8,#dfe9e5)', surface: 'rgba(255,255,255,.82)', text: '#183028', muted: 'rgba(24,48,40,.62)', frame: '#d2dfda' },
  greenhouse: { background: 'linear-gradient(145deg,#123a32,#071e1a)', surface: 'rgba(27,78,66,.74)', text: '#f2fff9', muted: 'rgba(210,246,231,.64)', frame: '#0c2924' },
  sand: { background: 'linear-gradient(145deg,#fff2cd,#d8b875)', surface: 'rgba(255,250,235,.72)', text: '#3d2d17', muted: 'rgba(61,45,23,.62)', frame: '#ae8a49' },
});

export function resolveThemeTokens(config) {
  const tokens = { ...(THEME_TOKENS[config.theme] ?? THEME_TOKENS.dark) };
  if (isValidColor(config.background_color)) tokens.background = config.background_color;
  return tokens;
}

export const THEME_OPTIONS = Object.freeze([
  { value: 'dark', label: '原始暗色' },
  { value: 'light', label: '明亮霧白' },
  { value: 'greenhouse', label: '溫室青綠' },
  { value: 'sand', label: '日光暖沙' },
]);
