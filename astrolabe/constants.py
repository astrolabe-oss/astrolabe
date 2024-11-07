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
from datetime import datetime, timezone

# independent constants
ARGS = None
OUTPUTS_DIR = 'outputs'
PROVIDER_SSH = 'ssh'
PROVIDER_HINT = 'hnt'
PROVIDER_SEED = 'seed'
PROVIDER_INV = 'inv'
PP = pprint.PrettyPrinter(indent=4)
CURRENT_RUN_TIMESTAMP = datetime.now(timezone.utc)

# dependent constants
LASTRUN_FILE = f"{OUTPUTS_DIR}/.lastrun.json"
