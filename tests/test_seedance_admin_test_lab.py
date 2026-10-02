from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seedance_admin_test_is_exposed_from_existing_test_lab():
    source = (ROOT / "bot/handlers/admin_test_lab.py").read_text(encoding="utf-8")
    assert 'callback_data="admin_seedance_lab"' in source
    assert "Seedance API" in source


def test_seedance_admin_router_is_wired_into_admin_router():
    source = (ROOT / "bot/handlers/__init__.py").read_text(encoding="utf-8")
    assert "admin_seedance_test_lab_router" in source
    assert "admin_router.include_router(admin_seedance_test_lab_router)" in source


def test_seedance_admin_test_has_full_documented_model_surface_and_no_rox_billing():
    source = (ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text(encoding="utf-8")
    service = (
        ROOT / "bot/services/neironych_seedance_admin_service.py"
    ).read_text(encoding="utf-8")

    for model in (
        "seedance-2.5",
        "seedance-2.0",
        "seedance-2.0-mini",
        "seedance-2.0-fast",
    ):
        assert model in source
        assert model in service

    assert "admin_seedance_generate" in source
    assert "admin_seedance_check" in source
    assert "list_enabled_seedance_models" in source
    assert "download_to_temp" in source
    assert "Idempotency-Key" in service
    assert "deduct" not in source.lower()
    assert "update_user_credits" not in source
    assert "credits" not in service.lower()


def test_access_guard_allows_seedance_admin_fsm_states():
    source = (ROOT / "bot/main.py").read_text(encoding="utf-8")
    assert '"SeedanceAdminTestStates:prompt"' in source
    assert '"SeedanceAdminTestStates:references"' in source
    assert '"SeedanceAdminTestStates:frames"' in source


def test_edit_mode_allows_supporting_media_after_source_video():
    source = (ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text(encoding="utf-8")
    assert "has_edit_source" in source
    assert 'kind != "video"' in source
    assert 'reference_images=images if mode in {"reference", "edit"} else None' in source
    assert 'reference_audios=audios if mode in {"reference", "edit"} else None' in source
    assert 'edit_only_video=mode == "edit"' not in source


def test_paid_submit_and_result_delivery_are_serialized():
    source = (ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text(encoding="utf-8")
    assert "_SUBMIT_LOCKS" in source
    assert "async with _submit_lock(callback.from_user.id)" in source
    assert "seedance_admin_last_payload_hash" in source
    assert 'F.data == "admin_seedance_new_request"' in source
    assert "_DELIVERY_LOCKS" in source
    assert "async with _delivery_lock(request_id)" in source
