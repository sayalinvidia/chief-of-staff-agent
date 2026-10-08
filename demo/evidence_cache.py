"""Clear run artifacts, preserving required state and the latest dated daily brief."""
from __future__ import annotations

import shutil
import stat
from datetime import date
from pathlib import Path


PRESERVED_STATE_FILES = frozenset({
    "google_token.json",
    "google_client_secret.json",
    "chief-of-staff-workspace-state.json",
    "second-brain.json",
})


def _check_path(path: Path, workspace: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    if info and (stat.S_ISLNK(info.st_mode) or
                 getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise RuntimeError(f"Refusing workspace cleanup through a linked path: {path}")
    resolved = path.resolve()
    if resolved != path.absolute() or not resolved.is_relative_to(workspace):
        raise RuntimeError(f"Workspace cleanup path must stay inside the workspace: {path}")


def check_evidence_cache(root: Path) -> tuple[list[Path], list[Path], int]:
    """Validate all artifact removals before reset writes or recursive deletion."""
    workspace = root.resolve() / "CoS_Workspace"
    vault = workspace / "CoS_SecondBrain"
    state = workspace / ".chief-of-staff-state"
    briefs = workspace / "DailyBriefs"
    for path in (workspace, vault, state, briefs):
        _check_path(path, workspace)
        if path.exists() and not path.is_dir():
            raise RuntimeError(f"Expected a workspace directory: {path}")

    # Filenames carry the brief date; copying or touching an older file must not
    # make it replace the newest brief. Validate even the file being preserved.
    latest_brief = None
    if briefs.exists():
        for path in sorted(briefs.iterdir()):
            _check_path(path, workspace)
            if path.is_file() and path.suffix.lower() == ".md":
                try:
                    brief_date = date.fromisoformat(path.stem)
                except ValueError:
                    continue
                if brief_date.isoformat() == path.stem:
                    latest_brief = path

    directories, standalone = [], []
    file_count = 0

    def collect(path: Path) -> None:
        nonlocal file_count
        _check_path(path, workspace)
        if path.is_dir():
            directories.append(path)
            pending = [path]
            while pending:
                for child in pending.pop().iterdir():
                    _check_path(child, workspace)
                    if child.is_dir():
                        pending.append(child)
                    elif child.is_file():
                        file_count += 1
                    else:
                        raise RuntimeError(f"Unsupported workspace artifact: {child}")
        elif path.is_file():
            standalone.append(path)
            file_count += 1
        else:
            raise RuntimeError(f"Unsupported workspace artifact: {path}")

    if workspace.exists():
        for path in sorted(workspace.iterdir()):
            if path == briefs and latest_brief is not None:
                for child in sorted(briefs.iterdir()):
                    if child != latest_brief:
                        collect(child)
            elif path not in (vault, state):
                collect(path)
    if state.exists():
        for path in sorted(state.iterdir()):
            _check_path(path, workspace)
            if path.name in PRESERVED_STATE_FILES:
                if not path.is_file():
                    raise RuntimeError(f"Expected a required state file: {path}")
            else:
                collect(path)
    return directories, standalone, file_count


def clear_evidence_cache(root: Path) -> dict:
    """Remove artifacts only; the caller separately restores the baseline vault."""
    directories, standalone, file_count = check_evidence_cache(root)
    # Every target and descendant was checked before any recursive deletion.
    for directory in directories:
        shutil.rmtree(directory)
    for path in standalone:
        path.unlink()
    return {"folders_removed": len(directories), "files_removed": file_count}
