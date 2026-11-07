"""Resolve legacy hex genome digests to GA4GH base64url digests.

Uses this package's own static lookup table as the primary resolution method.
Falls back to computing the seqcol digest from a FASTA file if one is
available on disk.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from refgenie_upgrade.digest_map import resolve_legacy_digest


@dataclass
class DigestResolution:
    legacy_hex: str
    ga4gh_digest: str | None
    method: str  # "lookup_table", "fasta_computation", "unresolved"


def _find_fasta_file(genome_folder: Path, hex_digest: str) -> Path | None:
    """Find the FASTA file for a genome in the legacy layout.

    Checks standard legacy layout paths:
    - genome_folder/data/{hex_digest}/fasta/default/{hex_digest}.fa
    - genome_folder/data/{hex_digest}/fasta/default/{hex_digest}.fa.gz
    - genome_folder/{hex_digest}/fasta/default/ (pre-data-dir layout)
    Also tries globbing for any .fa or .fa.gz file in the expected directory.
    """
    candidates = [
        genome_folder / "data" / hex_digest / "fasta" / "default",
        genome_folder / hex_digest / "fasta" / "default",
    ]

    for candidate_dir in candidates:
        if not candidate_dir.is_dir():
            continue
        # Try exact filename first
        exact = candidate_dir / f"{hex_digest}.fa"
        if exact.is_file():
            return exact
        exact_gz = candidate_dir / f"{hex_digest}.fa.gz"
        if exact_gz.is_file():
            return exact_gz
        # Glob for any FASTA file
        for pattern in ("*.fa", "*.fasta", "*.fa.gz", "*.fasta.gz"):
            matches = list(candidate_dir.glob(pattern))
            if len(matches) == 1:
                return matches[0]

    return None


@contextmanager
def fasta_view(fasta_path: Path) -> Iterator[Path]:
    """Yield a symlink to ``fasta_path`` inside a throwaway temp folder.

    gtars writes a ``<stem>.rgsi`` index next to the FASTA path it reads.
    Reading through this link keeps that file out of the legacy genome folder,
    which --symlink and --copy must leave untouched.
    """
    with tempfile.TemporaryDirectory(prefix="refgenie-upgrade-fasta-") as tmp:
        link = Path(tmp) / fasta_path.name
        link.symlink_to(fasta_path.resolve())
        yield link


def _compute_seqcol_digest(fasta_path: Path) -> str | None:
    """Compute the GA4GH seqcol digest from a FASTA file.

    Uses refget/gtars to compute the sequence collection digest.
    Returns None if computation fails.
    """
    try:
        from gtars.refget import RefgetStore

        # Create a temporary store and add the FASTA to compute its digest.
        # This is the same call refgenie1's initialize_genome uses
        # (add_sequence_collection_from_fasta), so the digest is guaranteed to
        # match the one the migrator later registers assets under.
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            store = RefgetStore.on_disk(Path(tmpdir) / "store")
            try:
                store.set_quiet(True)
            except AttributeError:
                pass
            with fasta_view(fasta_path) as fasta_link:
                metadata, _was_new = store.add_sequence_collection_from_fasta(
                    str(fasta_link)
                )
            if metadata is not None and metadata.digest:
                return metadata.digest
    except ImportError:
        pass
    except Exception:
        pass

    return None


def resolve_genome_digest(
    legacy_hex: str,
    genome_folder: Path | None = None,
    aliases: list[str] | None = None,
) -> DigestResolution:
    """Resolve a legacy hex digest to a GA4GH base64url digest.

    Strategy:
    1. Try refgenie1's static lookup table (resolve_legacy_digest)
    2. If not found, look for FASTA file under the genome folder
       and compute the seqcol digest from FASTA
    3. Return unresolved if neither works

    Args:
        legacy_hex: The 48-char hex genome digest from legacy config.
        genome_folder: Path to the legacy genome_folder for FASTA fallback.
        aliases: Alias names for this genome (unused but reserved for future
            lookup strategies).

    Returns:
        DigestResolution with the resolved digest and resolution method.
    """
    # Step 1: lookup table
    ga4gh = resolve_legacy_digest(legacy_hex)
    if ga4gh is not None:
        return DigestResolution(legacy_hex, ga4gh, "lookup_table")

    # Step 2: FASTA computation
    if genome_folder is not None:
        fasta_path = _find_fasta_file(genome_folder, legacy_hex)
        if fasta_path is not None:
            ga4gh = _compute_seqcol_digest(fasta_path)
            if ga4gh is not None:
                return DigestResolution(legacy_hex, ga4gh, "fasta_computation")

    return DigestResolution(legacy_hex, None, "unresolved")
