"""Placeholder asset classes for legacy assets must not shadow real ones (#1)."""

from packaging.version import Version

from refgenie_upgrade.migrator import LEGACY_ASSET_CLASS_VERSION


def test_sorts_below_any_registry_version():
    for registry_version in ("0.0.1", "0.1.0", "1.0.0"):
        assert Version(LEGACY_ASSET_CLASS_VERSION) < Version(registry_version)
