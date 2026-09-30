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
