import pytest
from astrolabe import constants
from astrolabe.main import main


@pytest.fixture(autouse=True)
def setup_common_mocks(mocker):
    """Setup all common mocks needed for most tests."""
    # Mock database functions
    mocker.patch('astrolabe.database.init')
    mocker.patch('astrolabe.database.close')

    # Mock plugin loading
    mocker.patch('astrolabe.plugin_core.import_plugin_classes')
    mocker.patch('astrolabe.profile_strategy.init')
    mocker.patch('astrolabe.providers.register_providers')
    mocker.patch('astrolabe.exporters.register_exporters')
    mocker.patch('astrolabe.exporters.parse_exporter_args')
    mocker.patch('astrolabe.exporters.get_exporter_by_ref')
    mocker.patch('astrolabe.providers.parse_provider_args')
    mocker.patch('astrolabe.providers.cleanup_providers')
    mocker.patch('astrolabe.providers.perform_inventory')
    # Mock os.makedirs to prevent filesystem changes
    mocker.patch('os.makedirs')

    # Mock exporters
    mocker.patch('astrolabe.plugins.export_json.dump')

    # Yield to test
    yield

    # Reset any global state
    if hasattr(constants, 'ARGS'):
        del constants.ARGS


def test_inventory_only_skips_discover(mocker):
    """Test that if --inventory-only is set, discover.discover() is not called."""
    # Setup mocks specific to this test
    mock_discover = mocker.patch('astrolabe.discover.discover')

    # Setup mock args
    constants.ARGS = mocker.MagicMock(
        command='discover',
        inventory_only=True,
        disable_providers=[],
        output=['ascii'],
        debug=False,
        quiet=False
    )
    mocker.patch('configargparse.ArgumentParser.parse_known_args', return_value=(constants.ARGS, []))

    # Execute main function
    main()

    # Assert discover.discover was not called
    mock_discover.assert_not_called()