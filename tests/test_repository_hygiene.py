from pathlib import Path

CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def test_merge_conflict_markers_are_not_committed() -> None:
    """Keep manually resolved parser conflicts from silently reaching the PR."""
    repository_root = Path(__file__).resolve().parents[1]
    conflict_prone_files = (
        repository_root / "app/parsers/protocol.py",
        repository_root / "tests/test_memo_parser.py",
    )

    for path in conflict_prone_files:
        content = path.read_text(encoding="utf-8")
        assert not any(marker in content for marker in CONFLICT_MARKERS), (
            f"Unresolved merge conflict marker found in {path.relative_to(repository_root)}"
        )
