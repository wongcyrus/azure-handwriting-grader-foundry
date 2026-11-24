import argparse
import os
from pathlib import Path

import uvicorn

from .api import create_app
from .auth import DevelopmentAuthenticator, EntraAuthenticator
from .repository import SQLiteRepository
from .service import ExamService


def main():
    parser = argparse.ArgumentParser(description="Run the initial, local input-review API.")
    parser.add_argument("--development", action="store_true", help="Synthetic local identity only")
    parser.add_argument("--database", type=Path, default=Path(".local/exams.sqlite3"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.development:
            authenticator = DevelopmentAuthenticator(os.environ["FOUNDRY_DEV_TOKEN"])
        else:
            authenticator = EntraAuthenticator(
                os.environ["FOUNDRY_ENTRA_TENANT_ID"],
                os.environ["FOUNDRY_ENTRA_AUDIENCE"],
                os.environ.get("FOUNDRY_ENTRA_SCOPE", "Exam.Access"),
            )
    except (KeyError, ValueError) as error:
        parser.error(f"Authentication is not configured: {error}")
    app = create_app(ExamService(SQLiteRepository(args.database)), authenticator)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
