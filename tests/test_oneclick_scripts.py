from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_cross_platform_oneclick_entrypoints_exist() -> None:
    assert (ROOT / "START-NETOPS-WINDOWS.bat").is_file()
    assert (ROOT / "START-NETOPS-LINUX.sh").is_file()
    assert (ROOT / "scripts" / "oneclick-windows.ps1").is_file()
    assert (ROOT / "scripts" / "oneclick-linux.sh").is_file()


def test_linux_oneclick_uses_one_profile_and_starts_all_roles_once() -> None:
    source = (ROOT / "scripts" / "oneclick-linux.sh").read_text(encoding="utf-8")
    assert 'COMBINED_PROFILE="${NETOPS_PROFILE:-netops-all}"' in source
    assert 'configure-harness-dual.sh' in source
    assert 'exec dsh --profile "$COMBINED_PROFILE"' in source
    assert "NETOPS_START_ROLE" not in source
    assert "ROLE_CHOICE" not in source


def test_windows_oneclick_uses_one_profile_and_starts_all_roles_once() -> None:
    source = (ROOT / "scripts" / "oneclick-windows.ps1").read_text(encoding="utf-8-sig")
    assert '$CombinedProfile = $(if ($env:NETOPS_PROFILE)' in source
    assert 'install-harness-dual.ps1' in source
    assert '& $DshCommand --profile $CombinedProfile' in source
    assert "NETOPS_START_ROLE" not in source
    assert "本次启动身份请选择" not in source
    assert 'NETOPS_REMOTE_SSH_TARGET' in source


def test_dual_role_profile_writers_register_two_unique_servers() -> None:
    bash_source = (ROOT / "scripts" / "configure-harness-dual.sh").read_text(encoding="utf-8")
    ps_source = (ROOT / "scripts" / "install-harness-dual.ps1").read_text(encoding="utf-8-sig")
    for source in (bash_source, ps_source):
        assert "mcp-huawei-netops-operator" in source
        assert "mcp-huawei-netops-approver" in source
        assert "huawei_netops_operator" in source
        assert "huawei_netops_approver" in source
        assert "NETOPS_OPERATOR_ROLE" in source
        assert "NETOPS_REQUIRE_DUAL_APPROVAL" in source


