"""Check point-list rows against Appendix B and building semantic schemas."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

BUILDING_COLUMN = "Building & Block Code"
EQUIPMENT_COLUMN = "Equipment Code / System / Room Code"
POINT_COLUMN = "Point Name"
FUNCTION_FIELD = "Function or Status Code"

Document = Mapping[str, Any]
Status = Literal["matched", "unmatched", "review", "multiple mappings"]


class CheckingError(ValueError):
    """A checking step could not produce a trustworthy boolean result."""


class SchemaSource(Protocol):
    def get_schema(self, building: str) -> Sequence[Document]: ...


def required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CheckingError(f"{name} must be a non-empty string.")
    return value


def equipment_code(record: Document) -> str:
    value = record.get("Equipment Code")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CheckingError("Appendix B Equipment Code must be a string or null.")
    return value.strip()


def match_function(records: Sequence[Document], code: str) -> list[Document]:
    exact = [
        record for record in records
        if record[FUNCTION_FIELD].strip() == code
    ]
    if exact:
        return exact
    return [
        record for record in records
        if code in (token.strip() for token in record[FUNCTION_FIELD].split("/"))
    ]


@dataclass(frozen=True)
class Candidate:
    system: str
    equipment: str | None
    schema_equipment: str
    parameter: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "System": self.system,
            "Equipment": self.equipment,
            "Schema Equipment": self.schema_equipment,
            "iBMS Parameters": self.parameter,
        }


@dataclass
class CheckingResult:
    appendix: bool | None = None
    schema: bool | None = None
    function_code: str = ""
    point_base_name: str = ""
    base_function_code: str = ""
    device_id: str = ""
    match_method: str = ""
    device_review: bool = False
    multiple_mappings: bool = False
    reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    candidate_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if self.multiple_mappings:
            return "multiple mappings"
        if self.device_review or self.errors:
            return "review"
        if self.appendix is None or self.schema is None:
            return "review"
        return "matched" if self.appendix == self.schema else "unmatched"


def object_at(parent: Document, key: str) -> Document | None:
    if key not in parent:
        return None
    value = parent[key]
    if not isinstance(value, Mapping):
        raise CheckingError(f"Schema key {key!r} is not an object.")
    return value


def point_at_path(
    documents: Sequence[Document],
    candidate: Candidate,
    point_base_name: str,
    point_name: str,
) -> bool:
    for document in documents:
        current: Document | None = document
        for key in (
            candidate.system,
            candidate.schema_equipment,
            point_base_name,
            candidate.parameter,
        ):
            if current is None:
                break
            current = object_at(current, key)
        if current is not None and current.get("point_name") == point_name:
            return True
    return False


def contains_point_base(
    documents: Sequence[Document], point_base_name: str
) -> bool:
    for document in documents:
        for system in document.values():
            if not isinstance(system, Mapping):
                continue
            for equipment in system.values():
                if not isinstance(equipment, Mapping):
                    continue
                if point_base_name in equipment:
                    object_at(equipment, point_base_name)
                    return True
    return False


class PointChecker:
    def __init__(
        self, appendix: Sequence[Document], schema_source: SchemaSource
    ) -> None:
        if not appendix:
            raise CheckingError("Appendix B is empty; checking cannot proceed.")
        for index, record in enumerate(appendix):
            if not isinstance(record, Mapping):
                raise CheckingError(f"Appendix B record {index} is not an object.")
            required_text(record.get(FUNCTION_FIELD), f"Appendix B {FUNCTION_FIELD}")
            equipment_code(record)
        self.appendix = appendix
        self.schema_source = schema_source
        self._equipment_cache: dict[
            tuple[str, str], tuple[list[Document], str]
        ] = {}

    def _match_equipment(
        self, code: str, function: str
    ) -> tuple[list[Document], str]:
        cache_key = (code, function)
        if cache_key in self._equipment_cache:
            return self._equipment_cache[cache_key]

        stages: list[tuple[list[Document], str]] = []
        if code:
            stages.extend([
                (
                    [r for r in self.appendix if equipment_code(r) == code],
                    "exact Equipment Code",
                ),
                (
                    [r for r in self.appendix if code in equipment_code(r)],
                    "RegExp Equipment Code",
                ),
            ])
        stages.append((
            [r for r in self.appendix if not equipment_code(r)],
            "MISC",
        ))
        for pool, method in stages:
            records = match_function(pool, function)
            if records:
                result = (records, method)
                self._equipment_cache[cache_key] = result
                return result
        result = ([], "no Equipment / Function mapping")
        self._equipment_cache[cache_key] = result
        return result

    def _candidates(
        self, records: Sequence[Document], method: str, function: str
    ) -> list[Candidate]:
        if method == "exact Equipment Code":
            names = {
                required_text(r.get("Equipment"), "Appendix B Equipment")
                for r in records
            }
            records = match_function(
                [r for r in self.appendix if r.get("Equipment") in names],
                function,
            )

        candidates: list[Candidate] = []
        for record in records:
            system = required_text(record.get("System"), "Appendix B System")
            parameter = required_text(
                record.get("iBMS Parameters"), "Appendix B iBMS Parameters"
            )
            equipment = record.get("Equipment")
            if method == "MISC":
                if equipment is not None and not isinstance(equipment, str):
                    raise CheckingError("Appendix B Equipment must be a string.")
                schema_equipment = "MISC"
            else:
                equipment = required_text(equipment, "Appendix B Equipment")
                schema_equipment = equipment
            candidate = Candidate(system, equipment, schema_equipment, parameter)
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def check(self, row: Mapping[str, Any]) -> CheckingResult:
        result = CheckingResult()
        try:
            point_name = required_text(row.get(POINT_COLUMN), POINT_COLUMN)
            base, separator, function = point_name.rpartition("-")
            if not separator or not base.strip() or not function.strip():
                raise CheckingError(
                    "Point Name must contain a non-empty base and final code "
                    "separated by a hyphen."
                )
            result.function_code = function.strip()
            result.point_base_name = base
            result.base_function_code = result.function_code

            building = required_text(row.get(BUILDING_COLUMN), BUILDING_COLUMN)
            code_value = row.get(EQUIPMENT_COLUMN)
            if code_value is None:
                code = ""
            elif isinstance(code_value, str):
                code = code_value.strip()
            else:
                raise CheckingError(f"{EQUIPMENT_COLUMN} must be a string or blank.")

            function_found = bool(
                match_function(self.appendix, result.function_code)
            )
            if not function_found:
                for count in (1, 2):
                    if len(result.function_code) <= count:
                        continue
                    candidate_code = result.function_code[:-count]
                    if match_function(self.appendix, candidate_code):
                        result.base_function_code = candidate_code
                        result.device_id = result.function_code[-count:]
                        result.device_review = not all(
                            "0" <= digit <= "9" for digit in result.device_id
                        )
                        if result.device_review:
                            result.reasons.append(
                                f"Non-numeric Device ID candidate: "
                                f"{result.function_code} -> {candidate_code} + "
                                f"{result.device_id}; manual review required."
                            )
                        else:
                            result.reasons.append(
                                f"Numeric Device ID {result.device_id!r}; "
                                f"base Function Code {candidate_code!r}."
                            )
                        function_found = True
                        break

            if not function_found:
                result.appendix = False
                result.match_method = "Function Code not found"
                result.reasons.append(
                    "Function Code did not match exactly, as a slash token, "
                    "or after stripping up to two trailing characters."
                )
            else:
                records, method = self._match_equipment(
                    code, result.base_function_code
                )
                result.appendix = bool(records)
                result.match_method = method
                result.reasons.append(f"Appendix B matching: {method}.")
                if records:
                    candidates = self._candidates(
                        records, method, result.base_function_code
                    )
                    result.multiple_mappings = len(candidates) > 1
                    if result.multiple_mappings:
                        result.reasons.append(
                            "Multiple different System / Equipment / "
                            "iBMS Parameters mappings; blue review takes priority."
                        )
                    result.candidate_results = [
                        {**c.as_dict(), "Schema Match": None}
                        for c in candidates
                    ]
                    documents = self.schema_source.get_schema(building)
                    outcomes: list[bool | None] = []
                    for candidate, diagnostic in zip(
                        candidates, result.candidate_results
                    ):
                        try:
                            outcome = point_at_path(
                                documents, candidate, base, point_name
                            )
                        except CheckingError as exc:
                            outcome = None
                            diagnostic["Error"] = str(exc)
                            result.errors.append(str(exc))
                        diagnostic["Schema Match"] = outcome
                        outcomes.append(outcome)
                    if outcomes and all(
                        outcome is not None and outcome == outcomes[0]
                        for outcome in outcomes
                    ):
                        result.schema = outcomes[0]
                    else:
                        result.reasons.append(
                            "Candidate schema results are unresolved or disagree; "
                            "the aggregate schema result is left blank."
                        )
                    if result.schema is not None:
                        result.reasons.append(
                            "Mapped path and original Point Name "
                            + ("matched." if result.schema else "did not match.")
                        )
                    return result

            documents = self.schema_source.get_schema(building)
            result.schema = contains_point_base(documents, base)
            result.reasons.append(
                f"Appendix=False: derived point base name {base!r} "
                + ("exists in the building schema." if result.schema else
                   "does not exist in the building schema.")
            )
        except CheckingError as exc:
            result.errors.append(str(exc))
        return result
