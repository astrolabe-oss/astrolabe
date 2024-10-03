from pathlib import Path

ROOT_DIR = Path.cwd()
ASTROLABE_DIR = ROOT_DIR / 'astrolabe.d'
CORE_ASTROLABE_DIR = Path(__file__).resolve().parent.parent / 'astrolabe.d'


def get_config_yaml_files():
    """
    Return full paths of all .yaml files from CORE_ASTROLABE_DIR and ASTROLABE_DIR

    :return: A list of full paths for files ending with .yaml
    """
    yaml_files = []

    for file in CORE_ASTROLABE_DIR.glob('*.yaml'):
        yaml_files.append(str(file))  # Append full path as a string

    # Check if custom ASTROLABE_DIR exists and is a directory
    if ASTROLABE_DIR.exists() and ASTROLABE_DIR.is_dir():
        for file in ASTROLABE_DIR.glob('*.yaml'):
            yaml_files.append(str(file))  # Append full path as a string

    return yaml_files


def get_network_yaml_files():
    """
    Return full paths of all network.yaml files from CORE_ASTROLABE_DIR and ASTROLABE_DIR.

    :return: A list of full paths for network.yaml files
    """
    yaml_files = []

    for file in CORE_ASTROLABE_DIR.glob('network.yaml'):
        yaml_files.append(str(file))  # Append full path as a string

    # Check if custom ASTROLABE_DIR exists and is a directory
    if ASTROLABE_DIR.exists() and ASTROLABE_DIR.is_dir():
        for file in ASTROLABE_DIR.glob('network.yaml'):
            yaml_files.append(str(file))  # Append full path as a string

    return yaml_files
