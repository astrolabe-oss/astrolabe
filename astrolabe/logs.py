"""
Module Name: logs

Description:
Logging!

License:
SPDX-License-Identifier: Apache-2.0
"""

import logging

# logger
logger = logging.getLogger('astrolabe')
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(filename)s:%(funcName)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
