import pytest

from open_webui.socket.paths import socketio_path_for_root


def test_socketio_path_for_root_deployment():
    assert socketio_path_for_root('') == '/ws/socket.io'


def test_socketio_path_for_subpath_deployment():
    assert socketio_path_for_root('/opsmitra') == '/opsmitra/ws/socket.io'


@pytest.mark.parametrize('root_path', ['opsmitra', '/opsmitra/'])
def test_socketio_path_rejects_invalid_root_path(root_path):
    with pytest.raises(ValueError):
        socketio_path_for_root(root_path)
