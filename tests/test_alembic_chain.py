from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_revisions_form_single_ordered_chain():
    """Protect the migration chain from missing or shorthand revision references."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    revisions = list(scripts.walk_revisions(base="base", head="heads"))

    assert [revision.revision for revision in reversed(revisions)] == [
        "0001_create_foundation_tables",
        "0002_add_import_sessions",
        "0003_add_publication_runs",
        "0004_add_parser_id",
        "0005_add_protocol_task_control",
        "0006_add_protocol_task_links",
        "0007_add_execution_control",
        "0008_add_protocol_task_controls",
        "0009_protocol_user_workflow",
        "0010_add_integration_settings",
    ]
    assert len(scripts.get_heads()) == 1
