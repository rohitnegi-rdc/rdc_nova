import pytest
from open_webui.utils.app_path import prefix_root_path


def test_prefix_root_path_for_subpath_deployment():
    assert prefix_root_path('/static/favicon.png', '/opsmitra') == '/opsmitra/static/favicon.png'


def test_prefix_root_path_does_not_duplicate_prefix():
    assert prefix_root_path('/opsmitra/static/favicon.png', '/opsmitra') == '/opsmitra/static/favicon.png'


def test_prefix_root_path_preserves_root_deployment():
    assert prefix_root_path('/static/favicon.png', '') == '/static/favicon.png'


def test_prefix_root_path_rejects_non_application_path():
    with pytest.raises(ValueError):
        prefix_root_path('static/favicon.png', '/opsmitra')
