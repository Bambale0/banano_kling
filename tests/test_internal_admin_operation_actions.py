from bot.internal_admin_operation_actions import _provider_accepted


def test_provider_acceptance_requires_task_and_non_failed_status() -> None:
    assert _provider_accepted({"task_id": "child-task", "status": "pending"})
    assert _provider_accepted({"task_id": "child-task", "status": "completed"})
    assert not _provider_accepted({"task_id": "", "status": "pending"})
    assert not _provider_accepted({"task_id": "child-task", "status": "failed"})
    assert not _provider_accepted({"task_id": "child-task", "status": "rejected"})
    assert not _provider_accepted(None)
