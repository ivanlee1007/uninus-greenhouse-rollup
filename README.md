# UNiNUS Greenhouse Cover Actuator

專為 Home Assistant 舊版溫室雙向智慧開關設計的 Integration。它會將兩個互斥 `switch` 安全包裝成具有位置估算、恢復與方向互鎖能力的標準 `cover`，並支援捲揚、天窗與遮陽簾三種裝置語意。

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/) [![CI](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml/badge.svg)](https://github.com/ivanlee1007/uninus-greenhouse-rollup/actions/workflows/ci.yml)

## 適用硬體

### 舊版雙 Switch Cover Adapter

底層 switch 的 `on` 代表智慧開關仍在執行計時，不保證馬達仍在轉。馬達可能已碰到硬體極限而停止，switch 稍後才更新為 `off`。因此：

- Integration 從上次保存位置、方向、經過時間及完整行程秒數估算位置。
- 中途將方向 switch 關閉時，位置會停在當下估算值並保存。
- 未啟用自動斷電時，到達估算 `0%`／`100%` 後停止顯示運動，即使底層 switch 仍在計時。
- 可明確啟用「行程結束後自動關閉兩個方向 Switch」，由 Integration 在行程時間到達後執行斷電。
- 完整跑完一次全開或全關行程即可校正端點。
- 位置會由 Home Assistant `RestoreEntity` 保存；重新整理卡片或更換瀏覽器不會遺失。
- 沒有實體位置感測器，因此 UI 一律明確標示「估算位置」與可信度。

位置定義：`0%` 為全關，`100%` 為全開。建立或調整 Config Entry 時可選擇裝置類型：

- **捲揚（rollup）**：Home Assistant device class 為 `awning`。
- **天窗（skylight）**：Home Assistant device class 為 `window`。
- **遮陽簾（shade）**：Home Assistant device class 為 `shade`；遵循 Cover 標準語意，**開啟 = 收回**、**關閉 = 展開**。因此「開啟 Switch」必須接到收回方向，「關閉 Switch」必須接到展開方向；`100%` 是完全收回，`0%` 是完全展開。

## 特色

- 將一組開啟 switch 與關閉 switch 包裝成標準 Home Assistant `cover` entity。
- 開啟／關閉前先關閉兩個方向、等待可調整的安全間隔、再次確認兩方向關閉，再啟動單一方向；安全間隔期間的停止命令會取消延遲啟動。
- 支援 `cover.open_cover`、`cover.stop_cover`、`cover.close_cover`、`cover.set_cover_position`（時間估算目標）。
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

## 新增與管理 Cover 致動器

1. 前往「**設定 → 裝置與服務 → 整合**」。
2. 選擇「新增整合」，搜尋 `UNiNUS Greenhouse Rollup`。
3. 每一個舊版實體致動器建立一個 Config Entry，設定：

- 名稱，例如「東側捲揚」、「屋頂天窗」或「南側遮陽簾」；
- Cover 類型：捲揚、天窗或遮陽簾；
- 開啟 Switch（遮陽簾為收回方向）；
- 關閉 Switch（遮陽簾為展開方向）；
- 全開行程秒數；
- 全關行程秒數；
- 方向切換安全間隔秒數（預設 `0.2` 秒）；
- 雙繼電器關閉確認逾時秒數（`off_confirmation_timeout`，預設 `5` 秒，範圍 `0.1–30` 秒）；
- 行程結束後自動關閉兩個方向 Switch（既有設定預設關閉，以維持原行為）。

各個致動器分別重複新增。從整合的 Config Entry 選擇**重新設定**，即可修改類型、來源 Switch、名稱、行程時間與安全間隔；也可從「設定」選項調整類型、行程時間與安全設定。

首次安裝時位置為未知。讓致動器在任一方向完整執行一次設定的行程時間後，Integration 會將端點校正為 `0%` 或 `100%`。

### 時間估算目標位置

```yaml
action: cover.set_cover_position
target:
  entity_id: cover.east_rollup
data:
  position: 35
```

- 目標使用標準**開啟百分比**：整數 `0–100`，`0` 全關、`100` 全開。不是覆蓋百分比；既有 Entity ID、Unique ID、`coverage_position = 100 - current_position` 均不變。
- 起始位置已知時，先停止原方向，再根據當下估算位置計算 `abs(目標 - 起點) / 100 × 該方向完整行程時間`。開啟、關閉分別使用各自的完整行程秒數；安全間隔與關閉確認等待不算入新行程。
- 與目前公開整數位置相同時不重新通電；若正在運動，仍會停止兩方向。
- 起點未知時，要求 `1–99` 會明確拒絕，**不對任何輸出寫入，也不解除既有端點安全計時**。明確要求 `0` 或 `100` 才會執行該方向完整校正時間。校正仍只是時間推估，不是限位回授。
- 每次目標行程都會自動對兩方向執行 `turn_off`，**不受**既有 `auto_stop_at_travel_end` 開關影響；該選項仍只控制原本全開／全關服務。直接操作原始 Switch 不會建立目標計時。
- 停止、反轉、新命令、來源改變與卸載會取消舊目標計時；重新載入或啟動只先關閉兩方向，不恢復未完成目標。來源在目標行程中遺失時會嘗試安全停止，但斷線時不能保證實際斷電。
- `target_position` 是此行程要求的目標，不代表實際位置。`target_operation` 為 `idle`、`running`、`timer_elapsed` 或 `error`（定時停止服務失敗）；`timer_elapsed` 只表示時間預算已到且已送出關閉服務，不表示馬達抵達目標或已讀回斷電。停止或被新命令取代後目標清除；不從 RestoreEntity 恢復目標。
- `position_is_estimated` 永遠為 `true`，`physical_arrival_confirmed` 永遠為 `false`；`current_position` 仍由原本無限位時間估算器產生，不會直接把要求值當成已抵達位置。

### 確認雙繼電器關閉後才啟動

每次 Cover 啟動方向前，都先發送兩個 `turn_off`、等待方向切換安全間隔，再檢查**兩個來源狀態都為 `off`**；服務成功回覆不等於關閉確認。支援延遲更新的非同步狀態讀回，最長等待 `off_confirmation_timeout`，逾時明確報錯且不發送任何 `turn_on`。缺少狀態、`unknown`、`unavailable` 或其他非 `off` 狀態均不能放行。等待中的停止／反向新命令會阻止舊命令稍後重新啟動。

舊設定採向後相容的新增欄位預設：缺少逾時欄位即使用 `5` 秒，不重建 Entry、不改 ID、不改原本 auto-stop 開關；舊版 Entry 的既有版本遷移保留，設定／重新設定表單可另行儲存逾時值。此變更刻意讓未確認關閉的舊設備拒絕啟動，不能關閉此安全檢查。

EMOS 裝置請使用 `relay0` 對應的**實際輸出**；`auto0`／`auto1` 是虛擬定時序列 Switch，不應把序列的計時狀態當成實際輸出回授。本 Integration 不改韌體、不自動移除這些虛擬 Switch；遷移前需自行停用會與 Cover 競爭實際輸出的舊 Automation。

### 行程結束自動斷電

啟用「**行程結束後自動關閉兩個方向 Switch**」後，透過這個 Cover 執行全開或全關時，Integration 會從成功啟動方向 Switch 起計時：

- 全開使用「全開行程秒數」，全關使用「全關行程秒數」；
- 時間到達後，對開啟與關閉 Switch **都**執行 `switch.turn_off`，避免任一方向殘留通電；
- 中途按停止、改變方向、重新載入或卸載 Integration 時，舊的自動斷電計時會取消，不會誤停後續的新方向命令；
- 若第一個 Switch 關閉失敗，仍會嘗試關閉第二個並在 Home Assistant 記錄錯誤。

此選項只保護**透過 Integration 產生的 Cover 所啟動**的行程。直接對底層來源 Switch 呼叫 `turn_on` 不會建立 Cover 的行程計時；硬體與 Automation 應統一使用 `cover.open_cover`／`cover.close_cover`／`cover.stop_cover`。

既有 Config Entry 缺少此欄位時一律視為關閉，不會因升級而改變原本的來源 Switch 計時行為。可從 Integration 的「設定」或「重新設定」啟用，儲存後會重新載入該捲揚。

### 不重新載入的即時設定服務

卡片或 Automation 可呼叫 `uninus_greenhouse_rollup.set_auto_stop_at_travel_end`：

```yaml
action: uninus_greenhouse_rollup.set_auto_stop_at_travel_end
data:
  entity_id:
    - cover.east_rollup
    - cover.west_rollup
  enabled: true
```

- `entity_id` 可為單一 `cover.*` 字串或非空清單；重複 ID 只處理一次。請明確提供目標，不支援 `all`、區域／裝置目標或原生 MQTT Cover。
- `enabled` 只接受真正的布林值 `true`／`false`，不接受字串或 `0`／`1`。
- 有使用者的呼叫會檢查每個目標的控制權限；無使用者 Context 的 HA 內部 Automation 可呼叫。
- 僅允許此整合仍持有兩個來源 Switch 的已載入 Cover。Cover 必須可用、兩個 Switch 都確認為 `off`，且沒有執行中／待執行的方向、停止、衝突處理、計時或卸載命令。估算已達 `0%`／`100%` **不代表斷電**，Switch 仍為 `on` 時會拒絕。
- 批次在任何寫入前驗證全部目標；任一目標無效即明確報錯，不修改其他目標。全部驗證後，更新期間持有所有目標的命令鎖，且驗證與取得空閒鎖之間不讓出事件迴圈，避免與新命令競爭。
- 只合併並保存 `auto_stop_at_travel_end` 選項，同步 runtime 與 Cover attribute；**不重新載入、不呼叫繼電器服務、不建立或取消行程計時**。設定從**下一次 Cover 開啟／關閉命令**生效，重新啟動後保留。
- 可要求服務回應：`{"updated": ["cover.east_rollup", "cover.west_rollup"], "enabled": true}`。若驗證後發生非預期保存／發布失敗，錯誤會列出失敗目標與已更新目標；跨 Config Entry 的保存不是磁碟交易，不保證回復先前成功的寫入。Config Entry 使用 HA 標準延遲保存機制，不承諾回應時已完成磁碟 fsync。
- 停用代表不再由 HA 於下一次行程結束時主動斷電，請先確認硬體／Switch 計時保護。既有 Integration「設定」與「重新設定」流程仍維持原本的 reload 行為，可能因卸載安全清理而關閉繼電器；本服務刻意不走該流程。

## 狀態語意

### 同一個 Cover 的開啟與覆蓋百分比

Integration 不會另外建立 Sensor；開啟與覆蓋百分比都在原本同一個 `cover.*` 的 attributes：

- `current_position`：Home Assistant 標準開啟百分比，`0` 為全關、`100` 為全開；既有語意與四捨五入規則不變。
- `coverage_position`：本 Integration 的自訂覆蓋百分比，直接以已對外公開的整數 `current_position` 計算 `100 - current_position`。例如開啟 `25` 時覆蓋 `75`，全關覆蓋 `100`，全開覆蓋 `0`；遮陽簾的覆蓋即展開比例。
- 尚未校正／恢復位置時，`coverage_position` 為 `null`；任一來源 Switch 遺失、`unknown` 或 `unavailable` 而使 Cover 不可用時，也為 `null`，不會把未知位置當成 `0` 再換算成 `100`。
- 不可用時原有 `current_position` 仍可能保留上次估算值，這不代表目前可控制。來源恢復可用後，覆蓋百分比會重新由同一位置推導。
- 覆蓋百分比沒有獨立計時、校正或保存；重新啟動後只由既有恢復的開啟位置重新計算，不讀取舊的 `coverage_position`。位置可信度與估算限制同樣適用。
- 本屬性不改變 Cover 狀態、`is_closed`、開啟／停止／關閉服務、方向 Switch 或行程設定；原生 MQTT Cover 不會由本 Integration 加上此自訂屬性。

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

- `calibrated`：時間模型已建立估算端點，**不是已讀到實體限位**；
- `estimated`：從已知位置依時間積分；
- `unknown`：尚無可靠起始位置，完整運轉一次即可校正。

## 安全說明

- Integration 是無位置回授的樂觀估算器，不可取代硬體限位、馬達保護或緊急停止裝置。
- 若簾布遭卡住、馬達斷電或機構被人工移動，估算位置可能與實際位置不同；請完整開啟或關閉一次重新校正。
- 兩個方向的底層硬體仍應具有電氣互鎖；軟體互鎖不能取代硬體安全設計。
- HA 停機、網路中斷或未觀察到的外部移動會使估算產生不確定性；恢復的數值不是新的實測值。請保留裝置端獨立最大通電時間及硬體限位，HA 計時不能提供硬即時停止或斷線斷電保證。

## 開發

```bash
uv run --with homeassistant==2026.7.2 python -m unittest discover -s tests_python -v
python -m compileall -q custom_components
```

CI 會執行 Python 狀態估算、Integration contract、hassfest 與 HACS validation。

## License

MIT
