"""Share a MongoDB client configured with the MONGODB_URI environment variable.

Usage:
    from mongodb_connect import DB

    database = DB["Testing"]
    collection = database["your_collection"]

The importing application must call DB.close() when it is finished.
Running this file directly checks connectivity and closes the client.
"""

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv(Path(__file__).with_name(".env"))




def create_client() -> MongoClient[dict[str, Any]]:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise ValueError(
            "Set MONGODB_URI in the .env file next to mongodb_connect.py."
        )
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=10_000,
        connectTimeoutMS=10_000,
        connect=False,
    )


DB = create_client()


def main() -> int:
    try:
        DB.admin.command("ping")
        print("Connected successfully to MongoDB.")
    except PyMongoError as exc:
        print(f"MongoDB connection failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    finally:
        DB.close()
    return 0


if __name__ == "__main__":
    building_json = DB["APB"]["enm_semantic_schema"].find_one()
    appendix_b = list(DB["MASTER"]["appendix_b"].find())
    print(appendix_b)
    # raise SystemExit(main())
