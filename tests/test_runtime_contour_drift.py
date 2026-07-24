from pathlib import Path

from scripts.check_runtime_contour_drift import (
    DROP_IN_UNITS,
    FORBIDDEN_SYSTEMD_ENTRIES,
    REQUIRED_FILES,
    check_runtime_contour_drift,
)


def _materialize_matching_contours(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    systemd_root = tmp_path / "systemd"
    nginx_root = tmp_path / "nginx"
    roots = {"systemd": systemd_root, "nginx": nginx_root}

    for repo_relative, installed_relative in REQUIRED_FILES:
        repo_path = repo_root / repo_relative
        kind, relative = installed_relative.split("/", 1)
        installed_path = roots[kind] / relative
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        installed_path.parent.mkdir(parents=True, exist_ok=True)
        repo_path.write_text(f"{repo_relative}\n", encoding="utf-8")
        installed_path.write_bytes(repo_path.read_bytes())

    for unit in DROP_IN_UNITS:
        repo_drop_in = repo_root / "deploy" / "systemd" / f"{unit}.d" / "tracked.conf"
        installed_drop_in = systemd_root / f"{unit}.d" / "tracked.conf"
        repo_drop_in.parent.mkdir(parents=True, exist_ok=True)
        installed_drop_in.parent.mkdir(parents=True, exist_ok=True)
        repo_drop_in.write_text("[Service]\n", encoding="utf-8")
        installed_drop_in.write_bytes(repo_drop_in.read_bytes())

    return repo_root, systemd_root, nginx_root


def test_runtime_contour_drift_accepts_matching_files(tmp_path: Path) -> None:
    repo_root, systemd_root, nginx_root = _materialize_matching_contours(tmp_path)

    assert (
        check_runtime_contour_drift(
            repo_root=repo_root,
            systemd_root=systemd_root,
            nginx_root=nginx_root,
        )
        == []
    )


def test_runtime_contour_drift_rejects_untracked_and_forbidden_files(
    tmp_path: Path,
) -> None:
    repo_root, systemd_root, nginx_root = _materialize_matching_contours(tmp_path)
    unexpected = systemd_root / f"{DROP_IN_UNITS[0]}.d" / "local.conf"
    unexpected.write_text("[Service]\n", encoding="utf-8")
    forbidden = systemd_root / FORBIDDEN_SYSTEMD_ENTRIES[0]
    forbidden.write_text("[Service]\n", encoding="utf-8")

    issues = check_runtime_contour_drift(
        repo_root=repo_root,
        systemd_root=systemd_root,
        nginx_root=nginx_root,
    )

    assert any("untracked deployed drop-in" in issue for issue in issues)
    assert any("forbidden legacy/test timer entry" in issue for issue in issues)


def test_runtime_contour_drift_rejects_changed_nginx_file(tmp_path: Path) -> None:
    repo_root, systemd_root, nginx_root = _materialize_matching_contours(tmp_path)
    nginx_file = nginx_root / "analitika.offonika.ru.conf"
    nginx_file.write_text("changed\n", encoding="utf-8")

    issues = check_runtime_contour_drift(
        repo_root=repo_root,
        systemd_root=systemd_root,
        nginx_root=nginx_root,
    )

    assert issues == [f"deployed file differs from Git: {nginx_file}"]
