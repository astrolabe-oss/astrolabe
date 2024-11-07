"""
Module Name: export_pprint

Description:
Exports pprint of the internal data structure tree

License:
SPDX-License-Identifier: Apache-2.0
"""

from typing import Dict

from astrolabe import constants, node, exporters


class ExporterPPrint(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'pprint'

    def export(self, tree: Dict[str, node.Node]):
        constants.PP.pprint(tree)
