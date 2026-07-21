# UNiNUS Greenhouse Rollup

專為 Home Assistant 舊版溫室側簾智慧開關設計的 Integration。它會將兩個互斥 `switch` 安全包裝成具有位置估算、恢復與方向互鎖能力的標準 `cover`。

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/) [![CI](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml/badge.svg)](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml)

## 適用硬體

### 舊版雙 Switch Adapter

底層 switch 的 `on` 代表智慧開關仍在執行計時，不保證馬達仍在轉。馬達可能已碰到硬體極限而停止，switch 稍後才更新為 `off`。因此：

- Integration 從上次保存位置、方向、經過時間及完整行程秒數估算位置。
- 中途將方向 switch 關閉時，位置會停在當下估算值並保存。
- 未啟用自動斷電時，到達估算 `0%`／`100%` 後停止顯示運動，即使底層 switch 仍在計時。
- 可明確啟用「行程結束後自動關閉兩個方向 Switch」，由 Integration 在行程時間到達後執行斷電。
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
- 與任何使用標準 Cover services 的 Lovelace UI 或 automation 相容。

## HACS 安裝

需求：Home Assistant `2026.7.2` 或更新版本。

1. HACS → Integrations → 右上角選單 → Custom repositories。
2. Repository：`https://github.com/ivanlee1007/uninus-greenhouse-rollup`
3. Type：**Integration**。
4. 安裝 `UNiNUS Greenhouse Rollup`。
5. 重新啟動 Home Assistant。

## 獨立卡片專案

Lovelace 卡片已移至 [ivanlee1007/uninus-greenhouse-rollup-card](https://github.com/ivanlee1007/uninus-greenhouse-rollup-card)，請在 HACS 以 **Dashboard** 類型安裝。HACS 會自動加入卡片資源，不需手動新增 JavaScript Module。

若升級自 `v2.2.2` 或更早版本，請刪除舊的手動資源：

```text
/uninus-greenhouse-rollup/uninus-greenhouse-rollup-card.js?...
```

新版 MQTT 裝置若已透過 MQTT Discovery 提供標準 `cover.*`，只需安裝獨立卡片，不需要安裝本 Integration。

## 新增與管理捲揚

1. 前往「**設定 → 裝置與服務 → 整合**」。
2. 選擇「新增整合」，搜尋 `UNiNUS Greenhouse Rollup`。
3. 每一個舊版實體捲揚建立一個 Config Entry，設定：

- 名稱，例如「東側捲揚」；
- 開啟／上捲 Switch；
- 關閉／下捲 Switch；
- 全開行程秒數；
- 全關行程秒數；
- 方向切換安全間隔秒數（預設 `0.2` 秒）；
- 行程結束後自動關閉兩個方向 Switch（既有設定預設關閉，以維持原行為）。

東、南、西、北分別重複新增。從整合的 Config Entry 選擇**重新設定**，即可修改來源 Switch、名稱、行程時間與安全間隔。

首次安裝時位置為未知。讓捲揚在任一方向完整執行一次設定的行程時間後，Integration 會將端點校正為 `0%` 或 `100%`。

### 行程結束自動斷電

啟用「**行程結束後自動關閉兩個方向 Switch**」後，透過這個 Cover 執行全開或全關時，Integration 會從成功啟動方向 Switch 起計時：

- 全開使用「全開行程秒數」，全關使用「全關行程秒數」；
- 時間到達後，對開啟與關閉 Switch **都**執行 `switch.turn_off`，避免任一方向殘留通電；
- 中途按停止、改變方向、重新載入或卸載 Integration 時，舊的自動斷電計時會取消，不會誤停後續的新方向命令；
- 若第一個 Switch 關閉失敗，仍會嘗試關閉第二個並在 Home Assistant 記錄錯誤。

此選項只保護**透過 Integration 產生的 Cover 所啟動**的行程。直接對底層來源 Switch 呼叫 `turn_on` 不會建立 Cover 的行程計時；硬體與 Automation 應統一使用 `cover.open_cover`／`cover.close_cover`／`cover.stop_cover`。

既有 Config Entry 缺少此欄位時一律視為關閉，不會因升級而改變原本的來源 Switch 計時行為。可從 Integration 的「設定」或「重新設定」啟用，儲存後會重新載入該捲揚。

## 狀態語意

| `command_state` | 意義 |
|---|---|
| `idle` | 兩個底層 switch 都是 `off` |
| `opening` | 開啟命令中，位置尚未到 100% |
| `closing` | 關閉命令中，位置尚未到 0% |
| `opening_timer` | 已估算全開，但開啟 switch 仍在計時；未啟用自動斷電或直接操作來源 Switch 時可能出現 |
| `closing_timer` | 已估算全關，但關閉 switch 仍在計時；未啟用自動斷電或直接操作來源 Switch 時可能出現 |
| `conflict` | 開啟與關閉 switch 同時為 `on` |
| `unavailable` | 任一底層 switch 不可用 |

`position_confidence`：

- `calibrated`：已完整抵達估算端點；
- `estimated`：從已知位置依時間積分；
- `unknown`：尚無可靠起始位置，完整運轉一次即可校正。

## 安全說明

- Integration 是無位置回授的樂觀估算器，不可取代硬體限位、馬達保護或緊急停止裝置。
- 若簾布遭卡住、馬達斷電或機構被人工移動，估算位置可能與實際位置不同；請完整開啟或關閉一次重新校正。
- 兩個方向的底層硬體仍應具有電氣互鎖；軟體互鎖不能取代硬體安全設計。

## 開發

```bash
uv run --with homeassistant==2026.7.2 python -m unittest discover -s tests_python -v
python -m compileall -q custom_components
```

CI 會執行 Python 狀態估算、Integration contract、hassfest 與 HACS validation。

## License

MIT
