import pytest

from research_cli.tools import Workspace


def test_saved_api_config_is_blocked_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    credentials = tmp_path / "config/research-cli/api.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text("fixture")
    (tmp_path / "alias.json").symlink_to(credentials)
    workspace = Workspace(tmp_path)
    for name in ("config/research-cli/api.json", "alias.json"):
        with pytest.raises(ValueError, match="credentials"):
            workspace.read(name)
    assert credentials not in workspace.files()


def test_package_manifest_and_private_agent_state_are_blocked(tmp_path, monkeypatch):
    from research_cli.tools import Workspace

    manifest = tmp_path / "packages.json"
    manifest.write_text("{}")
    state = tmp_path / "agent-state"
    state.mkdir()
    (state / "auth.json").write_text("fixture")
    (tmp_path / "manifest-alias.json").symlink_to(manifest)
    (tmp_path / "state-alias").symlink_to(state, target_is_directory=True)
    monkeypatch.setenv("RESEARCH_PACKAGE_CONFIG", str(manifest))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(state))
    workspace = Workspace(tmp_path)
    for path in (
        "packages.json",
        "manifest-alias.json",
        "agent-state/auth.json",
        "state-alias/auth.json",
    ):
        with pytest.raises(ValueError, match="blocked"):
            workspace.read(path)
    assert manifest not in workspace.files()
