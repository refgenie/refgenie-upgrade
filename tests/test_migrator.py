"""Tests for the migrator module."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refgenie_upgrade.config_parser import parse_legacy_config
from refgenie_upgrade.file_mover import TransferMode
from refgenie_upgrade.migrator import MigrationResult, migrate


class TestDryRun:
    """Test dry-run mode with real config files but no file operations."""

    def test_dry_run_v04_no_errors(self, v04_config_path, tmp_path):
        """Dry run with v0.4 config should not raise."""
        result = migrate(
            config_path=v04_config_path,
            target_dir=tmp_path / "target",
            dry_run=True,
        )
        # Should not have hard errors (digest resolution failures are skips, not errors)
        assert isinstance(result, MigrationResult)

    def test_dry_run_v03_no_errors(self, v03_config_path, tmp_path):
        """Dry run with v0.3 config should not raise."""
        result = migrate(
            config_path=v03_config_path,
            target_dir=tmp_path / "target",
            dry_run=True,
        )
        assert isinstance(result, MigrationResult)

    def test_dry_run_does_not_create_files(self, v04_config_path, tmp_path):
        """Dry run should not create the target directory."""
        target = tmp_path / "target"
        migrate(
            config_path=v04_config_path,
            target_dir=target,
            dry_run=True,
        )
        assert not target.exists()

    def test_dry_run_counts_skipped_genomes(self, v04_config_path, tmp_path):
        """Genomes with unresolvable digests should be counted as skipped."""
        with patch(
            "refgenie_upgrade.migrator.resolve_genome_digest",
        ) as mock_resolve:
            from refgenie_upgrade.digest_resolver import DigestResolution

            mock_resolve.return_value = DigestResolution("x" * 48, None, "unresolved")
            result = migrate(
                config_path=v04_config_path,
                target_dir=tmp_path / "target",
                dry_run=True,
            )
            assert result.genomes_skipped > 0
            assert result.genomes_migrated == 0


class TestMissingConfig:
    def test_missing_config_returns_error(self, tmp_path):
        result = migrate(
            config_path=tmp_path / "nonexistent.yaml",
            target_dir=tmp_path / "target",
        )
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower() or "parse" in result.errors[0].lower()


class TestTransferModes:
    """Test that different transfer modes produce correct plans."""

    def test_symlink_is_default(self, v04_config_path, tmp_path):
        """Default transfer mode should be symlink."""
        result = migrate(
            config_path=v04_config_path,
            target_dir=tmp_path / "target",
            dry_run=True,
        )
        for plan in result.transfer_plans:
            assert plan.mode == TransferMode.SYMLINK

    def test_copy_mode(self, v04_config_path, tmp_path):
        result = migrate(
            config_path=v04_config_path,
            target_dir=tmp_path / "target",
            transfer_mode=TransferMode.COPY,
            dry_run=True,
        )
        for plan in result.transfer_plans:
            assert plan.mode == TransferMode.COPY

    def test_move_mode(self, v04_config_path, tmp_path):
        result = migrate(
            config_path=v04_config_path,
            target_dir=tmp_path / "target",
            transfer_mode=TransferMode.MOVE,
            dry_run=True,
        )
        for plan in result.transfer_plans:
            assert plan.mode == TransferMode.MOVE
