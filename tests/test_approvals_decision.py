from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memory import store



def setup_store():
    temp_dir = Path(tempfile.mkdtemp())
    os.environ["ASTRA_DATA_DIR"] = str(temp_dir)
    store.reset_for_tests()
    store.init(temp_dir, ROOT / "memory" / "migrations")
    return temp_dir


def test_approval_decision_saved():
    setup_store()
    project = store.create_project("Тест", [], {})
    run = store.create_run(project["id"], "run", "execute_confirm")

    approval = store.create_approval(
        run_id=run["id"],
        task_id="task-1",
        scope="autopilot",
        title="Создать плейлист",
        description="Тест",
        proposed_actions=[],
    )
    store.update_approval_status(approval["id"], "approved", "user", decision={"limit": 50})
    loaded = store.get_approval(approval["id"])
    assert loaded is not None
    assert loaded.get("decision", {}).get("limit") == 50
