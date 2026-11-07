"""Handle physical relocation of asset files from legacy to refgenie1 layout.

Legacy layout:  {genome_folder}/data/{hex_digest}/{asset_name}/{tag}/
Refgenie1 layout: {genome_folder}/data/{ga4gh_digest}/{asset_group}/{content_digest}/
"""

import fnmatch
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TransferMode(Enum):
    COPY = "copy"
    MOVE = "move"
    SYMLINK = "symlink"


@dataclass
class FileTransferPlan:
    source: Path
    destination: Path
    mode: TransferMode
    # Top-level filename rewrites applied on transfer, e.g. mapping legacy-hex
    # stems to the GA4GH digest stem so the rendered alias tree matches native.
    rename_map: dict = field(default_factory=dict)
    # Glob patterns for directory or file names to skip at any depth
    # (e.g. legacy "_refgenie_build", "*.rgsi").
    exclude: list = field(default_factory=list)


@dataclass
class FileTransferResult:
    plan: FileTransferPlan
    success: bool
    error: str | None = None


def plan_asset_transfer(
    source_dir: Path,
    target_dir: Path,
    mode: TransferMode,
    rename_map: dict | None = None,
    exclude: list | None = None,
) -> FileTransferPlan:
    """Plan the file transfer for a single asset tag.

    Args:
        source_dir: The legacy asset directory (absolute path).
        target_dir: The target refgenie1 content directory (absolute path).
        mode: How to transfer the files (copy, move, or symlink).
        rename_map: Optional top-level {old_name: new_name} rewrites, applied so
            legacy-hex-stemmed content files land under the GA4GH digest stem.
        exclude: Optional glob patterns for directory or file names to skip
            (e.g. "_refgenie_build", "*.rgsi").

    Returns:
        FileTransferPlan describing the transfer.
    """
    return FileTransferPlan(
        source=source_dir,
        destination=target_dir,
        mode=mode,
        rename_map=rename_map or {},
        exclude=exclude or [],
    )


def _excluded(name: str, patterns: list) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def iter_transfer_files(
    source: Path, rename_map: dict, exclude: list
) -> Iterator[tuple[Path, Path]]:
    """Yield (source file, destination path relative to the asset dir).

    This is the single definition of what a transfer writes: excluded names are
    dropped at any depth and top-level files are renamed per rename_map.
    execute_transfer writes exactly this set and content_digest hashes it, so
    the two cannot disagree.
    """
    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if not _excluded(d, exclude)]
        rel = Path(os.path.relpath(root, source))
        is_top = rel == Path(".")
        for name in files:
            if _excluded(name, exclude):
                continue
            new_name = rename_map.get(name, name) if is_top else name
            yield Path(root) / name, rel / new_name


@contextmanager
def _scratch_dir(near: Path) -> Iterator[Path]:
    """A temporary folder beside `near` if possible, so hard links to it work."""
    try:
        path = tempfile.mkdtemp(prefix=".refgenie-upgrade-", dir=near)
    except OSError:
        path = tempfile.mkdtemp(prefix="refgenie-upgrade-")
    try:
        yield Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def content_digest(
    source: Path, rename_map: dict | None = None, exclude: list | None = None
) -> str:
    """refgenie1's content digest of an asset as a transfer will lay it out.

    The digest covers each file's relative path and bytes, and skips symlinks.
    So it cannot be taken on the legacy folder (legacy file names) or on a
    symlink-mode transfer (which would hash as empty). Instead, this hard-links
    the renamed, filtered files into a scratch folder (copying when a link is
    not possible) and hashes that with refgenie1's own get_dir_digest. A
    migrated asset then gets the digest refgenie1 gives the same files, so a
    migrated fasta matches the server's and its child assets can be pulled.
    """
    from refgenie.utils.digest import get_dir_digest

    with _scratch_dir(source.parent) as view:
        for src, rel in iter_transfer_files(source, rename_map or {}, exclude or []):
            dst = view / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            real = src.resolve()
            try:
                os.link(real, dst)
            except OSError:
                shutil.copyfile(real, dst)
        return get_dir_digest(view)


