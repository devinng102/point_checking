"""Export each building's enm_semantic_schema MongoDB collection to JSON."""

import argparse
import sys
from pathlib import Path

from bson.json_util import dumps
from pymongo.errors import PyMongoError

from building_config import MASTER_BUILDING
from mongodb_connect import DB

DEFAULT_OUTPUT_DIRECTORY = Path(__file__).parent / "src" / "building_json"


def export_collection(building_name: str, output_directory: Path) -> tuple[int, Path]:
    collection = DB[building_name]["enm_semantic_schema"]
    output_path = output_directory / f"{building_name}.json"
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    exported_count = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as json_file:
            json_file.write("[\n")
            for document in collection.find():
                if exported_count:
                    json_file.write(",\n")
                json_file.write(dumps(document, ensure_ascii=False))
                exported_count += 1
            json_file.write("\n]\n")

        temporary_path.replace(output_path)
    except (OSError, PyMongoError):
        temporary_path.unlink(missing_ok=True)
        raise

    return exported_count, output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export every building's enm_semantic_schema collection as JSON."
    )
    parser.add_argument(
        "output_directory",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIRECTORY})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    total_exported_count = 0

    try:
        for building_name in MASTER_BUILDING:
            exported_count, output_path = export_collection(
                building_name, args.output_directory
            )
            total_exported_count += exported_count
            print(
                f"Exported {exported_count} documents from {building_name} "
                f"to {output_path.resolve()}"
            )
    except (OSError, PyMongoError) as exc:
        print(
            f"Export failed for {building_name} ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        DB.close()

    print(
        f"Exported {total_exported_count} documents from "
        f"{len(MASTER_BUILDING)} buildings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
