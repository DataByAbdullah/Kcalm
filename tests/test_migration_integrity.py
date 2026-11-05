import hashlib
import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_deployed_migration_names_and_new_revision_chain_are_preserved():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20261105_0022"]
    for revision, filename, parent in [
        ("20261026_0019", "20261026_0019_pre_workout_meal_type.py", "20261021_0018"),
        ("20261028_0020", "20261028_0020_daily_metrics.py", "20261026_0019"),
        ("20261103_0021", "20261103_0021_admin_and_rate_limits.py", "20261028_0020"),
        ("20261105_0022", "20261105_0022_profile_meal_schedule.py", "20261103_0021"),
    ]:
        migration = scripts.get_revision(revision)
        assert Path(migration.path).name == filename
        assert migration.revision == revision
        assert migration.down_revision == parent


def test_historical_migration_files_remain_byte_for_byte_unchanged():
    root = Path(__file__).resolve().parents[1]
    checksums = json.loads((root / "tests/migration_checksums.json").read_text())
    for path, expected in checksums.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path
