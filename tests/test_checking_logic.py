import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from checking_logic import (
    BUILDING_COLUMN,
    EQUIPMENT_COLUMN,
    POINT_COLUMN,
    CheckingError,
    PointChecker,
    contains_point,
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

    def test_failed_device_detection_found_full_point_is_red(self):
        result, _ = self.check(
            input_row=row("APB-ACC-04-XYZ"),
            documents=[schema(point="APB-ACC-04-XYZ")],
        )
        self.assertFalse(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(result.status, "unmatched")

    def test_failed_device_detection_group_alone_does_not_match(self):
        result, _ = self.check(input_row=row("APB-ACC-04-XYZ"))
        self.assertFalse(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "matched")

    def test_appendix_false_scan_requires_full_point_name_in_group(self):
        result, _ = self.check(
            input_row=row(code="UNKNOWN"),
            documents=[schema(point="ANOTHER-POINT", system="OTHER")],
        )
        self.assertFalse(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "matched")

    def test_appendix_false_scan_does_not_match_point_name_values(self):
        self.assertFalse(contains_point(
            [{"OTHER": {"Thing": {"unrelated": {
                "P": {"point_name": "APB-ACC-04"}
            }}}}],
            "APB-ACC-04",
            "APB-ACC-04-S",
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

    def test_misc_missing_path_is_unknown_not_false(self):
        for documents, missing in (
            ([], "'FS'"),
            ([{"FS": {}}], "'FS' -> 'MISC'"),
            ([{"FS": {"MISC": {"OTHER": {}}}}], "'FS' -> 'MISC' -> 'APB-ACC-04'"),
        ):
            with self.subTest(missing=missing):
                result, _ = self.check(
                    records=[appendix(code=None, system="FS")],
                    documents=documents,
                )
                self.assertIsNone(result.appendix)
                self.assertFalse(result.schema)
                self.assertEqual(result.status, "review")
                self.assertFalse(result.errors)
                diagnostic = result.candidate_results[0]
                self.assertIsNone(diagnostic["MISC Relevance"])
                self.assertIsNone(diagnostic["Schema Match"])
                self.assertIn(missing, diagnostic["Relevance Reason"])
                self.assertIn("full Point Name scan", " ".join(result.reasons))

    def test_misc_unknown_scans_exact_point_not_group_only(self):
        for point, expected in (("APB-ACC-04-S", True), ("APB-ACC-04-S1", False)):
            with self.subTest(point=point):
                result, _ = self.check(
                    records=[appendix(code=None, system="PV")],
                    documents=[{}, schema(point=point)],
                )
                self.assertIsNone(result.appendix)
                self.assertEqual(result.schema, expected)
                self.assertEqual(result.status, "review")

    def test_misc_group_exists_missing_parameter_or_point_is_red(self):
        for group in ({}, {"Different": {"point_name": "APB-ACC-04-S"}},
                      {"Off/On Status": {"point_name": "APB-ACC-04-S1"}}):
            with self.subTest(group=group):
                result, _ = self.check(
                    records=[appendix(code=None)],
                    documents=[{"HVAC/W": {"MISC": {"APB-ACC-04": group}}}],
                )
                self.assertTrue(result.appendix)
                self.assertFalse(result.schema)
                self.assertEqual(result.status, "unmatched")
                self.assertTrue(result.candidate_results[0]["MISC Relevance"])

    def test_misc_relevance_searches_all_documents(self):
        result, _ = self.check(
            records=[appendix(code=None)],
            documents=[{}, {"HVAC/W": {}}, schema(equipment="MISC")],
        )
        self.assertEqual(result.status, "matched")
        self.assertTrue(result.appendix)
        self.assertTrue(result.schema)

    def test_misc_missing_parts_in_different_documents_do_not_form_a_path(self):
        result, _ = self.check(
            records=[appendix(code=None)],
            documents=[{"HVAC/W": {}},
                       {"OTHER": {"MISC": {"APB-ACC-04": {}}}}],
        )
        self.assertIsNone(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "review")

    def test_misc_valid_group_does_not_hide_malformed_group_in_other_document(self):
        result, _ = self.check(
            records=[appendix(code=None)],
            documents=[schema(equipment="MISC"),
                       {"HVAC/W": {"MISC": {"APB-ACC-04": 123}}}],
        )
        self.assertIsNone(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "review")
        self.assertTrue(result.errors)

    def test_misc_unknown_scan_malformed_point_does_not_become_false(self):
        result, _ = self.check(
            records=[appendix(code=None, system="PV")],
            documents=[{"OTHER": {"Thing": {"APB-ACC-04": {"Status": 123}}}}],
        )
        self.assertIsNone(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "review")
        self.assertTrue(result.errors)

    def test_misc_device_id_still_uses_full_point_and_unmodified_parameter(self):
        result, _ = self.check(
            records=[appendix(code=None)],
            documents=[schema(point="APB-ACC-04-S01", equipment="MISC")],
            input_row=row("APB-ACC-04-S01"),
        )
        self.assertTrue(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(result.device_id, "01")
        self.assertEqual(result.status, "matched")

    def test_misc_multiple_unknown_candidates_are_yellow_not_blue(self):
        result, _ = self.check(
            records=[appendix(code=None), appendix(code=None, system="PV")],
            documents=[],
        )
        self.assertEqual(result.status, "review")
        self.assertIsNone(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(len(result.candidate_results), 2)

    def test_misc_mixed_relevance_remains_unknown_and_keeps_candidates(self):
        result, _ = self.check(
            records=[appendix(code=None), appendix(code=None, system="PV")],
            documents=[schema(equipment="MISC")],
        )
        self.assertEqual(result.status, "review")
        self.assertIsNone(result.appendix)
        self.assertTrue(result.schema)
        self.assertEqual(
            [c["MISC Relevance"] for c in result.candidate_results], [True, None]
        )
        self.assertEqual(
            [c["Schema Match"] for c in result.candidate_results], [True, None]
        )

    def test_misc_multiple_accepted_mappings_are_blue_even_with_unknown(self):
        for extra in ([], [appendix(code=None, system="PV")]):
            with self.subTest(extra=bool(extra)):
                result, _ = self.check(
                    records=[appendix(code=None),
                             appendix(code=None, parameter="Different"), *extra],
                    documents=[schema(equipment="MISC")],
                )
                self.assertEqual(result.status, "multiple mappings")
                self.assertEqual(result.appendix, None if extra else True)
                self.assertEqual(result.schema, True if extra else None)
                self.assertEqual(len(result.candidate_results), 2 + len(extra))

    def test_misc_duplicate_mapping_does_not_trigger_blue(self):
        result, _ = self.check(
            records=[appendix(code=None), appendix(code=None)],
            documents=[schema(equipment="MISC")],
        )
        self.assertEqual(result.status, "matched")
        self.assertEqual(len(result.candidate_results), 1)

    def test_misc_query_failure_preserves_unknown_booleans_and_candidates(self):
        result, _ = self.check(
            records=[appendix(code=None), appendix(code=None, system="PV")],
            error="permission denied",
        )
        self.assertIsNone(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "review")
        self.assertEqual(result.errors, ["permission denied"])
        self.assertEqual(len(result.candidate_results), 2)
        self.assertEqual(result.candidate_results[0]["Relevance Reason"], "permission denied")

    def test_misc_malformed_relevance_path_is_unknown_not_absent(self):
        for document in (
            {"HVAC/W": 123},
            {"HVAC/W": {"MISC": 123}},
            {"HVAC/W": {"MISC": {"APB-ACC-04": 123}}},
        ):
            with self.subTest(document=document):
                result, _ = self.check(records=[appendix(code=None)], documents=[document])
                self.assertIsNone(result.appendix)
                self.assertIsNone(result.schema)
                self.assertEqual(result.status, "review")
                self.assertTrue(result.errors)
                self.assertIn("Error", result.candidate_results[0])

    def test_misc_malformed_parameter_keeps_accepted_appendix(self):
        result, _ = self.check(
            records=[appendix(code=None)],
            documents=[{"HVAC/W": {"MISC": {"APB-ACC-04": {"Off/On Status": 123}}}}],
        )
        self.assertTrue(result.appendix)
        self.assertIsNone(result.schema)
        self.assertEqual(result.status, "review")
        self.assertTrue(result.errors)

    def test_misc_cache_does_not_cache_building_relevance(self):
        class BuildingSource:
            def get_schema(self, building):
                return [schema(equipment="MISC")] if building == "APB" else []

        checker = PointChecker([appendix(code=None)], BuildingSource())
        self.assertEqual(checker.check(row()).status, "matched")
        self.assertEqual(checker.check(row(building="OTHER")).status, "review")

    def test_outd_pv_candidate_against_local_apb_snapshot_requires_review(self):
        path = Path(__file__).resolve().parents[1] / "src" / "building_json" / "APB.json"
        result, _ = self.check(
            records=[appendix("TFALM", None, "PV", "PV System",
                              "PV System Normal / Fault Alarm")],
            documents=json.loads(path.read_text(encoding="utf-8")),
            input_row=row("APB-4F-SVRRM-OUTD-TFALM", "SVRRM"),
        )
        self.assertIsNone(result.appendix)
        self.assertFalse(result.schema)
        self.assertEqual(result.status, "review")

    def test_rwt_group_alone_does_not_reintroduce_false_positive(self):
        path = Path(__file__).resolve().parents[1] / "src" / "building_json" / "APB.json"
        result, _ = self.check(
            records=[appendix("RWT", "COT", equipment="Cooling Tower",
                              parameter="Return Water Temperature")],
            documents=json.loads(path.read_text(encoding="utf-8")),
            input_row=row("APB-ACC-03-RWT"),
        )
        self.assertFalse(result.appendix)
        self.assertFalse(result.schema)
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


class DiagramTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "flow.drawio"
        self.cells = ET.parse(path).findall(".//mxCell")
        self.by_id = {cell.attrib["id"]: cell for cell in self.cells}

    def test_flow_references_and_explicit_unknown_branch(self):
        self.assertEqual(len(self.by_id), len(self.cells))
        for cell in self.cells:
            for attribute in ("parent", "source", "target"):
                if attribute in cell.attrib:
                    self.assertIn(cell.attrib[attribute], self.by_id)
        branch = self.by_id["misc-main-unknown-branch"]
        self.assertEqual(branch.attrib["source"], "Au464GKHaQkNzhSAhbhp-3")
        self.assertEqual(branch.attrib["target"], "misc-main-unknown")
        self.assertEqual(
            self.by_id["misc-main-unknown-export"].attrib["target"],
            "final-resolution",
        )
        self.assertIn("Unknown", self.by_id["final-yellow-check"].attrib["value"])

    def test_misc_subflow_nodes_fit_without_overlapping(self):
        container = self.by_id["misc-relevance-process"].find("mxGeometry")
        boxes = []
        for cell in self.cells:
            if (
                cell.attrib.get("parent") != "misc-relevance-process"
                or cell.attrib.get("vertex") != "1"
            ):
                continue
            geometry = cell.find("mxGeometry")
            x, y, width, height = (
                float(geometry.attrib.get(key, 0))
                for key in ("x", "y", "width", "height")
            )
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + width, float(container.attrib["width"]))
            self.assertLessEqual(y + height, float(container.attrib["height"]))
            for other_id, ox, oy, ow, oh in boxes:
                self.assertFalse(
                    x < ox + ow and ox < x + width
                    and y < oy + oh and oy < y + height,
                    f"{cell.attrib['id']} overlaps {other_id}",
                )
            boxes.append((cell.attrib["id"], x, y, width, height))


if __name__ == "__main__":
    unittest.main()
