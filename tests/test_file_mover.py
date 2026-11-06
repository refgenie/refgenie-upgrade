"""Tests for the file mover: transferred layout and its content digest."""

import os
from pathlib import Path

import pytest
from refgenie.utils.digest import get_dir_digest

from refgenie_upgrade.file_mover import (
    TransferMode,
    content_digest,
    execute_transfer,
    iter_transfer_files,
    plan_asset_transfer,
)
from refgenie_upgrade.migrator import _LEGACY_EXCLUDE

HEX = "94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4"
GA4GH = "jthDpfNIgzM5AGJlOkRtfnky4rXMBIUP"
FILES = {
    ".fa": ">chrM\nACGT\n",
    ".fa.fai": "chrM\t4\t6\t4\t5\n",
    ".chrom.sizes": "chrM\t4\n",
}


def _legacy_fasta(root: Path) -> Path:
    """A fasta asset as legacy refgenie pulls it: hex-named files plus its
    own .rgsi index and build-log directory."""
    asset = root / "legacy" / "data" / HEX / "fasta" / "default"
    asset.mkdir(parents=True)
    for suffix, text in FILES.items():
        (asset / f"{HEX}{suffix}").write_text(text)
    (asset / f"{HEX}.rgsi").write_text("legacy refgenconf index\n")
    (asset / "_refgenie_build").mkdir()
    (asset / "_refgenie_build" / "log.md").write_text("built\n")
    return asset


def _native_fasta(root: Path) -> Path:
    """The same fasta as refgenie1 lays it out natively."""
    asset = root / "native"
    asset.mkdir()
    for suffix, text in FILES.items():
        (asset / f"{GA4GH}{suffix}").write_text(text)
    return asset


def _rename_map(asset: Path) -> dict:
    return {
        p.name: GA4GH + p.name[len(HEX):]
        for p in asset.iterdir()
        if p.is_file() and p.name.startswith(HEX)
    }


def test_digest_matches_native_layout(tmp_path):
    legacy = _legacy_fasta(tmp_path)
    expected = get_dir_digest(_native_fasta(tmp_path))
    assert content_digest(legacy, _rename_map(legacy), _LEGACY_EXCLUDE) == expected
    # The bug this guards against: hashing the legacy folder as-is.
    assert get_dir_digest(legacy) != expected


def test_digest_reads_through_symlinked_legacy_files(tmp_path):
    legacy = _legacy_fasta(tmp_path)
    store = tmp_path / "elsewhere"
    store.mkdir()
    for p in list(legacy.iterdir()):
        if p.is_file():
            target = store / p.name
            p.rename(target)
            p.symlink_to(target)
    expected = get_dir_digest(_native_fasta(tmp_path))
    assert content_digest(legacy, _rename_map(legacy), _LEGACY_EXCLUDE) == expected


def test_scratch_folder_is_removed(tmp_path):
    legacy = _legacy_fasta(tmp_path)
    before = set(legacy.parent.iterdir())
    content_digest(legacy, _rename_map(legacy), _LEGACY_EXCLUDE)
    assert set(legacy.parent.iterdir()) == before


@pytest.mark.parametrize("mode", list(TransferMode))
def test_transfer_writes_exactly_the_digested_files(tmp_path, mode):
    legacy = _legacy_fasta(tmp_path)
    rename_map = _rename_map(legacy)
    planned = sorted(
        str(rel) for _, rel in iter_transfer_files(legacy, rename_map, _LEGACY_EXCLUDE)
    )
    digest = content_digest(legacy, rename_map, _LEGACY_EXCLUDE)

    dest = tmp_path / "new" / digest
    plan = plan_asset_transfer(legacy, dest, mode, rename_map=rename_map, exclude=_LEGACY_EXCLUDE)
    assert execute_transfer(plan).success

    written = sorted(
        os.path.relpath(Path(r) / f, dest) for r, _, fs in os.walk(dest) for f in fs
    )
    assert written == planned
    assert planned == sorted(f"{GA4GH}{s}" for s in FILES)
    if mode != TransferMode.SYMLINK:
        assert get_dir_digest(dest) == digest
