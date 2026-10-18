from app.capabilities.status import canonical_plugin_status


def test_legacy_plugin_states_map_to_canonical_capability_states():
    assert canonical_plugin_status("available") == "not_installed"
    assert canonical_plugin_status("awaiting_authentication") == "auth_required"
    assert canonical_plugin_status("connected") == "ready"
    assert canonical_plugin_status("disabled") == "degraded"
    assert canonical_plugin_status("failed") == "failed"