def test_linux_oneclick_mock_integration_creates_one_profile_with_both_roles(tmp_path: Path) -> None:
    """Exercise Linux orchestration without installing dependencies or launching real Harness."""
    project = tmp_path / "project"
    shutil.copytree(ROOT / "scripts", project / "scripts")
    shutil.copy2(ROOT / "START-NETOPS-LINUX.sh", project / "START-NETOPS-LINUX.sh")
    (project / ".env").write_text("# fake env for orchestration test\n", encoding="utf-8")
    fake_python = project / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_dsh = fake_bin / "dsh"
    fake_dsh.write_text(
        """#!/usr/bin/env bash
name=''; from=''
for ((i=1;i<=$#;i++)); do
  arg="${!i}"
  case "$arg" in
    --profile) j=$((i+1)); name="${!j}" ;;
    --from-default-profile) j=$((i+1)); from="${!j}" ;;
  esac
done
if [[ -n "$from" ]]; then
  dir="$DSH_HOME/profiles/$name"
  mkdir -p "$dir"
  printf '%s\\n' '{"name":"fake-profile"}' > "$dir/package.json"
  printf '%s\\n' '{"bundles":["@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app"]}' > "$dir/dsh.profile"
  printf '%s\\n' '[]' > "$dir/cordis.patch.yml"
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_dsh.chmod(0o755)

    dsh_home = tmp_path / "dsh-home"
    combined_profile = dsh_home / "profiles" / "netops-all"
    combined_profile.mkdir(parents=True)
    (combined_profile / "cordis.patch.yml").write_text("# user-custom-harness-entry\n[]\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "DSH_HOME": str(dsh_home),
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "NETOPS_NO_LAUNCH": "1",
            "NETOPS_OPERATOR_ID": "operator01",
            "NETOPS_APPROVER_ID": "approver01",
        }
    )
    completed = subprocess.run(
        ["bash", str(project / "START-NETOPS-LINUX.sh")],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    patch = (combined_profile / "cordis.patch.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(patch)
    assert isinstance(parsed, list)
    assert "# user-custom-harness-entry" in patch
    assert "NETOPS_OPERATOR_ID: 'operator01'" in patch
    assert "NETOPS_OPERATOR_ROLE: 'operator'" in patch
    assert "NETOPS_OPERATOR_ID: 'approver01'" in patch
    assert "NETOPS_OPERATOR_ROLE: 'approver'" in patch
    assert "NETOPS_REQUIRE_DUAL_APPROVAL: 'true'" in patch
    inserted = [x for item in parsed if isinstance(item, dict) for x in item.get("insert", [])]
    ids = {x.get("id") for x in inserted if isinstance(x, dict)}
    assert ids == {"mcp-huawei-netops-operator", "mcp-huawei-netops-approver"}
    assert "netops-operator" not in [x.name for x in (dsh_home / "profiles").iterdir()]


def test_dual_role_writer_is_idempotent_on_repeated_runs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "scripts", project / "scripts")
    python3 = shutil.which("python3")
    assert python3
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!{python3}\nimport sys, yaml\nd=yaml.safe_load(open(sys.argv[-1],encoding='utf-8')); assert isinstance(d,list)\n", encoding="utf-8")
    python.chmod(0o755)
    profile_dir = tmp_path / "dsh" / "profiles" / "netops-all"
    profile_dir.mkdir(parents=True)
    patch = profile_dir / "cordis.patch.yml"
    patch.write_text("# user-entry\n[]\n", encoding="utf-8")
    env = os.environ.copy()
    env["DSH_HOME"] = str(tmp_path / "dsh")
    command = ["bash", str(project / "scripts" / "configure-harness-dual.sh"), "netops-all", "op01", "ap01", "true"]
    for _ in range(2):
        result = subprocess.run(command, cwd=project, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
    text = patch.read_text(encoding="utf-8")
    assert text.count("# BEGIN HUAWEI NETOPS MCP BOTH ROLES") == 1
    assert text.count("mcp-huawei-netops-operator") == 1
    assert text.count("mcp-huawei-netops-approver") == 1
    assert "# user-entry" in text
    parsed = yaml.safe_load(text)
    inserted = [child for item in parsed if isinstance(item, dict) for child in item.get("insert", [])]
    assert len(inserted) == 2


def test_dual_role_profile_yaml_uses_one_insert_operation_with_two_plugins(tmp_path: Path) -> None:
    """Exercise the Linux writer directly and inspect its generated Cordis YAML."""
    project = tmp_path / "project"
    shutil.copytree(ROOT / "scripts", project / "scripts")
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(shutil.which("python3") and f"#!{shutil.which('python3')}\nimport sys, yaml\npath=sys.argv[-1]\nd=yaml.safe_load(open(path,encoding='utf-8'))\nassert isinstance(d,list)\n" or "#!/usr/bin/env python3\n", encoding="utf-8")
    python.chmod(0o755)
    profile_dir = tmp_path / "dsh" / "profiles" / "netops-all"
    profile_dir.mkdir(parents=True)
    (profile_dir / "cordis.patch.yml").write_text("[]\n", encoding="utf-8")
    env = os.environ.copy()
    env["DSH_HOME"] = str(tmp_path / "dsh")
    result = subprocess.run(
        ["bash", str(project / "scripts" / "configure-harness-dual.sh"), "netops-all", "op01", "ap01", "true"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = yaml.safe_load((profile_dir / "cordis.patch.yml").read_text(encoding="utf-8"))
    inserts = [item["insert"] for item in parsed if isinstance(item, dict) and "insert" in item]
    assert len(inserts) == 1
    assert len(inserts[0]) == 2
    assert {item["config"]["serverName"] for item in inserts[0]} == {
        "huawei_netops_operator", "huawei_netops_approver"
    }


def test_clean_release_excludes_obsolete_installers_and_sample_profiles():
    obsolete = [
        "doctor-windows.bat", "install-windows.bat",
        "scripts/configure-harness.sh", "scripts/install-harness.ps1",
        "scripts/install.sh", "scripts/netops.ps1", "scripts/start.sh",
        "scripts/start.ps1", "scripts/stop.ps1", "scripts/backup.sh",
        "harness/cordis.patch.local.example.yml",
        "harness/cordis.patch.ubuntu-ssh.example.yml",
    ]
    for relative in obsolete:
        assert not (ROOT / relative).exists(), f"obsolete project file remains: {relative}"


def test_active_linux_entrypoints_use_safe_single_identity_fallback():
    source = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NETOPS_OPERATOR_ROLE=viewer" in source
    assert "NETOPS_REQUIRE_DUAL_APPROVAL=true" in source


def test_runtime_installers_do_not_install_development_only_dependencies():
    linux = (ROOT / "scripts" / "install-core.sh").read_text(encoding="utf-8")
    windows = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8-sig")
    assert 'pip install -e "[dev]"' not in linux
    assert 'pip install -e ".[dev]"' not in linux
    assert "pip install -e ." in linux
    assert "pip install -e ." in windows
