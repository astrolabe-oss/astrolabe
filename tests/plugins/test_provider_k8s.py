# pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments
"""Unit tests for the ProviderKubernetes"""
import pytest

from kubernetes_asyncio.client.models import V1PodList, V1ServiceList, V1Pod, V1Service
from astrolabe.plugins.provider_k8s import ProviderKubernetes


@pytest.fixture
def k8s_provider(mocker):
    """Returns a ProviderKubernetes instance with mocked API."""
    provider = ProviderKubernetes()
    provider.api = mocker.Mock()
    provider.api.list_service_for_all_namespaces = mocker.AsyncMock()
    provider.api.list_namespaced_pod = mocker.AsyncMock()
    return provider


@pytest.fixture
def k8s_service_factory(mocker):
    """Factory for creating k8s service mocks."""
    def _factory():
        service = mocker.Mock(spec=V1Service)
        service.metadata = mocker.Mock()
        service.metadata.name = "test-service"
        service.spec = mocker.Mock()
        service.spec.selector = {"app": "test-app"}
        service.spec.ports = [mocker.Mock(target_port="8080")]
        return service
    return _factory


@pytest.fixture
def k8s_service(k8s_service_factory):
    return k8s_service_factory()


@pytest.fixture
def pod_fixture_factory(mocker):
    def _factory():
        pod = mocker.Mock(spec=V1Pod)
        pod.metadata = mocker.Mock()
        pod.metadata.name = "test-pod"
        pod.spec = mocker.Mock()
        pod.spec.containers = [mocker.Mock()]
        return pod
    return _factory


@pytest.fixture
def pod_fixture(pod_fixture_factory):
    """Returns a k8s pod mock instance."""
    return pod_fixture_factory()


@pytest.fixture
def pod_list_fixture(mocker, pod_fixture):
    """Returns a k8s pod list with a single pod."""
    pod_list = mocker.Mock(spec=V1PodList)
    pod_list.items = [pod_fixture]
    return pod_list


@pytest.fixture
def k8s_service_list(mocker):
    service_list = mocker.Mock(spec=V1ServiceList)
    return service_list


@pytest.mark.asyncio
@pytest.mark.parametrize('namespace, custom_excluded, allowed', [
    ('allowed-ns', False, True),
    ('kube-system', False, False),
    ('excluded-ns', True, False),
])
async def test_profile_k8s_service_respects_default_excluded_namespaces(
    node_fixture, k8s_provider,
    k8s_service, k8s_service_list,
    pod_list_fixture,
    namespace, custom_excluded, allowed,
    cli_args_mock, mocker
):
    """Test that profile method correctly respects default excluded namespaces when handling k8s services."""
    # Arrange
    cli_args_mock.k8s_exclude_namespaces = [namespace] if custom_excluded else []
    k8s_service.metadata.namespace = namespace
    k8s_service_list.items = [k8s_service]
    # mock the k8s api
    k8s_provider.api.list_service_for_all_namespaces.return_value = k8s_service_list
    k8s_provider.api.list_namespaced_pod.return_value = pod_list_fixture
    # ensure the logic path to profile as service
    mocker.patch('astrolabe.database.node_is_k8s_load_balancer', return_value=False)
    mocker.patch('astrolabe.database.node_is_k8s_service', return_value=True)

    # Act
    result = await k8s_provider.profile(node_fixture, [], None)

    # Assert
    assert len(result) == allowed


@pytest.fixture
def mock_pfs_response(mocker, k8s_provider):
    # Mock exec response to return a result
    mocker.patch('astrolabe.plugins.provider_k8s.parse_profile_strategy_response', return_value=[mocker.MagicMock()])
    k8s_provider.ws_api = mocker.Mock()
    k8s_provider.ws_api.connect_get_namespaced_pod_exec = mocker.AsyncMock(return_value="test response")


@pytest.mark.asyncio
@pytest.mark.parametrize('namespace, custom_excluded, allowed', [
    ('allowed-ns', False, True),
    ('kube-system', False, False),
    ('excluded-ns', True, False),
])
async def test_profile_pod_respects_excluded_namespaces(
        mocker, node_fixture, k8s_provider, pod_fixture,
        pod_list_fixture, namespace, custom_excluded, allowed,
        cli_args_mock, profile_strategy_fixture, mock_pfs_response
):
    """Test that profile method correctly respects excluded namespaces when handling k8s pods."""
    # Arrange
    cli_args_mock.k8s_exclude_namespaces = ["excluded-ns"] if custom_excluded else []
    pod_fixture.metadata.namespace = namespace
    # mock k8s api
    pod_list_fixture.items = [pod_fixture]
    k8s_provider.api.list_pod_for_all_namespaces = mocker.AsyncMock(return_value=pod_list_fixture)
    # ensure the logic path to profile as service
    mocker.patch('astrolabe.database.node_is_k8s_load_balancer', return_value=False)
    mocker.patch('astrolabe.database.node_is_k8s_service', return_value=False)

    # Act
    result = await k8s_provider.profile(node_fixture, [profile_strategy_fixture], None)

    # Assert
    assert len(result) == allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('namespace, custom_excluded, allowed', [
    ('allowed-ns', False, True),
    ('kube-system', False, False),
    ('excluded-ns', True, False),
])
async def test_lookup_name_respects_excluded_namespaces(
        mocker, k8s_provider, pod_fixture, pod_list_fixture,
        namespace, custom_excluded, allowed, cli_args_mock
):
    """Test that lookup_Name method correctly respects excluded namespaces when handling k8s pods."""
    # Arrange
    cli_args_mock.k8s_exclude_namespaces = ["excluded-ns"] if custom_excluded else []
    cli_args_mock.k8s_app_name_label = 'test'
    pod_fixture.metadata.namespace = namespace
    pod_fixture.metadata.labels = {'test': 'foo'}
    # mock k8s api
    pod_list_fixture.items = [pod_fixture]
    k8s_provider.api.list_pod_for_all_namespaces = mocker.AsyncMock(return_value=pod_list_fixture)

    # Act
    result = await k8s_provider.lookup_name('fake_address', None)

    # Assert
    assert bool(result) is allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('namespace, custom_excluded, allowed', [
    ('allowed-ns', False, True),
    ('kube-system', False, False),
    ('excluded-ns', True, False),
])
async def test_sidecar_respects_excluded_namespaces(
        mocker, node_fixture, k8s_provider, pod_fixture,
        pod_list_fixture, namespace, custom_excluded, allowed,
        cli_args_mock, profile_strategy_fixture, mock_pfs_response,
        patch_database
):
    """Test that sidecar method (which calls _sidecar_lookup_hostname)
       correctly respects excluded namespaces when handling k8s pods."""
    # Arrange
    cli_args_mock.k8s_exclude_namespaces = ["excluded-ns"] if custom_excluded else []
    pod_fixture.metadata.namespace = namespace
    pod_fixture.metadata.labels = {'test': 'foo'}
    # mock k8s api
    pod_list_fixture.items = [pod_fixture]
    k8s_provider.api.list_pod_for_all_namespaces = mocker.AsyncMock(return_value=pod_list_fixture)
    # ensure _sidecar_lookup_hostname is called
    mocker.patch('astrolabe.database.get_nodes_pending_dnslookup', return_value={'foo': node_fixture}.items())

    # Act
    await k8s_provider.sidecar('fake_address', None)

    # Assert
    # Verify pods were queried from the allowed namespace
    assert k8s_provider.ws_api.connect_get_namespaced_pod_exec.call_count == allowed
