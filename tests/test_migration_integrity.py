from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_deployed_migration_names_and_new_revision_chain_are_preserved():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20261103_0021"]
    for revision, filename, parent in [
        ("20261026_0019", "20261026_0019_pre_workout_meal_type.py", "20261021_0018"),
        ("20261028_0020", "20261028_0020_daily_metrics.py", "20261026_0019"),
        ("20261103_0021", "20261103_0021_admin_and_rate_limits.py", "20261028_0020"),
    ]:
        migration = scripts.get_revision(revision)
        assert Path(migration.path).name == filename
        assert migration.revision == revision
        assert migration.down_revision == parent
