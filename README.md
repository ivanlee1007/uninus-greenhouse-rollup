# UNiNUS Greenhouse Rollup

專為 Home Assistant 溫室側簾設計的 **Integration + Lovelace Card**。每個真實捲揚由兩個互斥的 `switch` 控制開啟與關閉；Integration 依人工量測的完整行程時間估算並恢復位置，卡片則顯示估算位置、命令狀態、可信度並提供開啟／停止／關閉控制。

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/) [![CI](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml/badge.svg)](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml)

## 為什麼需要 Integration

底層 switch 的 `on` 代表智慧開關仍在執行計時，不保證馬達仍在轉。馬達可能已碰到硬體極限而停止，switch 稍後才更新為 `off`。因此：

- Integration 從上次保存位置、方向、經過時間及完整行程秒數估算位置。
- 中途將方向 switch 關閉時，位置會停在當下估算值並保存。
- 到達估算 `0%`／`100%` 後停止顯示運動，即使底層 switch 仍在計時。
- 完整跑完一次全開或全關行程即可校正端點。
- 位置會由 Home Assistant `RestoreEntity` 保存；重新整理卡片或更換瀏覽器不會遺失。
- 沒有實體位置感測器，因此 UI 一律明確標示「估算位置」與可信度。

位置定義：`0%` 為全關，`100%` 為全開。

## 特色

- 將一組開啟 switch 與關閉 switch 包裝成標準 Home Assistant `cover` entity。
- 開啟／關閉前先關閉兩個方向、等待可調整的安全間隔、再次確認兩方向關閉，再啟動單一方向；安全間隔期間的停止命令會取消延遲啟動。
- 支援 `cover.open_cover`、`cover.stop_cover`、`cover.close_cover`。
- 監聽卡片以外的手動操作、automation 與原始 switch 狀態變更。
- 顯示 `calibrated`、`estimated`、`unknown` 位置可信度。
- 兩個 switch 同時為 `on` 時顯示控制衝突且停止位置積分。
- 四面捲揚、精確的**每列捲揚數量**、動畫、主題與視覺化設定。
- 可在設定 UI 選擇每列 1～4 個捲揚（最多 4 個）；`items_per_row` 固定產生 1～4 欄，不會因卡片寬度擅自降欄。
- 保留 v1 的位置 Entity／Motion Entity 顯示模式，方便逐步移轉。

## HACS 安裝（v2 Integration）

需求：Home Assistant `2026.7.2` 或更新版本。

> 從 v1 Dashboard plugin 升級時，請先在 HACS 移除舊的 Dashboard repository，再將同一個 repository 以 **Integration** 類型重新加入。

1. HACS → Integrations → 右上角選單 → Custom repositories。
2. Repository：`https://github.com/ivanlee1007/uninus-greenhouse-rollup`
3. Type：**Integration**。
4. 安裝 `UNiNUS Greenhouse Rollup`。
5. 重新啟動 Home Assistant。

## 新增捲揚

每一個實體捲揚建立一個 Config Entry：

1. 設定 → 裝置與服務 → 新增整合。
2. 搜尋 `UNiNUS Greenhouse Rollup`。
3. 設定：
   - 名稱，例如「東側捲揚」；
   - 開啟／上捲 switch；
   - 關閉／下捲 switch；
   - 全開行程秒數；
   - 全關行程秒數；
   - 方向切換安全間隔秒數（預設 `0.2` 秒）。
4. 東、南、西、北分別重複新增。

首次安裝時位置為未知。讓捲揚在任一方向完整執行一次設定的行程時間後，Integration 會將端點校正為 `0%` 或 `100%`。

## 安裝卡片資源

Integration 會提供內建前端檔案。於「設定 → 儀表板 → 右上角選單 → 資源」新增 JavaScript Module：

```text
/uninus-greenhouse-rollup/uninus-greenhouse-rollup-card.js?v=2.0.2
```

之後重新整理瀏覽器。新增卡片時可搜尋 **UNiNUS Greenhouse Rollup Card**，並使用**視覺化設定**。

## Integration 卡片設定

```yaml
type: custom:uninus-greenhouse-rollup-card
title: 溫室側簾捲揚
items_per_row: 2
faces:
  - key: east
    name: 東側
    entity_mode: cover_entity
    cover_entity: cover.east_greenhouse_rollup
  - key: south
    name: 南側
    entity_mode: cover_entity
    cover_entity: cover.south_greenhouse_rollup
  - key: west
    name: 西側
    entity_mode: cover_entity
    cover_entity: cover.west_greenhouse_rollup
  - key: north
    name: 北側
    entity_mode: cover_entity
    cover_entity: cover.north_greenhouse_rollup
```

每一面設定 `cover_entity` 後會顯示：

- 估算位置與端點校正狀態；
- 實際位置積分中的開啟／關閉動畫；
- 「開啟命令中」或「關閉命令中」；
- 到端點後「已全開／已全關」，並另外顯示底層 switch 尚在計時；
- 開啟、停止、關閉三個控制按鈕。

## 狀態語意

| `command_state` | 意義 |
|---|---|
| `idle` | 兩個底層 switch 都是 `off` |
| `opening` | 開啟命令中，位置尚未到 100% |
| `closing` | 關閉命令中，位置尚未到 0% |
| `opening_timer` | 已估算全開，但開啟 switch 仍在計時 |
| `closing_timer` | 已估算全關，但關閉 switch 仍在計時 |
| `conflict` | 開啟與關閉 switch 同時為 `on` |
| `unavailable` | 任一底層 switch 不可用 |

`position_confidence`：

- `calibrated`：已完整抵達估算端點；
- `estimated`：從已知位置依時間積分；
- `unknown`：尚無可靠起始位置，完整運轉一次即可校正。

## 舊版 Entity 顯示模式

將 `entity_mode` 設為 `position_entity` 時，仍可使用 v1 設定：

```yaml
type: custom:uninus-greenhouse-rollup-card
faces:
  - key: east
    name: 東側
    entity_mode: position_entity
    entity: input_number.up_lift_position_e
    motion_entity: binary_sensor.rollup_e_moving
    max_entity: input_number.rollup_e_maximum
    max_value: 120
```

舊模式只顯示狀態，不會取得 Integration 的位置保存、互鎖與開停關控制。

## 安全說明

- Integration 是無位置回授的樂觀估算器，不可取代硬體限位、馬達保護或緊急停止裝置。
- 若簾布遭卡住、馬達斷電或機構被人工移動，估算位置可能與實際位置不同；請完整開啟或關閉一次重新校正。
- 兩個方向的底層硬體仍應具有電氣互鎖；軟體互鎖不能取代硬體安全設計。

## 開發

```bash
npm install
npm test
npm run build
python -m unittest discover -s tests_python -v
npm run check
```

建置會產生兩份相同的前端 bundle：

```text
uninus-greenhouse-rollup-card.js
custom_components/uninus_greenhouse_rollup/www/uninus-greenhouse-rollup-card.js
```

CI 會執行 JavaScript 測試、Python 狀態估算／Integration contract 測試、bundle 建置與版本一致性檢查。

## License

MIT
