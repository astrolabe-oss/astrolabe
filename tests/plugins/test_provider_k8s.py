# pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments
"""Unit tests for the ProviderKubernetes"""
import pytest

from kubernetes_asyncio.client.models import V1PodList, V1ServiceList, V1Pod, V1Service
from astrolabe.plugins import provider_k8s
from astrolabe.node import NodeType


@pytest.fixture(autouse=True)
def clear_pod_cache():
    provider_k8s.pod_cache = {}


@pytest.fixture
def k8s_provider(mocker):
    """Returns a ProviderKubernetes instance with mocked API."""
    provider = provider_k8s.ProviderKubernetes()
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


@pytest.mark.parametrize('node_type,node_cluster,prov_cluster,qualifies', [
    (NodeType.DEPLOYMENT, 'cluster1', 'cluster1', True),
    (NodeType.DEPLOYMENT, 'cluster1', 'cluster2', False),
    (NodeType.TRAFFIC_CONTROLLER, 'cluster1', 'cluster1', True),
    (NodeType.TRAFFIC_CONTROLLER, 'cluster1', 'cluster2', False),
    (NodeType.RESOURCE, 'doesntmatter', 'doesntmatter', False),
    (NodeType.COMPUTE, 'cluster1', 'cluster1', True),
])
@pytest.mark.asyncio
async def test_qualify_node_standard_paths(k8s_provider, node_fixture, prov_cluster,
                                           node_cluster, node_type, qualifies):
    """Test qualify_node for standard pathways"""
    # Arrange
    node_fixture.cluster = node_cluster
    node_fixture.node_type = node_type
    k8s_provider._cluster_name = prov_cluster  # pylint:disable=protected-access

    # Act
    provider_qualified = await k8s_provider.qualify_node(node_fixture)

    # Assert
    assert provider_qualified == qualifies


@pytest.mark.parametrize('node_address,pod_cache,qualifies', [
    (None, {'does_not_matter': 'does_not_matter'}, False),
    ('foo', {'foo': 'bar'}, True),
    ('foo', {'cats': 'dogs'}, False),
    ('foo', {}, False)
])
@pytest.mark.asyncio
async def test_qualify_node_check_pod_cache_podname(k8s_provider, node_fixture, node_address, pod_cache, qualifies):
    """Check if we have cached the pod by name in our local cache.  We consider the pod name to be Node.address
       in astrolabeland."""
    # Arrange
    node_fixture.cluster = None
    node_fixture.node_type = NodeType.COMPUTE
    node_fixture.address = node_address
    node_fixture.ipaddrs = None
    k8s_provider._cluster_name = 'does_not_matter'  # pylint:disable=protected-access
    # don't be confused... setting pod cache on the module not the object!
    provider_k8s.pod_cache = pod_cache

    # Act
    provider_qualified = await k8s_provider.qualify_node(node_fixture)

    # Assert
    assert provider_qualified == qualifies


@pytest.mark.parametrize('node_ipaddrs,pod_cache_ip,qualifies', [
    (None, 'does_not_matter', False),
    (['1.2.3.4', '5,6,7,8'], '1.2.3.4', True),
    (['1.2.3.4', '5,6,7,8'], '4.3.2.1', False),
])
@pytest.mark.asyncio
async def test_qualify_node_check_pod_ips(k8s_provider, mocker, node_fixture, node_ipaddrs, pod_cache_ip, qualifies):
    """Test qualify_cluster returns True and sets cluster name when cluster name exists."""
    # Arrange
    node_fixture.cluster = None
    node_fixture.node_type = NodeType.COMPUTE
    node_fixture.ipaddrs = node_ipaddrs
    k8s_provider._cluster_name = 'does_not_matter'  # pylint:disable=protected-access
    provider_k8s.pod_cache = {'a_pod': mocker.Mock(**{'status.pod_ip': pod_cache_ip})}
    # ensure we don't check the pod cache by address/pod name
    node_fixture.address = None

    # Act
    provider_qualified = await k8s_provider.qualify_node(node_fixture)

    # Assert
    assert provider_qualified == qualifies
