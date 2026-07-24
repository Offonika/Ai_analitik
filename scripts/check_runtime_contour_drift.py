#!/usr/bin/env python3
"""Check deployed runtime contour files against versioned templates."""

from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED_FILES = (
    ("deploy/systemd/shumeiko-web-prod.service", "systemd/shumeiko-web-prod.service"),
    ("deploy/systemd/shumeiko-web-test.service", "systemd/shumeiko-web-test.service"),
    (
        "deploy/systemd/shumeiko-web-prod-health.service",
        "systemd/shumeiko-web-prod-health.service",
    ),
    (
        "deploy/systemd/shumeiko-web-prod-health.timer",
        "systemd/shumeiko-web-prod-health.timer",
    ),
    (
        "deploy/systemd/shumeiko-web-test-health.service",
        "systemd/shumeiko-web-test-health.service",
    ),
    (
        "deploy/systemd/shumeiko-web-test-health.timer",
        "systemd/shumeiko-web-test-health.timer",
    ),
    (
        "deploy/nginx/analitika.offonika.ru.conf",
        "nginx/analitika.offonika.ru.conf",
    ),
    (
        "deploy/nginx/shumeiko.offonika.ru.conf",
        "nginx/shumeiko.offonika.ru.conf",
    ),
)
DROP_IN_UNITS = ("shumeiko-web-prod.service", "shumeiko-web-test.service")
FORBIDDEN_SYSTEMD_ENTRIES = (
    "shumeiko-web.service",
    "shumeiko-web.service.d",
    "shumeiko-test-source-snapshot-archive.service",
    "shumeiko-test-source-snapshot-archive.timer",
)


def _same_bytes(left: Path, right: Path) -> bool:
    return (
        left.is_file()
        and right.is_file()
        and left.read_bytes() == right.read_bytes()
    )


def check_runtime_contour_drift(
    *,
    repo_root: Path,
    systemd_root: Path,
    nginx_root: Path,
) -> list[str]:
    issues: list[str] = []
    deploy_root = repo_root / "deploy"
    installed_roots = {"systemd": systemd_root, "nginx": nginx_root}

    for repo_relative, installed_relative in REQUIRED_FILES:
        repo_path = repo_root / repo_relative
        kind, relative = installed_relative.split("/", 1)
        installed_path = installed_roots[kind] / relative
        if not repo_path.is_file():
            issues.append(f"missing repository template: {repo_relative}")
        elif not installed_path.is_file():
            issues.append(f"missing installed file: {installed_path}")
        elif not _same_bytes(repo_path, installed_path):
            issues.append(f"deployed file differs from Git: {installed_path}")

    for entry in FORBIDDEN_SYSTEMD_ENTRIES:
        path = systemd_root / entry
        if path.exists():
            issues.append(f"forbidden legacy/test timer entry exists: {path}")

    for unit in DROP_IN_UNITS:
        repo_dir = deploy_root / "systemd" / f"{unit}.d"
        installed_dir = systemd_root / f"{unit}.d"
        tracked = {
            path.name: path
            for path in repo_dir.glob("*.conf")
            if path.is_file()
        }
        installed = {
            path.name: path
            for path in installed_dir.glob("*.conf")
            if path.is_file()
        }
        for name, installed_path in sorted(installed.items()):
            repo_path = tracked.get(name)
            if repo_path is None:
                issues.append(f"untracked deployed drop-in: {installed_path}")
            elif not _same_bytes(repo_path, installed_path):
                issues.append(f"deployed drop-in differs from Git: {installed_path}")

    return issues


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare production/test systemd and nginx files with Git without "
            "reading runtime EnvironmentFiles."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--systemd-root",
        type=Path,
        default=Path("/etc/systemd/system"),
    )
    parser.add_argument(
        "--nginx-root",
        type=Path,
        default=Path("/etc/nginx/sites-available"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    issues = check_runtime_contour_drift(
        repo_root=args.repo_root.resolve(),
        systemd_root=args.systemd_root.resolve(),
        nginx_root=args.nginx_root.resolve(),
    )
    if issues:
        print("Runtime contour drift detected:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Runtime contour files match Git; no forbidden entries found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
