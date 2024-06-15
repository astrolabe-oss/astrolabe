import pytest
from astrolabe import plugin_core


def test_init_case_plugin_subclass_registered():
    """PluginInterface subclasses are automatically registered up and configured"""
    # arrange
    class PluginFamily(plugin_core.PluginInterface):
        pass

    class TestSubclassRegistered(PluginFamily):
        """This is a singleton so that we can spy on it when it is instantiated by plugins::init()"""
        instance = None

        def __new__(cls):
            if cls.instance is None:
                cls.instance = super().__new__(cls)
            return cls.instance

        @staticmethod
        def ref():
            return 'subclassregistered'
    plugin = TestSubclassRegistered()
    plugin_registry = plugin_core.PluginFamilyRegistry(PluginFamily)

    # act
    plugin_registry.register_plugins()

    # assert
    assert plugin == plugin_registry.get_plugin(plugin.ref())


def test_get_case_plugin_present():
    """Tests that a plugin set in init() is get_plugin_by_ref-able by get_plugin_by_ref()"""
    # arrange
    class PluginFamily(plugin_core.PluginInterface):
        pass

    ref = 'subclasspresent'

    class TestPluginPresent(PluginFamily):
        @staticmethod
        def ref():
            return ref
    plugin_registry = plugin_core.PluginFamilyRegistry(PluginFamily)

    # act
    plugin_registry.register_plugins()

    # assert
    assert TestPluginPresent.__name__ == plugin_registry.get_plugin(ref).__class__.__name__


def test_get_case_plugin_absent():
    """When a plugin is requested which is not registered, halt the program"""
    # arrange/act
    plugin_registry = plugin_core.PluginFamilyRegistry([])

    # assert
    with pytest.raises(SystemExit) as e_info:
        plugin_registry.get_plugin('not_present')
    assert 1 == e_info.value.code
