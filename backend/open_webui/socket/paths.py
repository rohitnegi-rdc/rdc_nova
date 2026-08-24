def socketio_path_for_root(root_path: str) -> str:
    if not root_path:
        return '/ws/socket.io'

    if not root_path.startswith('/') or root_path.endswith('/'):
        raise ValueError('ROOT_PATH must start with / and must not end with /.')

    return f'{root_path}/ws/socket.io'
