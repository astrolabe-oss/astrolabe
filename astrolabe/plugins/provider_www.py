"""
Module Name: provider_www

Description:
Provider for looking up info regarding public internet IPs

License:
SPDX-License-Identifier: Apache-2.0
"""
from typing import Optional
import ipinfo

from astrolabe.providers import ProviderInterface
from astrolabe import constants


class ProviderWWW(ProviderInterface):
    @staticmethod
    def ref() -> str:
        return 'www'

    def __init__(self):
        self.handler = None

    async def init_async(self):
        """Initialize the ipinfo handler asynchronously"""
        # Get token directly from constants.ARGS when needed
        token = getattr(constants.ARGS, 'www_ipinfo_token', None)
        # Initialize the ipinfo client
        self.handler = ipinfo.getHandler(token)
        # The handler is now ready to use

    @staticmethod
    def register_cli_args(argparser):
        argparser.add_argument('--ipinfo-token', metavar='TOKEN',
                               help='API token for ipinfo.io lookups')

    async def lookup_name(self, address: str, _) -> Optional[str]:
        """
        Look up information about a public IP address using ipinfo.io
        Returns a formatted string: "{org} ({region}, {country})"

        Args:
            address: The IP address to look up
            connection: Optional connection object (not used for this provider)

        Returns:
            A formatted string with organization and location info, or None if lookup fails
        """
        try:
            # Check if handler is initialized
            if self.handler is None:
                return None

            # The ipinfo library handles caching, rate limiting, and retries
            details = self.handler.getDetails(address)

            # Get organization, region and country information
            org = getattr(details, 'org', 'Unknown')
            region = getattr(details, 'region', 'Unknown')
            country = getattr(details, 'country_name', None) or getattr(details, 'country', 'Unknown')

            # Format the result string
            result = f"{org} ({region}, {country})"

            return result

        except Exception:  # pylint:disable=broad-exception-caught
            # Return None in case of any error
            return None