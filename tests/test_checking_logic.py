import json
import unittest
from pathlib import Path

from checking_logic import (
    BUILDING_COLUMN,
    EQUIPMENT_COLUMN,
    POINT_COLUMN,
    CheckingError,
    PointChecker,
    contains_point_base,
    match_function,
)


def appendix(
    function="S", code="CHR/ACC/WCC", system="HVAC/W",
    equipment="Chiller", parameter="Off/On Status",
):
    return {
        "Function or Status Code": function,
        "Equipment Code": code,
        "System": system,
        "Equipment": equipment,
        "iBMS Parameters": parameter,
    }


def row(point="APB-ACC-04-S", code="ACC", building="APB"):
    return {
        BUILDING_COLUMN: building,
        EQUIPMENT_COLUMN: code,
        POINT_COLUMN: point,
        "Function or Status Code": "UNTRUSTED",
        "point name (without function code)": "UNTRUSTED",
    }


def schema(
    point="APB-ACC-04-S", base="APB-ACC-04",
    system="HVAC/W", equipment="Chiller", parameter="Off/On Status",
):
    return {system: {equipment: {base: {parameter: {"point_name": point}}}}}


class MemorySource:
    def __init__(self, documents=None, error=None):
        self.documents = [] if documents is None else documents
        self.error = error
        self.buildings = []

    def get_schema(self, building):
        self.buildings.append(building)
        if self.error is not None:
            raise CheckingError(self.error)
        return self.documents


class FunctionMatchingTests(unittest.TestCase):
    def test_exact_takes_priority_over_tokens(self):
        exact, tokens = appendix("S"), appendix("S/T")
        self.assertEqual(match_function([tokens, exact], "S"), [exact])

    def test_generic_slash_tokens_not_substrings(self):
        records = [appendix("ALPHA/BETA"), appendix("ALPHABET")]
        self.assertEqual(match_function(records, "ALPHA"), records[:1])
        self.assertEqual(match_function(records, "BETA"), records[:1])
        self.assertEqual(match_function(records, "ALPH"), [])

    def test_examples_and_regex_metacharacters(self):
        records = [appendix("FALM/TFALM"), appendix("SWT/SS"), appendix("X+/Y")]
        self.assertEqual(match_function(records, "TFALM"), records[:1])
        self.assertEqual(match_function(records, "FALM"), records[:1])
        self.assertEqual(match_function(records, "S"), [])
        self.assertEqual(match_function(records, "X+"), records[2:])


