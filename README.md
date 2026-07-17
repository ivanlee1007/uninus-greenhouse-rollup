# UNiNUS Greenhouse Rollup

專為 Home Assistant 溫室側簾設計的 **Integration + Lovelace Card**，同時支援兩代 UNiNUS 智慧開關。新版裝置可透過 MQTT Discovery 直接提供標準 `cover`；舊版裝置的兩個互斥 `switch` 則由 Integration 安全包裝成具有位置估算與恢復能力的 `cover`。Card 對兩種來源一律使用標準 Cover services。

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/) [![CI](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml/badge.svg)](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml)

## 兩種硬體模式

### 新版：原生 MQTT Cover

新版智慧開關已在韌體／MQTT 層處理兩個方向，並向 Home Assistant 註冊一個 `cover.*`。Card 直接使用該 Entity；Integration **不會建立代理 Cover**、不會重複估算位置，也不會操作其底層 Relay。位置、運轉方向、availability 與可用控制皆以裝置實際回報為準。

### 舊版：舊版雙 Switch Adapter

底層 switch 的 `on` 代表智慧開關仍在執行計時，不保證馬達仍在轉。馬達可能已碰到硬體極限而停止，switch 稍後才更新為 `off`。因此：

- Integration 從上次保存位置、方向、經過時間及完整行程秒數估算位置。
- 中途將方向 switch 關閉時，位置會停在當下估算值並保存。
- 到達估算 `0%`／`100%` 後停止顯示運動，即使底層 switch 仍在計時。
- 完整跑完一次全開或全關行程即可校正端點。
- 位置會由 Home Assistant `RestoreEntity` 保存；重新整理卡片或更換瀏覽器不會遺失。
- 沒有實體位置感測器，因此 UI 一律明確標示「估算位置」與可信度。

位置定義：`0%` 為全關，`100%` 為全開。

## 特色

- 同一卡片可直接使用新版原生 MQTT Cover，或使用 Integration 從舊版雙 Switch 產生的 Cover。
- 原生 Cover 沒有 `current_position` 時會明確顯示「位置未提供」，不會把 `open` 誤判為 `100%`。
- 依原生 Cover 的 `supported_features` 顯示開啟、停止與關閉按鈕。
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

## 新增與管理捲揚

1. 前往「**設定 → 裝置與服務 → 整合**」。
2. 選擇「新增整合」，搜尋 `UNiNUS Greenhouse Rollup`。
3. 選擇硬體模式。

### 新版：直接使用原生 MQTT Cover

選擇「新版：直接使用原生 MQTT Cover」並完成一次設定，以確保只使用新版裝置的環境也會載入內建 Card 資源。此模式不要求選擇 Relay，也不產生新的 Cover Entity。之後在 Card 的「標準 Cover Entity」欄位直接選擇 MQTT 提供的 `cover.*`。

同一個 Home Assistant 執行個體只需要一個原生 Cover 支援 Config Entry。

### 舊版：將兩個 Switch 組合成 Cover

每一個舊版實體捲揚建立一個 Config Entry，設定：

- 名稱，例如「東側捲揚」；
- 開啟／上捲 Switch；
- 關閉／下捲 Switch；
- 全開行程秒數；
- 全關行程秒數；
- 方向切換安全間隔秒數（預設 `0.2` 秒）。

東、南、西、北分別重複新增。從整合的 Config Entry 選擇**重新設定**，即可修改來源 Switch、名稱、行程時間與安全間隔；Card 只選擇此 Entry 產生的 `cover.*`，不會直接操作底層 Switch。

首次安裝時位置為未知。讓捲揚在任一方向完整執行一次設定的行程時間後，Integration 會將端點校正為 `0%` 或 `100%`。

## 安裝卡片資源

Integration 會提供內建前端檔案。於「設定 → 儀表板 → 右上角選單 → 資源」新增 JavaScript Module：

```text
/uninus-greenhouse-rollup/uninus-greenhouse-rollup-card.js?v=2.2.0
```

之後重新整理瀏覽器。新增卡片時可搜尋 **UNiNUS Greenhouse Rollup Card**，並使用**視覺化設定**。

## Integration 卡片設定

```yaml
type: custom:uninus-greenhouse-rollup-card
title: 溫室側簾捲揚
items_per_row: 4
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

每一面設定 `cover_entity` 後，兩種 Cover 都使用相同的開／停／關服務。舊版 Integration Cover 另外顯示：

- 估算位置與端點校正狀態；
- 實際位置積分中的開啟／關閉動畫；
- 「開啟命令中」或「關閉命令中」；
- 到端點後「已全開／已全關」，並另外顯示底層 switch 尚在計時；
- 開啟、停止、關閉三個控制按鈕。

原生 MQTT Cover 則顯示裝置回報的 `current_position` 與運轉狀態；沒有位置回報時明確標示「位置未提供」，並依 `supported_features` 隱藏裝置不支援的控制。

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
npm run test:python
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
