"""
Module Name: export_pprint

Description:
Exports pprint of the internal data structure tree

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

from astrolabe import constants, node, exporters
from typing import Dict


class ExporterPPrint(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'pprint'

    def export(self, tree: Dict[str, node.Node]):
        constants.PP.pprint(tree)
