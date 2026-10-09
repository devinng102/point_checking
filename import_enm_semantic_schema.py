"""Import building JSON files into enm_semantic_schema collections."""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from bson.json_util import dumps, loads
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from building_config import MASTER_BUILDING

DEFAULT_INPUT_DIRECTORY = Path(__file__).parent / "src" / "building_json"
COLLECTION_NAME = "enm_semantic_schema"


def create_target_client() -> MongoClient[dict[str, Any]]:
    load_dotenv(Path(__file__).with_name(".env"))
    uri = os.environ.get("TARGET_MONGODB_URI")
    if not uri:
        raise ValueError(
            "Set TARGET_MONGODB_URI in the environment or the project .env file."
        )
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=10_000,
        connectTimeoutMS=10_000,
        connect=False,
    )


def load_documents(json_path: Path) -> list[dict[str, Any]]:
    parsed_json = loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(parsed_json, list):
        raise ValueError(f"{json_path} must contain a JSON array.")

    documents: list[dict[str, Any]] = []
    document_ids: set[str] = set()
    for index, document in enumerate(parsed_json):
        if not isinstance(document, dict):
            raise ValueError(
                f"{json_path} document at index {index} must be a JSON object."
            )

        if "_id" in document:
            document_id = dumps(document["_id"], sort_keys=True)
            if document_id in document_ids:
                raise ValueError(
                    f"{json_path} contains a duplicate _id at index {index}."
                )
            document_ids.add(document_id)

        documents.append(document)

    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replace each building's enm_semantic_schema collection "
            "with its exported JSON data."
        )
    )
    parser.add_argument(
        "input_directory",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_DIRECTORY,
        help=f"input directory (default: {DEFAULT_INPUT_DIRECTORY})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    building_documents: dict[str, list[dict[str, Any]]] = {}

    try:
        for building_name in MASTER_BUILDING:
            json_path = args.input_directory / f"{building_name}.json"
            building_documents[building_name] = load_documents(json_path)
    except (OSError, ValueError) as exc:
        print(f"Input validation failed: {exc}", file=sys.stderr)
        return 1

    try:
        client = create_target_client()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    total_inserted_count = 0
    try:
        client.admin.command("ping")
        for building_name, documents in building_documents.items():
            collection = client[building_name][COLLECTION_NAME]
            deleted_count = collection.delete_many({}).deleted_count
            inserted_count = 0
            if documents:
                inserted_count = len(collection.insert_many(documents).inserted_ids)
            total_inserted_count += inserted_count
            print(
                f"{building_name}: deleted {deleted_count}, "
                f"inserted {inserted_count} documents."
            )
    except PyMongoError as exc:
        print(
            f"Import failed for {building_name} ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        client.close()

    print(
        f"Inserted {total_inserted_count} documents into "
        f"{len(MASTER_BUILDING)} building databases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
