import pytest


class TestNode:
    # id()
    @pytest.mark.parametrize('address, aliases, expct', [
        ('ADDY', [], 'ADDY'),
        (None, ['DNSNAME'], 'DNSNAME'),
        (None, [], 'UNKNOWN')
    ])
    def test_debug_id(self, node_fixture, address, aliases, expct):
        """This is what the node.id() format should be"""
        # arrange
        provider = 'PROV'
        node_fixture.provider = provider
        node_fixture.address = address
        node_fixture.aliases = aliases

        # arrange/act/assert
        assert node_fixture.debug_id() == provider + ':' + expct

    def test_debug_id_case_shorten(self, node_fixture):
        """This is what the node.id() format should be"""
        # arrange
        provider = 'PROV'
        address = 'AREALLYREALLYREALLYREALLYREALLYREALLYREALLYREALLYREALLYREALLYLONGADDRESSLONGERTHANEIGHTYCHARS'
        node_fixture.provider = provider
        node_fixture.address = address

        # arrange/act/assert
        assert node_fixture.debug_id() == (provider + ':' + address)[:60] + "..."

    # is_database()
    @pytest.mark.parametrize('port', ['3306', '5432', '9160'])
    def test_is_database_case_database_ports(self, node_fixture, port, mocker):
        """Node is a database from it's port/mux(DB port)"""
        # arrange
        node_fixture.protocol = mocker.patch('astrolabe.network.Protocol', is_database=False)
        node_fixture.protocol_mux = port

        # act/assert
        assert node_fixture.is_database()

    @pytest.mark.parametrize('port', ['11211', '6379'])
    def test_is_database_case_cache_ports(self, port, node_fixture, mocker):
        """Node is a database from it's port/mux(cache port, cache treated as DB here)"""
        # arrange
        node_fixture.protocol = mocker.patch('astrolabe.network.Protocol', is_database=True)
        node_fixture.protocol_mux = port

        # act/assert
        assert node_fixture.is_database()

    @pytest.mark.parametrize('port', ['80', '443', '21', '8080', '8443'])
    def test_is_database_case_nondatabase_ports(self, port, node_fixture, mocker):
        """Node is not a database from non DB ports"""
        # arrange
        node_fixture.protocol = mocker.patch('astrolabe.network.Protocol', is_database=False)
        node_fixture.protocol_mux = port

        # act/assert
        assert not node_fixture.is_database()

    def test_is_database_case_databasey_protocol(self, node_fixture, mocker):
        """Node is a database because it's protocol is defined as such"""
        # arrange
        node_fixture.protocol = mocker.patch('astrolabe.network.Protocol', is_database=True)

        # act/assert
        assert node_fixture.is_database()

    # profile_complete()
    @pytest.mark.parametrize('timestamped,expected', [(None, False), (True, True)])
    def test_profile_complete_case_profile_timestamp(self, timestamped, expected, node_fixture, mocker):
        """Crawl is complete when profile timestamp stamped."""
        # arrange
        node_fixture.name_lookup_complete = mocker.Mock(return_value=True)
        if timestamped:
            node_fixture.set_profile_timestamp()

        # act/assert
        assert node_fixture.profile_complete() == expected

    # name_lookup_complete()
    def test_name_lookup_complete_case_incomplete(self, node_fixture):
        """Name lookup is incomplete with no name and no errors"""
        # arrange
        node_fixture.service_name = None
        node_fixture.errors = {}

        # act/assert
        assert not node_fixture.name_lookup_complete()

    def test_name_lookup_complete_case_name_lookup_failed(self, node_fixture):
        """Name lookup complete if we have name lookup failure in warnings"""
        # arrange
        node_fixture.service_name = None
        node_fixture.errors = {}
        node_fixture.warnings = {'NAME_LOOKUP_FAILED': True}

        # act/assert
        assert node_fixture.name_lookup_complete()

    def test_name_lookup_complete_case_service_name(self, node_fixture):
        """Name lookup complete if we have a name!"""
        # arrange
        node_fixture.service_name = 'stub'
        node_fixture.errors = {}

        # act/assert
        assert node_fixture.name_lookup_complete()

    def test_name_lookup_complete_case_errors(self, node_fixture):
        """Name lookup complete if we have errors"""
        # arrange
        node_fixture.service_name = None
        node_fixture.errors = {'STUB': None}

        # act/assert
        assert node_fixture.name_lookup_complete()
