"""Reading a legacy FASTA must not write files next to it (#4)."""

from refgenie_upgrade.digest_resolver import _compute_seqcol_digest, fasta_view


def test_digest_leaves_the_fasta_folder_untouched(tmp_path):
    fasta = tmp_path / "legacy" / "phix.fa"
    fasta.parent.mkdir()
    fasta.write_text(">chr1\nACGTACGTAC\n")
    assert _compute_seqcol_digest(fasta)
    assert [p.name for p in fasta.parent.iterdir()] == ["phix.fa"]


def test_view_is_outside_the_fasta_folder_and_cleaned_up(tmp_path):
    fasta = tmp_path / "legacy" / "phix.fa"
    fasta.parent.mkdir()
    fasta.write_text(">chr1\nACGT\n")
    with fasta_view(fasta) as link:
        assert link.read_text() == fasta.read_text()
        assert link.parent != fasta.parent
    assert not link.exists()
