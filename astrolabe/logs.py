"""
Module Name: logs

Description:
Logging!

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import logging

# logger
logger = logging.getLogger('astrolabe')
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s.%(filename)s.%(funcName)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
