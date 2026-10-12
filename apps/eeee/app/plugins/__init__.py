from app.plugins.catalog import PluginCatalog, PluginCatalogEntry
from app.plugins.manifest import discover_manifest
from app.plugins.models import PluginAction, PluginHealth, PluginManifest, PluginPermission, PluginStatus

__all__ = [
    "PluginAction", "PluginCatalog", "PluginCatalogEntry", "PluginHealth", "PluginHost", "PluginManifest", "PluginPermission",
    "PluginStatus", "discover_manifest",
]


def __getattr__(name: str):
    # Keep the package exports compatible without importing PluginHost while
    # runtime.store is still importing plugin connection contracts.
    if name == "PluginHost":
        from app.plugins.host import PluginHost

        return PluginHost
    raise AttributeError(name)
