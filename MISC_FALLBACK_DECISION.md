# MISC 後備匹配決策：無法確認時要求人工覆核

決策日期：2026-10-13

狀態：已採用方案二，並已實作於 `checking_logic.py` 及 `flow.drawio`。
Excel 沿用既有空白未知值及 review 黃色輸出，不覆寫原始資料。

## 背景

Appendix B 的 MISC 後備匹配會查找 `"Equipment Code"` 缺失、null 或空白，
且 `"Function or Status Code"` 相符的記錄。這些記錄沒有可直接對應輸入
Equipment Code 的依據，因此找到相同 Function Code 不代表候選與本次設備相關。

例如 `APB-4F-SVRRM-OUTD-TFALM` 可找到 System 為 `"PV"` 的候選，
但僅憑 `TFALM` 相符，不能證明該候選與 SVRRM 設備有關。

## 決策

在沒有獨立、可信的設備／System 對應時，不把缺少 schema 路徑當成候選
「明確不相關」的證據。無法確認 MISC 候選關聯時，使用未知結果及黃色人工覆核，
而不是直接把 `Appendix_b` 設為 `F`。

本決策只針對 MISC 後備匹配；不改變 exact Equipment Code、RegExp Equipment Code、
Function Code、Device ID 的既有匹配規則。

### MISC 判斷規則

以輸入的 Building & Block Code 選擇目標 schema，並檢查所有文件中的：

```text
候選 "System" → "MISC" → Derived Point Base Name
```

| 情況 | 判斷與輸出 |
|---|---|
| 找不到任何 MISC Function Code 候選 | 沒有映射，`Appendix_b=F`；另行掃描完整 Point Name |
| 候選的 System／MISC／同名群組存在 | 暫接受候選關聯，按映射路徑檢查 `"iBMS Parameters"` 及完整 Point Name |
| 候選缺少 System、MISC 或同名群組 | 關聯無法確認；不能僅因此排除候選或記 `Appendix_b=F` |
| 有獨立可信證據證明候選不相關 | 可排除該候選；所有候選均被明確排除後，才記 `Appendix_b=F` |
| 查詢失敗、collection 不存在或相關節點結構異常 | 查詢／資料錯誤，要求人工覆核；不能解讀成不存在 |

有候選但關聯無法確認時：

- `Appendix_b` 留空，表示未知，不寫入字串 `F`。
- 在 schema 可正常讀取時，另行掃描完整原始 Point Name，輸出該掃描的 T/F；
  群組名稱存在本身不等於完整 point 存在。
- 若 schema 檢查也無法完成，`enm_semantic_schema` 留空。
- `Test result=review`，黃色；未知結果不能進入 F/F 的綠色 equality 判斷。
- 保留候選映射及具體原因，區分缺少 System、MISC、同名群組和查詢錯誤。
  原因須說明 schema 結果來自完整 Point Name 掃描，而非已確認的映射路徑。

關聯已暫接受的候選，若只缺少 `"iBMS Parameters"` 或完整 Point Name，
應維持 `Appendix_b=T`、`enm_semantic_schema=F`，得到紅色 unmatched。
不能根據 point 匹配失敗，反過來把 Appendix 改成 F。

多候選必須保留逐項結果，不能任意選第一筆，也不能默默捨棄關聯未確認的候選。
僅有多筆 Function Code 候選，不足以確認多個相關映射。
已成立的多個不同映射仍按既有規則標藍，藍色優先於黃色，但保留所有未知／錯誤原因；
未確認候選不能被當作已排除或已確認的映射。

當已暫接受與未確認候選並存時，整列 `Appendix_b` 仍留空，schema 結果使用
完整 Point Name 掃描；保留已接受候選的映射路徑結果。
兩個以上已暫接受的不同映射才觸發藍色，其餘未知組合維持黃色。
相關節點檢查有錯誤時，不用另行掃描的結果掩蓋錯誤，schema 留空。

目前沒有新增外部對應或「明確不相關」判斷器；上述外部證據排除規則是未來
取得可信對應後的原則，不代表目前程式能自動排除候選。

## 選擇方案二的原因

### 避免整個群組缺失被誤判為正常

假設 Appendix B 有合法 FS／SS 映射，正確路徑應為：

```text
"FS" → "MISC" → "APB-FAS-01" → "System Status"
```

如果 `APB-FAS-01` 整個群組被誤刪，僅根據 schema 缺失排除 Appendix 候選，
就會得到 F/F、matched、綠色，掩蓋實際資料缺失。

方案二會把候選關聯判為未知。若完整 `APB-FAS-01-SS` 也不存在，
輸出 Appendix 留空、schema=F、黃色 review，不宣稱資料正常。

### 避免把無關候選當成已確認映射

假設 APB 有 `"PV" → "MISC" → "APB-PV-01"`，但沒有
`"PV" → "MISC" → "APB-4F-SVRRM-OUTD"`。
PV／MISC 存在不代表 PV 候選適用於 OUTD，因此要檢查同名群組。
即使同名群組不存在，也只代表目前無法確認關聯，不代表已證明候選無關。

若完整 `APB-4F-SVRRM-OUTD-TFALM` 不存在，方案二預期輸出：

| Appendix_b | enm_semantic_schema | Test result | 原因 |
|---|---|---|---|
| 留空 | F | review，黃色 | 無法確認 PV MISC 候選與此設備的關聯；完整 Point Name 不存在 |

### 不需要立即新增未經確認的 System 對應

方案一需要獨立、可信的設備／System 對應。現階段沒有使用者確認的完整對應，
不應由程式猜測，也不應從待檢查的 schema 自動產生，再用來驗證同一份 schema。
方案二保留不確定性，讓人工覆核取代缺乏證據的布林判斷。

## 已知限制

方案二降低誤標綠／誤認映射的風險，但不是完整的獨立驗證：

- 合法但缺失的群組與真正無關的候選，可能同樣顯示黃色，增加人工覆核量。
- 如果群組被放錯 System，而該位置的 parameter／Point Name 又恰好匹配，
  仍可能得到 T/T。schema 路徑存在不能獨立證明 System 分類正確。
- 沒有外部對應依據時，不能保證自動區分「不相關」和「應存在但缺失」。

後續若建立獨立可信對應，可再採用方案一；不在本次決策中新增對應表或推測規則。

## 實作驗收重點

1. 缺少候選 System、MISC 或同名群組時，不能因完整 point 也不存在而標綠。
2. 同名群組存在，但指定 parameter／完整 point 不匹配時，維持 T/F、紅色。
3. 完整 Point Name 掃描不能被群組名稱存在取代。
4. 查詢失敗或相關節點結構異常不能轉成 F。
5. 多候選保留逐項關聯判斷、匹配結果及原因，不任意選取或丟棄。
6. Excel 保留原始資料；未知 Appendix 使用空白，並保留覆核原因。
