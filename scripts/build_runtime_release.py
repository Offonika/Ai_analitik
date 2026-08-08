#!/usr/bin/env python3
"""Build an immutable runtime release from an exact Git commit."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from wb_unit_economics.runtime_release_lock import (
    DEFAULT_RUNTIME_RELEASE_LOCK,
    exclusive_runtime_release_lock,
)

ROOT = Path(__file__).resolve().parents[1]

RELEASE_SITE_MODULE = "shumeyko_release_site.py"
RELEASE_SITE_PTH = "00-shumeyko-release-src.pth"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", default="")
    parser.add_argument(
        "--release-root",
        type=Path,
        default=Path("/opt/shumeyko-releases"),
    )
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    parser.add_argument(
        "--lock-path", type=Path, default=DEFAULT_RUNTIME_RELEASE_LOCK
    )
    return parser.parse_args()


def _run(*command: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_editable_install_artifacts(site_packages: Path) -> list[str]:
    """Drop editable-install hooks that point back at the build worktree.

    Копируемый dev-venv установлен в editable-режиме, поэтому несёт `.pth` с
    абсолютным путём до рабочего каталога сборки. Release bootstrap ставит свой
    `src` первым, но dev-путь остаётся в `sys.path` как fallback: модуль,
    существующий в worktree и отсутствующий в релизе, импортировался бы мимо
    immutable release. Удаляем такие хуки вместе с их finder-модулями.
    """

    removed: list[str] = []
    for pth in sorted(site_packages.glob("__editable__*.pth")):
        pth.unlink()
        removed.append(pth.name)
    for finder in sorted(site_packages.glob("__editable___*_finder.py")):
        finder.unlink()
        removed.append(finder.name)
    return removed


def _install_release_source_bootstrap(venv: Path) -> str:
    """Force the copied venv to import the package from its own release."""

    site_packages = sorted((venv / "lib").glob("python*/site-packages"))
    if len(site_packages) != 1:
        raise SystemExit("Copied runtime venv must contain one site-packages directory")
    _remove_editable_install_artifacts(site_packages[0])
    module = site_packages[0] / RELEASE_SITE_MODULE
    pth = site_packages[0] / RELEASE_SITE_PTH
    module_content = (
        "from pathlib import Path\n"
        "import sys\n\n"
        "release_src = str(Path(__file__).resolve().parents[4] / 'src')\n"
        "if release_src not in sys.path:\n"
        "    sys.path.insert(0, release_src)\n"
    )
    pth_content = "import shumeyko_release_site\n"
    module.write_text(module_content, encoding="utf-8")
    pth.write_text(pth_content, encoding="utf-8")
    return hashlib.sha256(f"{module_content}\0{pth_content}".encode()).hexdigest()


def main() -> int:
    args = parse_args()
    try:
        with exclusive_runtime_release_lock(args.lock_path):
            return _build_release(args)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


def _build_release(args: argparse.Namespace) -> int:
    commit = _run("git", "rev-parse", "--verify", f"{args.commit}^{{commit}}")
    short_commit = commit[:12]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    release_id = args.release_id or f"runtime-{short_commit}-{stamp}"
    release_root = args.release_root.resolve()
    release_dir = release_root / release_id
    venv = args.venv.resolve()
    if release_dir.exists():
        raise SystemExit(f"Release already exists: {release_dir}")
    if not (venv / "bin" / "python").is_file():
        raise SystemExit(f"Python environment not found: {venv}")

    release_root.mkdir(parents=True, exist_ok=True)
    release_root.chmod(0o711)
    with tempfile.TemporaryDirectory(prefix=f".{release_id}-", dir=release_root) as raw:
        staging = Path(raw)
        archive = staging / "source.tar"
        _run(
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            commit,
        )
        archive_sha256 = _sha256(archive)
        app_dir = staging / "app"
        app_dir.mkdir()
        with tarfile.open(archive, "r") as bundle:
            bundle.extractall(app_dir, filter="data")
        (app_dir / "reports").symlink_to(
            Path("/data/shumeyko/prod/reports"),
            target_is_directory=True,
        )
        shutil.copytree(venv, app_dir / ".venv", symlinks=True)
        runtime_bootstrap_sha256 = _install_release_source_bootstrap(
            app_dir / ".venv"
        )

        freeze = _run(str(venv / "bin" / "python"), "-m", "pip", "freeze")
        freeze_path = app_dir / "python-freeze.txt"
        freeze_path.write_text(freeze + "\n", encoding="utf-8")
        freeze_sha256 = _sha256(freeze_path)
        content_sha256 = hashlib.sha256(
            (
                f"{archive_sha256}:{freeze_sha256}:"
                f"{runtime_bootstrap_sha256}"
            ).encode()
        ).hexdigest()
        manifest = {
            "releaseId": release_id,
            "sourceCommit": commit,
            "sourceDirty": False,
            "createdAt": datetime.now(UTC).isoformat(),
            "archiveSha256": archive_sha256,
            "pythonFreezeSha256": freeze_sha256,
            "runtimeBootstrapSha256": runtime_bootstrap_sha256,
            "contentSha256": content_sha256,
        }
        (app_dir / "release-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        archive.unlink()
        os.rename(app_dir, release_dir)

    for path in release_dir.rglob("*"):
        if path.is_symlink():
            continue
        with contextlib.suppress(OSError):
            if path.is_dir() or path.stat().st_mode & 0o111:
                path.chmod(0o555)
            else:
                path.chmod(0o444)
    release_dir.chmod(0o555)
    print(
        f"release={release_dir} sourceCommit={commit} "
        f"contentSha256={content_sha256} sourceDirty=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
