import pytest


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Ningún test debe tocar la carpeta de datos real del usuario."""
    home = tmp_path / "app_home"
    monkeypatch.setenv("PLAYLIST_CONVERTER_HOME", str(home))
    return home
