from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import planner


def test_planner_returns_autopilot_plan():
    plan = planner.create_plan_for_query("Астра, сделай X")
    assert plan
    assert plan[0]["skill_name"] == "autopilot_computer"
    assert plan[0]["inputs"]["goal"] == "Астра, сделай X"
