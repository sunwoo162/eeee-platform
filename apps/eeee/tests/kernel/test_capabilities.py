from app.contracts import ExecutionStatus
from app.kernel.capabilities import _project_execution_status


def test_project_release_gate_does_not_persist_completion_when_evidence_is_blocked() -> None:
    assert _project_execution_status(
        quality_status="PASS", final_blockers=["ClaimLatch evidence is missing"], missing_extensions=[]
    ) is ExecutionStatus.BLOCKED
    assert _project_execution_status(
        quality_status="PASS", final_blockers=[], missing_extensions=["connector.figma.read"]
    ) is ExecutionStatus.BLOCKED
    assert _project_execution_status(
        quality_status="PASS", final_blockers=[], missing_extensions=[]
    ) is ExecutionStatus.COMPLETED
