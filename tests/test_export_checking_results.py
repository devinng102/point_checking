import argparse
import contextlib
import csv
import io
import sys
import tempfile
import unittest
from copy import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from pymongo.errors import OperationFailure

from checking_logic import (
    BUILDING_COLUMN, EQUIPMENT_COLUMN, POINT_COLUMN, CheckingError, PointChecker,
)
from export_checking_results import (
    RESULT_COLORS,
    RESULT_COLUMNS,
    MongoSchemaSource,
    check_workbook,
    main,
    read_workbook,
    save_workbook,
    write_text,
)


HEADERS = [
    BUILDING_COLUMN, EQUIPMENT_COLUMN, POINT_COLUMN,
    "Function or Status Code", "point name (without function code)", "Comment",
]
APPENDIX = [{
    "Function or Status Code": "S",
    "Equipment Code": "CHR/ACC/WCC",
    "System": "HVAC/W",
    "Equipment": "Chiller",
    "iBMS Parameters": "Off/On Status",
}]
SCHEMA = [{
    "HVAC/W": {"Chiller": {"APB-ACC-04": {
        "Off/On Status": {"point_name": "APB-ACC-04-S"}
    }}}
}]


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.reads = 0

    def find(self):
        self.reads += 1
        return iter(self.documents)


class FakeDatabase:
    def __init__(self, collections, error=None):
        self.collections = collections
        self.error = error

    def list_collection_names(self, filter):
        if self.error:
            raise self.error
        return list(self.collections)

    def __getitem__(self, name):
        return self.collections[name]


