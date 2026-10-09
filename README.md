# Point checking

Check an Excel/CSV point list against MongoDB Appendix B and a building's
`enm_semantic_schema`, then export a **new** workbook with additional result
columns. MongoDB is read-only for this command.

## Setup and usage

```powershell
python -m pip install -r requirements.txt
$env:MONGODB_URI = "<your UAT ASL MongoDB connection URI>"
python export_checking_results.py .\point_name_16-9-2026_v1.csv
python export_checking_results.py .\points.xlsx -o .\points_checked.xlsx
```

Alternatively, put `MONGODB_URI` in the ignored `.env` beside
`mongodb_connect.py`. Do not commit connection credentials.

With no arguments the command checks `point_name_16-9-2026_v1.csv`. Default
output is `<input-name>_checked.xlsx` (`.xlsm` for macro-enabled inputs).
Existing output files and the input are never overwritten.

The command accepts UTF-8 CSV, XLSX and XLSM. Each data worksheet must have
these exact headers in row 1:

- `Building & Block Code`
- `Equipment Code / System / Room Code`
- `Point Name`

Every worksheet containing all three headers is checked; other worksheets are
preserved. Blank equipment-code **cells** are allowed for MISC matching.
CSV values are written as text, preserving leading zeroes and treating strings
beginning with `=` as literal text, not formulas. Excel source cells, formulas
and their existing formatting are retained; only new result columns are colored.
Formula-based checking inputs need cached values from recalculation in Excel.
Unavailable formula values produce yellow review results, not invented values.

## Checking rules

1. `Point Name` is authoritative. Split at its **last** hyphen to derive the
   Function Code and point base name. Do not read the original
   `Function or Status Code` or `point name (without function code)` columns
   for checking, and do not overwrite them. Missing floor/equipment-ID segments
   and hyphens inside building codes do not affect this split.
2. Read `MASTER.appendix_b`. Function matching is exact first, then an entire
   slash-separated token. This applies to **all** codes, including codes with
   regex metacharacters; it is equivalent to matching the escaped code with
   `(^|/)code(/|$)`, not an arbitrary substring.
3. If the Function Code is absent, strip one trailing character, then two.
   Stop at the first base-code match. A 1-2 digit ASCII suffix is accepted as a
   Device ID. Other suffixes set a yellow flag but still undergo candidate
   checking. Two unsuccessful trims set Appendix=False and use the normal
   schema-scan/color rules; they are not automatically errors or red results.
4. Match Appendix B `Equipment Code` against the CSV equipment code: exact
   first, then literal substring RegExp behavior. At each stage, match
   `Function or Status Code` exactly first, then as a slash token. After exact
   Equipment Code matching, query the mapped **Equipment name** and Function
   Code, as described in `flow.drawio`.
5. If Equipment Code matching fails, try Appendix records whose
   `Equipment Code` is missing, null or blank. Use their `System` and
   `iBMS Parameters`, with the schema equipment key fixed to `MISC`.
6. Appendix=True: check all documents at
   `System -> Equipment (or MISC) -> derived point base name -> iBMS Parameters`,
   requiring `point_name` to equal the original complete `Point Name`.
   **Do not append Device ID to `iBMS Parameters`.**
7. Appendix=False: scan all documents in the target building collection for
   the derived point base name as a `System -> Equipment/MISC -> group` key.
   Do not merely search for the name anywhere in a value.
8. Distinct `System / Equipment / iBMS Parameters` mappings set a blue flag.
   Duplicate records with the same mapping do not. Retain all candidates;
   never arbitrarily choose the first one. Schema T/F is reported if all
   candidate checks agree; if they disagree or are unresolved, it is blank
   and each candidate's result is retained.

The target database is the CSV's `Building & Block Code` **as given**, not a
guessed alias. For example, `FLCB` is not automatically mapped to `FLC`.
Missing collections, permissions/connection failures, malformed matched
metadata and parsing errors produce yellow review with a reason. Errors are
not converted to False. Appendix-loading failure aborts the command.

## Added Excel columns

| Column | Meaning |
|---|---|
| `Appendix_b` | `T` for a successful mapping, `F` for no mapping, blank if unknown |
| `enm_semantic_schema` | `T`/`F` for the appropriate path check or group scan; blank if unknown |
| `Test result` | `matched`, `unmatched`, `review`, or `multiple mappings` |
| `Derived Function Code` | Final segment of the original Point Name |
| `Derived Point Base Name` | Point Name with its final hyphen/segment removed |
| `Base Function Code` | Code used in Appendix checking, after any Device ID split |
| `Device ID` | Candidate suffix; does not change the schema parameter key |
| `Appendix Match Method` | Exact Equipment Code, RegExp, MISC, or unmatched |
| `Checking Reasons` | Checking decisions and any review/error reasons |
| `Candidate Mappings` | JSON containing mapped fields and per-candidate schema results |

If an original column already has one of these names, a uniquely suffixed result
column is appended instead of replacing it. Original columns and values remain
unchanged. Added result cells have the row's result background:

| Priority | Condition | Result / background |
|---|---|---|
| 1 | Multiple different mappings | `multiple mappings` / blue |
| 2 | Non-numeric Device ID candidate or checking error | `review` / yellow |
| 3 | Appendix/schema both T or both F | `matched` / green |
| 3 | Appendix/schema T/F or F/T | `unmatched` / red |

Blue overrides yellow, but all reasons are retained. The command prints counts
for each result category and reports checking errors to stderr. It exits
nonzero if input loading, Appendix loading, or output saving fails; row-level
review conditions are exported rather than silently discarded.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use in-memory MongoDB fixtures and a local APB schema snapshot; they do
not connect to or modify UAT.
