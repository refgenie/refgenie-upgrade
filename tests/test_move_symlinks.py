"""--move must not leave dangling links behind (#2)."""

from refgenie_upgrade.file_mover import TransferMode, execute_transfer, plan_asset_transfer

HEX = "94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4"


def test_move_lands_link_target_bytes(tmp_path):
    """A legacy bwa_index holds <hex>.fa as an absolute link to the fasta asset."""
    fasta = tmp_path / "data" / HEX / "fasta" / "default"
    bwa = tmp_path / "data" / HEX / "bwa_index" / "default"
    fasta.mkdir(parents=True)
    bwa.mkdir(parents=True)
    (fasta / f"{HEX}.fa").write_text(">chrM\nACGT\n")
    (bwa / f"{HEX}.fa.bwt").write_text("bwt\n")
    (bwa / f"{HEX}.fa").symlink_to((fasta / f"{HEX}.fa").resolve())

    dest = tmp_path / "new" / "bwa"
    assert execute_transfer(plan_asset_transfer(bwa, dest, TransferMode.MOVE)).success

    landed = dest / f"{HEX}.fa"
    assert landed.is_file() and not landed.is_symlink()
    assert landed.read_text() == ">chrM\nACGT\n"
    assert not (bwa / f"{HEX}.fa").exists()  # link removed from the source
    assert (fasta / f"{HEX}.fa").exists()  # its target is left for its own asset