class CheckingTests(unittest.TestCase):
    def check(self, records=None, documents=None, input_row=None, error=None):
        source = MemorySource(
            [schema()] if documents is None else documents, error
        )
        result = PointChecker(
            [appendix()] if records is None else records, source
        ).check(row() if input_row is None else input_row)
        return result, source

    def test_point_name_is_authoritative_and_row_unchanged(self):
        original = row()
        snapshot = original.copy()
        result, _ = self.check(input_row=original)
        self.assertEqual(original, snapshot)
        self.assertEqual(result.function_code, "S")
        self.assertEqual(result.point_base_name, "APB-ACC-04")
        self.assertTrue(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.match_method, "RegExp Equipment Code")

    def test_exact_equipment_then_mapped_equipment_name_query(self):
        records = [
            appendix(code="ACC"),
            appendix(code="WCC", parameter="Another parameter"),
        ]
        result, _ = self.check(records=records)
        self.assertEqual(result.match_method, "exact Equipment Code")
        self.assertEqual(result.status, "multiple mappings")
        self.assertEqual(len(result.candidate_results), 2)

    def test_function_fallback_within_each_equipment_condition(self):
        records = [
            appendix("FALM", "AHU", equipment="AHU"),
            appendix("FALM/TFALM", "ACC", parameter="Fault Alarm"),
        ]
        result, _ = self.check(
            records=records,
            documents=[schema(point="APB-ACC-04-FALM", parameter="Fault Alarm")],
            input_row=row("APB-ACC-04-FALM"),
        )
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.match_method, "exact Equipment Code")

    def test_one_and_two_digit_device_ids_use_unmodified_parameter_key(self):
        for suffix in ("1", "01", "99"):
            with self.subTest(suffix=suffix):
                point = f"APB-ACC-04-S{suffix}"
                result, _ = self.check(
                    input_row=row(point), documents=[schema(point=point)]
                )
                self.assertEqual(result.base_function_code, "S")
                self.assertEqual(result.device_id, suffix)
                self.assertEqual(result.status, "matched")
                self.assertFalse(result.device_review)

    def test_device_id_is_not_appended_to_parameter(self):
        result, _ = self.check(
            input_row=row("APB-ACC-04-S1"),
            documents=[schema(point="APB-ACC-04-S1", parameter="Off/On Status 1")],
        )
        self.assertTrue(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "unmatched")

    def test_full_code_is_matched_before_device_id_stripping(self):
        result, _ = self.check(
            records=[appendix("CO"), appendix("CO2")],
            documents=[schema(point="APB-ACC-04-CO2")],
            input_row=row("APB-ACC-04-CO2"),
        )
        self.assertEqual(result.device_id, "")
        self.assertEqual(result.base_function_code, "CO2")
        self.assertEqual(result.status, "matched")

    def test_device_candidate_function_also_supports_slash_tokens(self):
        result, _ = self.check(
            records=[appendix("S/T")],
            documents=[schema(point="APB-ACC-04-S1")],
            input_row=row("APB-ACC-04-S1"),
        )
        self.assertEqual(result.status, "matched")

    def test_non_numeric_device_candidate_keeps_results_and_yellow(self):
        point = "APB-ACC-04-SWT"
        result, _ = self.check(
            input_row=row(point), documents=[schema(point=point)]
        )
        self.assertEqual(result.device_id, "WT")
        self.assertTrue(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(result.status, "review")
        self.assertTrue(result.device_review)

    def test_non_ascii_digits_are_not_automatically_accepted(self):
        result, _ = self.check(input_row=row("APB-ACC-04-S\uFF11"))
        self.assertEqual(result.status, "review")

    def test_failed_device_detection_uses_normal_false_false_green(self):
        result, _ = self.check(input_row=row("APB-UNKNOWN-XYZ"), documents=[])
        self.assertFalse(result.appendix)
        self.assertFalse(result.schema)
        self.assertFalse(result.device_review)
        self.assertEqual(result.status, "matched")

    def test_failed_device_detection_found_group_is_red(self):
        result, _ = self.check(input_row=row("APB-ACC-04-XYZ"))
        self.assertFalse(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(result.status, "unmatched")

    def test_appendix_false_scan_uses_group_not_full_point_name(self):
        result, _ = self.check(
            input_row=row(code="UNKNOWN"),
            documents=[schema(point="ANOTHER-POINT", system="OTHER")],
        )
        self.assertFalse(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(result.status, "unmatched")

    def test_appendix_false_scan_does_not_match_point_name_values(self):
        self.assertFalse(contains_point_base(
            [{"OTHER": {"Thing": {"unrelated": {
                "P": {"point_name": "APB-ACC-04"}
            }}}}],
            "APB-ACC-04",
        ))

    def test_appendix_false_scan_searches_all_documents(self):
        result, _ = self.check(
            input_row=row(code="UNKNOWN"), documents=[{}, schema()]
        )
        self.assertTrue(result.schema)

    def test_appendix_true_absent_schema_is_red(self):
        result, _ = self.check(documents=[])
        self.assertTrue(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "unmatched")

    def test_wrong_path_is_not_a_match_even_when_point_exists(self):
        result, _ = self.check(documents=[schema(system="OTHER")])
        self.assertFalse(result.schema)

    def test_wrong_full_point_name_is_not_a_match(self):
        result, _ = self.check(documents=[schema(point="APB-ACC-04-S1")])
        self.assertFalse(result.schema)

    def test_schema_path_searches_all_documents(self):
        result, _ = self.check(documents=[{}, schema()])
        self.assertTrue(result.schema)

    def test_missing_null_and_empty_equipment_code_use_misc(self):
        for kind in ("missing", None, "", "   "):
            with self.subTest(kind=kind):
                record = appendix(
                    "SS", kind, "FS", "Clean Agent Fire Extinguishing System",
                    "System Status",
                )
                if kind == "missing":
                    del record["Equipment Code"]
                result, _ = self.check(
                    records=[record],
                    documents=[schema(
                        point="APB-FAS-01-SS", base="APB-FAS-01", system="FS",
                        equipment="MISC", parameter="System Status",
                    )],
                    input_row=row("APB-FAS-01-SS", "FAS"),
                )
                self.assertEqual(result.status, "matched")
                self.assertEqual(result.match_method, "MISC")
                self.assertEqual(
                    result.candidate_results[0]["Schema Equipment"], "MISC"
                )

    def test_blank_csv_equipment_does_not_match_every_code(self):
        result, _ = self.check(input_row=row(code=""))
        self.assertFalse(result.appendix)

    def test_misc_function_supports_slash_tokens(self):
        result, _ = self.check(
            records=[appendix("SS/ST", None, "FS", "Fire", "Status")],
            documents=[schema(system="FS", equipment="MISC", parameter="Status",
                              point="APB-ACC-04-SS")],
            input_row=row("APB-ACC-04-SS"),
        )
        self.assertEqual(result.status, "matched")

    def test_same_mapping_duplicates_do_not_trigger_blue(self):
        result, _ = self.check(records=[appendix(), appendix()])
        self.assertEqual(result.status, "matched")
        self.assertEqual(len(result.candidate_results), 1)

    def test_multi_mapping_keeps_candidates_and_disagreement_blank(self):
        result, _ = self.check(records=[
            appendix(), appendix(parameter="Different"),
        ])
        self.assertTrue(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "multiple mappings")
        self.assertEqual(
            [r["Schema Match"] for r in result.candidate_results], [True, False]
        )

    def test_multiple_candidates_with_same_outcome_keep_schema_boolean(self):
        result, _ = self.check(
            records=[appendix(), appendix(parameter="Different")], documents=[]
        )
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "multiple mappings")

    def test_blue_takes_priority_over_device_yellow_and_query_error(self):
        result, _ = self.check(
            records=[appendix(), appendix(parameter="Different")],
            input_row=row("APB-ACC-04-SWT"),
            error="database unavailable",
        )
        self.assertEqual(result.status, "multiple mappings")
        self.assertTrue(result.device_review)
        self.assertIsNone(result.schema)
        self.assertIn("database unavailable", result.errors)
        self.assertEqual(len(result.candidate_results), 2)

    def test_function_only_multiple_records_do_not_trigger_blue(self):
        result, _ = self.check(records=[
            appendix(), appendix(code="AHU", equipment="AHU"),
        ])
        self.assertEqual(result.status, "matched")

    def test_hyphenated_building_and_optional_segments(self):
        for point, base in (
            ("APB-FAS-SS", "APB-FAS"),
            ("APB-ACC-04-S", "APB-ACC-04"),
            ("APB-5F-AHU-01-S", "APB-5F-AHU-01"),
            ("YLDOB-010-ACC-04-S", "YLDOB-010-ACC-04"),
        ):
            with self.subTest(point=point):
                function = point.rsplit("-", 1)[1]
                result, source = self.check(
                    records=[appendix(function)],
                    documents=[schema(point=point, base=base)],
                    input_row=row(point, building="TARGET"),
                )
                self.assertEqual(result.point_base_name, base)
                self.assertEqual(source.buildings, ["TARGET"])
                self.assertEqual(result.status, "matched")

    def test_invalid_input_marks_yellow_without_fake_booleans(self):
        for point in (None, "", "NOHYPHEN", "APB-", "-S", 123):
            with self.subTest(point=point):
                result, source = self.check(input_row=row(point))
                self.assertEqual(result.status, "review")
                self.assertTrue(result.errors)
                self.assertIsNone(result.appendix)
                self.assertIsNone(result.schema)
                self.assertEqual(source.buildings, [])

    def test_query_failure_is_yellow_and_not_schema_false(self):
        result, _ = self.check(error="permission denied")
        self.assertTrue(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "review")
        self.assertEqual(result.errors, ["permission denied"])

    def test_malformed_matched_metadata_is_yellow(self):
        record = appendix()
        del record["System"]
        result, _ = self.check(records=[record])
        self.assertTrue(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "review")

    def test_malformed_schema_path_is_yellow(self):
        result, _ = self.check(documents=[{"HVAC/W": 123}])
        self.assertEqual(result.status, "review")
        self.assertIsNone(result.schema)
        self.assertTrue(result.errors)

    def test_real_apb_snapshot_off_on_status(self):
        path = Path(__file__).resolve().parents[1] / "src" / "building_json" / "APB.json"
        documents = json.loads(path.read_text(encoding="utf-8"))
        result, _ = self.check(documents=documents)
        self.assertEqual(result.status, "matched")

    def test_invalid_appendix_fails_explicitly(self):
        for records in ([], [{"Equipment Code": "ACC"}]):
            with self.subTest(records=records):
                with self.assertRaises(CheckingError):
                    PointChecker(records, MemorySource())


if __name__ == "__main__":
    unittest.main()
