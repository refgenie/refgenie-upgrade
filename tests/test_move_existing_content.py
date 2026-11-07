"""--move into content that is already migrated must still free the source (#3)."""

from pathlib import Path

from refgenie_upgrade.file_mover import TransferMode, execute_transfer, plan_asset_transfer


def _asset(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "idx.1.bt2").write_text("same\n")
    (d / "idx.2.bt2").write_text("same\n")
    return d


def test_second_identical_tag_freed(tmp_path):
    default = _asset(tmp_path, "default")
    v2 = _asset(tmp_path, "v2")
    dest = tmp_path / "content"
    assert execute_transfer(plan_asset_transfer(default, dest, TransferMode.MOVE)).success
    assert execute_transfer(plan_asset_transfer(v2, dest, TransferMode.MOVE)).success
    assert not list(v2.iterdir())
    assert sorted(p.name for p in dest.iterdir()) == ["idx.1.bt2", "idx.2.bt2"]


def test_interrupted_move_is_completed_not_deleted(tmp_path):
    src = _asset(tmp_path, "default")
    dest = tmp_path / "content"
    dest.mkdir()
    (src / "idx.1.bt2").rename(dest / "idx.1.bt2")  # half-done earlier run
    assert execute_transfer(plan_asset_transfer(src, dest, TransferMode.MOVE)).success
    assert (dest / "idx.2.bt2").read_text() == "same\n"
    assert not list(src.iterdir())


def test_copy_and_symlink_never_touch_sources(tmp_path):
    for mode in (TransferMode.COPY, TransferMode.SYMLINK):
        src = _asset(tmp_path / mode.value, "v2")
        dest = tmp_path / mode.value / "content"
        dest.mkdir()
        execute_transfer(plan_asset_transfer(src, dest, mode))
        assert sorted(p.name for p in src.iterdir()) == ["idx.1.bt2", "idx.2.bt2"]
