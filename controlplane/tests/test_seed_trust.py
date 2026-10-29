from __future__ import annotations

from controlplane.scripts.seed_trust import trajectory


def test_demo_trajectory_hits_target_scores_and_bands():
    stages = dict(trajectory())
    assert abs(stages["pre-demo"].score - 640) <= 5
    assert abs(stages["post-incident"].score - 570) <= 5
    assert abs(stages["post-fix"].score - 655) <= 5
    assert stages["pre-demo"].cap_inr == 6000
    assert stages["post-incident"].cap_inr == 2000
    assert stages["post-fix"].cap_inr == 6000
