# UNiNUS Greenhouse Rollup Card

專為 Home Assistant 設計的四面溫室捲揚 Lovelace 卡片。卡片以側簾剖面、捲軸位置、透光亮度與氣流動畫，同時表現東／南／西／北捲揚的最終位置及運轉狀態。

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/) [![CI](https://github.com/ivanlee1007/uninus-greenhouse-rollup-card/actions/workflows/ci.yml/badge.svg)](https://github.com/ivanlee1007/uninus-greenhouse-rollup-card/actions/workflows/ci.yml)

## 特色

- 四面位置 Entity、捲動 Entity、最大刻度 Entity／固定最大值。
- 全閉、局部開啟、全開及實際刻度文字。
- 開啟面積越大，顯示越明亮；捲動時具有捲軸、氣流、掃光及狀態燈動畫。
- 完整**視覺化設定**：標題、副標文字、副標 Entity／Attribute、四面名稱與 Entity、狀態色、開啟色、每面強調色及背景氛圍。
- `ResizeObserver` 依卡片本身的寬、高及比例切換 `1 × 4`、`2 × 2`、單欄與短版配置，而不是只看瀏覽器寬度。
- 可由設定 UI 強制使用 **1 × 4** 模式。
- 背景預設提供：原始暗色、明亮霧白、溫室青綠、日光暖沙，亦可指定自訂 CSS 顏色。
- 支援 `prefers-reduced-motion`、HA More Info 與 Sections Grid。

## HACS 安裝

1. HACS → Frontend → 右上角選單 → Custom repositories。
2. Repository：`https://github.com/ivanlee1007/uninus-greenhouse-rollup-card`
3. Type：Dashboard。
4. 安裝 `UNiNUS Greenhouse Rollup Card` 並重新整理瀏覽器。

也可手動下載 `uninus-greenhouse-rollup-card.js` 到 `/config/www/`，並新增 JavaScript Module Resource：

```text
/local/uninus-greenhouse-rollup-card.js
```

## 最小設定

```yaml
type: custom:uninus-greenhouse-rollup-card
faces:
  - key: east
    name: 東側
    entity: input_number.up_lift_position_e
    motion_entity: binary_sensor.rollup_e_moving
    max_value: 120
  - key: south
    name: 南側
    entity: input_number.up_lift_position_s
    motion_entity: binary_sensor.rollup_s_moving
    max_value: 120
  - key: west
    name: 西側
    entity: input_number.up_lift_position_w
    motion_entity: binary_sensor.rollup_w_moving
    max_value: 120
  - key: north
    name: 北側
    entity: input_number.up_lift_position_n
    motion_entity: binary_sensor.rollup_n_moving
    max_value: 120
```

新增卡片時可直接在 HA 卡片選擇器搜尋 **UNiNUS Greenhouse Rollup Card**，建議優先使用視覺化設定 UI。

## 完整設定範例

```yaml
type: custom:uninus-greenhouse-rollup-card
title: 溫室側簾捲揚
subtitle: 四向即時監測
subtitle_entity: sensor.greenhouse_status
subtitle_attribute: description
theme: greenhouse
background_color: ""
force_1x4: false
animation: true
unit: 秒
status_idle_color: "#8798a2"
status_moving_color: "#ffd54a"
closed_color: "#3d4b52"
open_color: "#ffd54a"
faces:
  - key: east
    name: 東側
    entity: input_number.up_lift_position_e
    motion_entity: binary_sensor.rollup_e_moving
    max_entity: input_number.rollup_e_maximum
    max_value: 120
    accent_color: "#ffc83d"
```

未列出的南、西、北面會由卡片補上預設結構，可在設定 UI 中逐面設定。

## Motion Entity 狀態

- `off`：靜止
- `on`：捲動中；若 Attribute `direction` 為 `opening`／`closing`，會顯示開啟中／關閉中。
- `opening`：開啟中
- `closing`：關閉中
- `moving`：捲動中

## 開發

```bash
npm install
npm test
npm run build
npm run check
```

建置產物固定為根目錄的 `uninus-greenhouse-rollup-card.js`，與 `hacs.json` 的 `filename` 一致。CI 會重新建置並確認提交的產物未過期。

## License

MIT
