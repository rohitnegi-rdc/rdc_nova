def prefix_root_path(path: str, root_path: str) -> str:
    if not path.startswith('/'):
        raise ValueError('Application paths must start with /.')

    normalized_root = root_path.rstrip('/')
    if not normalized_root or path == normalized_root or path.startswith(f'{normalized_root}/'):
        return path

    return f'{normalized_root}{path}'
