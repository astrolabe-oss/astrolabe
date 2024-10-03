from pathlib import Path
from astrolabe.config import get_config_yaml_files, get_network_yaml_files


def test_get_config_yaml_files(astrolabe_d, core_astrolabe_d, mocker):  # pylint:disable=unused-argument
    '''pathlib.Path.glob is called once for astrolabe core dir, and once for the application dir if it exists.
       Here we check for both calls indirectly...'''
    # arrange
    core_mock_files = [
        Path('/mock/astrolabe.d/config1.yaml'),
        Path('/mock/astrolabe.d/config2.yaml')
    ]
    app_mock_files = [
        Path('/mock/astrolabe.d/config3.yaml')
    ]
    mocker.patch('pathlib.Path.glob', side_effect=[core_mock_files, app_mock_files])
    mocker.patch('pathlib.Path.exists', return_value=True)
    mocker.patch('pathlib.Path.is_dir', return_value=True)

    # act
    result = get_config_yaml_files()

    # assert
    assert result == [
        '/mock/astrolabe.d/config1.yaml',
        '/mock/astrolabe.d/config2.yaml',
        '/mock/astrolabe.d/config3.yaml'
    ]


def test_get_config_yaml_files_no_yaml_files(astrolabe_d, core_astrolabe_d, mocker):  # pylint:disable=unused-argument
    # arrange
    core_mock_files = []
    app_mock_files = []
    mocker.patch('pathlib.Path.glob', side_effect=[core_mock_files, app_mock_files])
    mocker.patch('pathlib.Path.exists', return_value=True)
    mocker.patch('pathlib.Path.is_dir', return_value=True)

    # act
    result = get_config_yaml_files()

    # assert
    assert not result


# pylint:disable=unused-argument
def test_get_config_yaml_files_directory_does_not_exist(astrolabe_d, core_astrolabe_d, mocker):
    """Here we are ensuring that if the application config dir does not exists - it is not checked for files!"""
    # arrange
    core_mock_files = [
        Path('/mock/astrolabe.d/config1.yaml'),
        Path('/mock/astrolabe.d/config2.yaml')
    ]
    app_mock_files = [
        Path('/mock/astrolabe.d/config3.yaml')
    ]
    mocker.patch('pathlib.Path.glob', side_effect=[core_mock_files, app_mock_files])
    mocker.patch('pathlib.Path.exists', return_value=False)
    mocker.patch('pathlib.Path.is_dir', return_value=True)

    # act
    result = get_config_yaml_files()

    # assert
    assert result == [
        '/mock/astrolabe.d/config1.yaml',
        '/mock/astrolabe.d/config2.yaml'
    ]


def test_get_network_yaml_files(astrolabe_d, core_astrolabe_d, mocker):  # pylint:disable=unused-argument
    '''pathlib.Path.glob is called once for astrolabe core dir, and once for the application dir if it exists.
       Here we check for both calls indirectly...'''
    # arrange
    core_mock_files = [
        Path('/mock/astrolabe.d/network.yaml'),
    ]
    app_mock_files = [
        Path('/mock/core/astrolabe.d/network.yaml')
    ]
    mocker.patch('pathlib.Path.glob', side_effect=[core_mock_files, app_mock_files])
    mocker.patch('pathlib.Path.exists', return_value=True)
    mocker.patch('pathlib.Path.is_dir', return_value=True)

    # act
    result = get_network_yaml_files()

    # assert
    assert result == [
        '/mock/astrolabe.d/network.yaml',
        '/mock/core/astrolabe.d/network.yaml'
    ]