from app.assistant.profile import DEFAULT_PROFILE, load_profile, save_profile


def test_profile_store_is_local_and_tolerates_corrupt_data(tmp_path):
    path = tmp_path / "profile.json"
    assert load_profile(path) == DEFAULT_PROFILE

    saved = save_profile(path, {"name": "모모", "tone": "간결하게"})
    assert saved["name"] == "모모"
    assert saved["tone"] == "간결하게"
    assert load_profile(path)["personality"] == DEFAULT_PROFILE["personality"]

    path.write_text("not-json", encoding="utf-8")
    assert load_profile(path) == DEFAULT_PROFILE