def execute_transfer(plan: FileTransferPlan) -> FileTransferResult:
    """Execute a single file transfer.

    Args:
        plan: The transfer plan to execute.

    Returns:
        FileTransferResult indicating success or failure.
    """
    try:
        if not plan.source.exists():
            return FileTransferResult(
                plan=plan,
                success=False,
                error=f"Source does not exist: {plan.source}",
            )

        plan.destination.parent.mkdir(parents=True, exist_ok=True)

        if plan.destination.exists() or plan.destination.is_symlink():
            # Content-addressed destination already holds these files: an
            # idempotent re-run, or a second legacy tag with identical content.
            # A move must still free the source, or that tag's copy stays behind.
            if plan.mode == TransferMode.MOVE:
                _finish_move(plan)
            return FileTransferResult(
                plan=plan,
                success=True,
                error=None,
            )

        # Transfer file-by-file so rename and exclusion apply identically across
        # copy/move/symlink, and so the rendered alias tree (which walks these
        # files) matches the native layout.
        plan.destination.mkdir(parents=True, exist_ok=True)
        for src_file, rel in iter_transfer_files(
            plan.source, plan.rename_map, plan.exclude
        ):
            dst_file = plan.destination / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            if plan.mode == TransferMode.COPY:
                shutil.copy2(src_file, dst_file)
            elif plan.mode == TransferMode.MOVE:
                _move_file(src_file, dst_file)
            elif plan.mode == TransferMode.SYMLINK:
                os.symlink(src_file.resolve(), dst_file)

        return FileTransferResult(plan=plan, success=True)

    except Exception as e:
        return FileTransferResult(
            plan=plan,
            success=False,
            error=f"{type(e).__name__}: {e}",
        )


def _finish_move(plan: FileTransferPlan) -> None:
    """Finish a move into a destination that already exists.

    Per file: if it is already at the destination, the source copy is
    redundant and is deleted; otherwise (an earlier move was interrupted) it is
    moved now. A source file is never deleted without its copy in place.
    """
    for src_file, rel in list(
        iter_transfer_files(plan.source, plan.rename_map, plan.exclude)
    ):
        dst_file = plan.destination / rel
        if dst_file.exists():
            src_file.unlink()
        else:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            _move_file(src_file, dst_file)


def _move_file(src_file: Path, dst_file: Path) -> None:
    """Move one file; a symlink is replaced by the bytes it points to.

    Legacy refgenie links some files across assets by absolute path
    (bwa_index/<d>.fa -> fasta/<d>.fa). Moving the link itself would leave it
    dangling once its target is moved too, so land the real bytes and drop the
    link. content_digest already hashes such files by their target's bytes.
    """
    if src_file.is_symlink():
        shutil.copy2(src_file, dst_file)
        src_file.unlink()
    else:
        shutil.move(str(src_file), str(dst_file))


def resolve_legacy_asset_dir(
    genome_folder: Path,
    hex_digest: str,
    asset_name: str,
    tag_name: str,
    asset_path: str,
) -> Path | None:
    """Resolve the legacy asset directory on disk.

    Handles both standard relative paths and absolute paths (symlinked assets).

    Args:
        genome_folder: The legacy genome_folder path.
        hex_digest: The legacy hex genome digest.
        asset_name: The asset name (e.g. "fasta").
        tag_name: The tag name (e.g. "default").
        asset_path: The asset_path from the legacy config.

    Returns:
        Absolute path to the asset directory, or None if it does not exist.
    """
    # Check if asset_path is absolute (symlinked asset)
    if os.path.isabs(asset_path):
        abs_path = Path(asset_path)
        if abs_path.exists():
            return abs_path
        return None

    # Standard relative path: genome_folder/data/{hex}/{asset_name}/{tag}/
    # The asset_path field is the relative content dir within the tag
    candidate = genome_folder / "data" / hex_digest / asset_name / tag_name
    if candidate.is_dir():
        return candidate

    # Also try without the data/ prefix (older layouts)
    candidate = genome_folder / hex_digest / asset_name / tag_name
    if candidate.is_dir():
        return candidate

    return None
