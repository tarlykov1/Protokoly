from app.db.session import SessionLocal
from app.services.imports.service import cleanup_expired_import_sessions


def main() -> None:
    with SessionLocal() as db:
        print(f"expired sessions cleaned: {cleanup_expired_import_sessions(db)}")


if __name__ == "__main__":
    main()
