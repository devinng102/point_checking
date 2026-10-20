# 特殊及待解決情況

本文件記錄已知案例、處理決策及未解決限制。Excel 的 `Remark` 由使用者人工填寫，
`Review` 由使用者填寫覆核結論及修改背景色。本文件不會自動產生人工記錄，
也不會作為 checking 規則或例外清單。
以下 source 差異來自先前提供的結果及本地 schema snapshot，並非本次重新查詢 UAT。

## 案例記錄


| 編號   | 完整 Point Name／情況                                           | 狀態                                   | 說明及後續處理                                                                                                                                                                          |
| ------ | --------------------------------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SC-001 | `APB-CHWP-01-S`                                                 | Source 差異已確認；不改 matching logic | Appendix B 的`"iBMS Parameters"` 是 `"On/Off Status"`，schema key 是 `"Off/On Status"`。依 exact key 規則為 T/F、unmatched；須統一 source 後重新 checking，不新增自動別名。             |
| SC-002 | `APB-GEN-01-BATV`                                               | 待確認 source 修正                     | Appendix B 的`"Battery Voltage "` 有尾隨空格，schema key 是 `"Battery Voltage"`。依 exact key 規則為 T/F、unmatched；不自動 trim parameter key，以免掩蓋 source 差異。                  |
| SC-003 | `APB-ACC-03-RWT`                                                | Checking logic 已修正                  | `APB-ACC-03` 群組存在，不代表 RWT point 存在。Appendix=F 時需在 derived group 下比對完整 Point Name；此已知案例應為 F/F、matched。                                                      |
| SC-004 | `APB-4F-SVRRM-OUTD-TFALM`                                       | 方案二已實作；候選關聯待人工確認       | 無 Equipment Code 的 PV／TFALM 記錄不足以證明與 SVRRM 相關。若缺少候選 System／MISC／同名群組，Appendix 留空；完整 Point Name 掃描若為 F，仍為黃色 review，而不是 T/F 紅色或 F/F 綠色。 |
| SC-005 | 合法 MISC 的 System／MISC／整個群組缺失                         | 待獨立對應資料                         | 無法單靠 schema 區分「合法資料被刪除」與「候選不相關」。方案二要求黃色覆核；未新增推測式 System 對應。                                                                                  |
| SC-006 | MISC 群組被放錯 System，但 parameter／point 恰好匹配            | 已知限制，待獨立對應資料               | 現行 schema 路徑檢查可能仍為 T/T，不能獨立驗證分類正確性。需要 schema 以外的可信設備／System 對應才能完整解決。                                                                         |
| SC-007 | Function Code 去掉 1–2 字元後才匹配，但 suffix 不是 ASCII 數字 | 已實作；需人工覆核                     | 例如`SWT` 若只能拆成 `S` + `WT`，保留候選檢查結果，但標黃色。若原始 `SWT` 已匹配則不拆，不能把所有 SWT 都視為異常。                                                                     |
| SC-008 | 多個不同 System／Equipment／`"iBMS Parameters"` 映射            | 已實作；需人工覆核                     | 保留候選，標藍，不任選第一筆；MISC 只計已暫接受關聯的映射。藍色優先於黃色，但兩種覆核原因都保留。                                                                                       |
| SC-009 | Building "FLCB" in excel = "FLC" in MongoDB | 已實作 |標綠

詳細 MISC 決策原因見 [MISC_FALLBACK_DECISION.md](MISC_FALLBACK_DECISION.md)。
「已修正」描述程式規則，不代表已修正 MongoDB source 或重產所有舊 Excel。

## 人工 Remark 範例

按以下格式自行填入 Excel 的 `Remark`，兩側依序表示 Appendix B 與 schema：

```text
iBMS Parameters: "On/Off Status" vs "Off/On Status"
iBMS Parameters: "Battery Voltage " vs "Battery Voltage"
MISC relevance: PV candidate; System/MISC/group not confirmed
```

使用引號保留空格差異。備註只記錄人工觀察，不會修改 T/F、顏色或候選選擇。
即使後續 source 或 logic 已修正，舊備註仍會保留，須由使用者更新或刪除。

## 重新導入備註

1. 在本次產生的 Excel `Remark` 欄填寫備註，在 `Review` 欄填寫覆核結論及修改
   背景色，並儲存、保留完整舊檔。只修改 Review 顏色、不填文字也可以。
2. 使用原始 point list 重新 checking，透過 `--remarks-from` 指定含人工記錄的舊檔。
3. 新檔以 **`Building & Block Code` + 完整 `Point Name`** exact 配對，與列號、
   worksheet 名稱、舊 T/F 或 derived code 無關；不自動 trim 或模糊匹配。

```powershell
python export_checking_results.py .\point_name_16-9-2026_v1.csv --remarks-from .\point_name_checked_v3.xlsx -o .\point_name_checked_v4.xlsx
```

沒找到對應記錄的舊備註會在 stderr 提示，仍保留在舊檔；point 改名不會自動轉移備註。
同一 key 有相同備註可重複；不同備註會報錯，不任選第一筆或拼接文字。
若輸入已有 `Remark`，沿用該欄、不新增重複欄；已有不同文字時也會報錯，不覆寫。
只允許人工文字；導入檔的非文字備註或公式會報錯。

## Review 顏色保留規則

- 新的 `Review` 欄預設空白、無自動背景色；原有 Review 欄沿用，不新增重複欄。
- `--remarks-from` 會同時導入 Remark 文字及 Review 文字／直接儲存格背景色。
  舊檔只有 Remark 也可以使用；CSV 沒有 Excel 背景色，只能保留文字。
- Checking 欄位的結果及顏色照最新 logic 重算，不複製舊的自動顏色。
  直接改整行或 checking 欄位的顏色，不會作為新的人工覆核顏色導入。
- 同 key 的不同 Review 文字或背景色會報錯；已有不同人工覆核也不會被覆寫。
  未匹配到新記錄的 Review 會提示，仍保留在舊檔。
- 只複製 Review 的文字及直接 fill 定義，不導入條件格式規則或其他儲存格格式。
  Theme 顏色依新檔 theme 顯示。
- 保留下來的是上一次覆核，即使新結果已改變也不自動清除；應人工重新確認。