class FakeClient:
    def __init__(self, buildings=None):
        self.databases = {
            "MASTER": FakeDatabase({"appendix_b": FakeCollection(APPENDIX)}),
            "APB": FakeDatabase({"enm_semantic_schema": FakeCollection(SCHEMA)}),
        }
        if buildings:
            self.databases.update(buildings)
        self.closed = False
        self.admin = SimpleNamespace(command=lambda name: None)

    def __getitem__(self, name):
        return self.databases.get(name, FakeDatabase({}))

    def close(self):
        self.closed = True


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.client = FakeClient()
        data = MongoSchemaSource(self.client)
        self.checker = PointChecker(data.get_appendix(), data)

    def tearDown(self):
        self.temporary.cleanup()

    def workbook(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(HEADERS)
        sheet.append(["APB", "ACC", "APB-ACC-04-S", "WRONG", "WRONG", "001"])
        return workbook

    def test_preserves_original_values_styles_and_other_sheets(self):
        workbook = self.workbook()
        sheet = workbook.active
        sheet["C2"].fill = PatternFill("solid", fgColor="123456")
        notes = workbook.create_sheet("Notes")
        notes.append(["Untouched", "=1+2"])
        source = self.directory / "source.xlsx"
        workbook.save(source)
        workbook.close()

        workbook, cached = read_workbook(source)
        summary = check_workbook(workbook, self.checker, cached)
        output = self.directory / "checked.xlsx"
        save_workbook(workbook, output)
        workbook.close()
        cached.close()

        actual = load_workbook(output)
        original = load_workbook(source)
        for title in original.sheetnames:
            for rows in original[title].iter_rows():
                for cell in rows:
                    target = actual[title][cell.coordinate]
                    self.assertEqual(target.value, cell.value)
                    self.assertEqual(target.data_type, cell.data_type)
                    self.assertEqual(copy(target.fill), copy(cell.fill))
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(actual.active["G2"].value, "T")
        self.assertEqual(actual.active["H2"].value, "T")
        self.assertEqual(actual.active["I2"].value, "matched")
        self.assertEqual(actual.active["J2"].value, "S")
        self.assertEqual(actual.active["I2"].fill.fgColor.rgb[-6:], "D5E8D4")
        actual.close()
        original.close()

    def test_csv_text_preserves_leading_zeroes_and_literal_formulas(self):
        source = self.directory / "source.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerow([
                "APB", "ACC", "APB-ACC-04-S", "WRONG", "WRONG", "=1+2"
            ])
            writer.writerow([
                "APB", "ACC", "APB-ACC-04-XYZ", "WRONG", "WRONG", "001"
            ])
        workbook, cached = read_workbook(source)
        self.assertIsNone(cached)
        check_workbook(workbook, self.checker)
        output = self.directory / "checked.xlsx"
        save_workbook(workbook, output)
        workbook.close()
        actual = load_workbook(output)
        self.assertEqual(actual.active["F2"].value, "=1+2")
        self.assertEqual(actual.active["F2"].data_type, "s")
        self.assertEqual(actual.active["F3"].value, "001")
        self.assertEqual(actual.active["D2"].value, "WRONG")
        self.assertEqual(actual.active["E2"].value, "WRONG")
        actual.close()

    def test_all_four_result_backgrounds(self):
        records = APPENDIX + [{
            **APPENDIX[0], "Function or Status Code": "MULTI",
        }, {
            **APPENDIX[0], "Function or Status Code": "MULTI",
            "iBMS Parameters": "Other",
        }]
        data = MongoSchemaSource(self.client)
        checker = PointChecker(records, data)
        workbook = self.workbook()
        sheet = workbook.active
        sheet.append(["APB", "ACC", "APB-ACC-04-XYZ"])
        sheet.append(["APB", "ACC", "APB-ACC-04-SWT"])
        sheet.append(["APB", "ACC", "APB-ACC-04-MULTI"])
        summary = check_workbook(workbook, checker)
        self.assertEqual(dict(summary), {
            "matched": 1, "unmatched": 1, "review": 1, "multiple mappings": 1,
        })
        for row_number, status in enumerate(RESULT_COLORS, start=2):
            self.assertEqual(sheet.cell(row_number, 9).value, status)
            for column in range(7, 7 + len(RESULT_COLUMNS)):
                self.assertEqual(
                    sheet.cell(row_number, column).fill.fgColor.rgb[-6:],
                    RESULT_COLORS[status],
                )
        workbook.close()

    def test_existing_result_headers_are_not_overwritten(self):
        workbook = self.workbook()
        sheet = workbook.active
        sheet["G1"] = "Appendix_b"
        sheet["G2"] = "ORIGINAL"
        check_workbook(workbook, self.checker)
        self.assertEqual(sheet["G2"].value, "ORIGINAL")
        self.assertEqual(sheet["H1"].value, "Appendix_b (checking 2)")
        self.assertEqual(sheet["H2"].value, "T")
        workbook.close()

    def test_multiple_data_sheets_and_blank_rows(self):
        workbook = self.workbook()
        second = workbook.create_sheet("Second")
        second.append(HEADERS)
        second.append([None] * len(HEADERS))
        second.append(["APB", "ACC", "APB-ACC-04-S"])
        summary = check_workbook(workbook, self.checker)
        self.assertEqual(sum(summary.values()), 2)
        self.assertIsNone(second["G2"].value)
        self.assertEqual(second["G3"].value, "T")
        workbook.close()

    def test_blank_csv_rows_are_not_checked(self):
        source = self.directory / "source.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerow([""] * len(HEADERS))
            writer.writerow(["APB", "ACC", "APB-ACC-04-S"])
        workbook, _ = read_workbook(source)
        summary = check_workbook(workbook, self.checker)
        self.assertEqual(sum(summary.values()), 1)
        self.assertIsNone(workbook.active["G2"].value)
        self.assertEqual(workbook.active["G3"].value, "T")
        workbook.close()

    def test_input_formula_without_cache_is_yellow_and_formula_preserved(self):
        workbook = self.workbook()
        workbook.active["C2"] = '="APB-ACC-04-S"'
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            summary = check_workbook(workbook, self.checker)
        self.assertEqual(summary["review"], 1)
        self.assertEqual(workbook.active["C2"].value, '="APB-ACC-04-S"')
        self.assertEqual(workbook.active["G2"].value, "")
        self.assertEqual(workbook.active["H2"].value, "")
        self.assertIn("without a cached value", errors.getvalue())
        workbook.close()

    def test_input_formula_uses_cache_without_changing_formula(self):
        workbook = self.workbook()
        workbook.active["C2"] = '="APB-ACC-04-S"'
        cached = self.workbook()
        summary = check_workbook(workbook, self.checker, cached)
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(workbook.active["C2"].value, '="APB-ACC-04-S"')
        workbook.close()
        cached.close()

    def test_missing_schema_collection_is_yellow_with_blank_schema(self):
        workbook = self.workbook()
        workbook.active["A2"] = "NONEXISTENT"
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            summary = check_workbook(workbook, self.checker)
        self.assertEqual(summary["review"], 1)
        self.assertEqual(workbook.active["G2"].value, "T")
        self.assertEqual(workbook.active["H2"].value, "")
        self.assertIn("does not exist", errors.getvalue())
        workbook.close()

    def test_schema_reads_and_failures_are_cached_per_building(self):
        source = MongoSchemaSource(self.client)
        source.get_schema("APB")
        source.get_schema("APB")
        collection = self.client.databases["APB"].collections["enm_semantic_schema"]
        self.assertEqual(collection.reads, 1)
        for _ in range(2):
            with self.assertRaises(CheckingError):
                source.get_schema("MISSING")
        self.assertIsInstance(source._cache["MISSING"], CheckingError)

    def test_mongo_read_failure_has_context(self):
        client = FakeClient({"APB": FakeDatabase({}, OperationFailure("denied"))})
        with self.assertRaisesRegex(CheckingError, "APB.enm_semantic_schema"):
            MongoSchemaSource(client).get_schema("APB")

    def test_missing_and_duplicate_required_headers_fail(self):
        workbook = Workbook()
        workbook.active.append(["Point Name"])
        with self.assertRaisesRegex(ValueError, "No worksheet"):
            check_workbook(workbook, self.checker)
        workbook.close()
        workbook = self.workbook()
        workbook.active["G1"] = POINT_COLUMN
        with self.assertRaisesRegex(ValueError, "duplicate required header"):
            check_workbook(workbook, self.checker)
        workbook.close()

    def test_unrepresentable_text_is_not_silently_truncated(self):
        workbook = Workbook()
        for text in ("X" * 32_768, "bad\x00value"):
            with self.subTest(text_length=len(text)):
                with self.assertRaisesRegex(ValueError, "without changing"):
                    write_text(workbook.active["A1"], text)
        workbook.close()

    def test_existing_output_is_never_overwritten(self):
        workbook = self.workbook()
        output = self.directory / "checked.xlsx"
        output.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            save_workbook(workbook, output)
        self.assertEqual(output.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [output])
        workbook.close()

    def test_failed_save_cleans_temporary_file(self):
        workbook = self.workbook()
        output = self.directory / "checked.xlsx"
        with patch.object(workbook, "save", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                save_workbook(workbook, output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.directory.iterdir()), [])
        workbook.close()

    def test_output_created_during_save_is_never_overwritten(self):
        workbook = self.workbook()
        output = self.directory / "checked.xlsx"
        real_save = workbook.save

        def create_competing_file(path):
            real_save(path)
            output.write_bytes(b"other writer")

        with patch.object(workbook, "save", side_effect=create_competing_file):
            with self.assertRaises(FileExistsError):
                save_workbook(workbook, output)
        self.assertEqual(output.read_bytes(), b"other writer")
        self.assertEqual(list(self.directory.iterdir()), [output])
        workbook.close()

    def test_cli_exports_and_closes_client(self):
        source = self.directory / "source.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerow(["APB", "ACC", "APB-ACC-04-S", "WRONG", "WRONG", "001"])
        output = self.directory / "checked.xlsx"
        with (
            patch("export_checking_results.parse_args", return_value=argparse.Namespace(
                input_file=source, output=output,
            )),
            patch.dict(sys.modules, {"mongodb_connect": SimpleNamespace(DB=self.client)}),
            contextlib.redirect_stdout(io.StringIO()) as messages,
        ):
            self.assertEqual(main(), 0)
        self.assertTrue(self.client.closed)
        self.assertTrue(output.exists())
        self.assertIn("Exported 1 checked rows", messages.getvalue())
        actual = load_workbook(output)
        self.assertEqual(actual.active["I2"].value, "matched")
        actual.close()

    def test_cli_rejects_in_place_output(self):
        source = self.directory / "source.xlsx"
        source.write_bytes(b"original")
        with (
            patch("export_checking_results.parse_args", return_value=argparse.Namespace(
                input_file=source, output=source,
            )),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(), 1)
        self.assertEqual(source.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
