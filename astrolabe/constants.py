"""
Module Name: constants

Description:
Constants and globals shared across modules

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import pprint

# independent constants
ARGS = None
ASTROLABE_DIR = 'astrolabe.d'
OUTPUTS_DIR = 'outputs'
PROVIDER_SSH = 'ssh'
PROVIDER_HINT = 'hnt'
PROVIDER_SEED = 'seed'
PP = pprint.PrettyPrinter(indent=4)

# dependent constants
LASTRUN_FILE = f"{OUTPUTS_DIR}/.lastrun.json"
