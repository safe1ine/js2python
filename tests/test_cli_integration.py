import os
import subprocess
from pathlib import Path


def _run_cli(args, cwd: Path):
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(Path("src").resolve()) + (os.pathsep + pythonpath if pythonpath else "")
    result = subprocess.run(
        ["python3", "-m", "cli", *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return result


def test_cli_converts_function(tmp_path):
    output_path = tmp_path / "out.py"
    result = _run_cli(
        ["convert", "tests/cases/function_call.js", "--out", str(output_path)],
        cwd=Path("."),
    )
    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "def add(" in content
    assert "result = add(1, 2)" in content


def test_cli_strict_mode(tmp_path):
    output_path = tmp_path / "strict_out.py"
    result = _run_cli(
        ["convert", "tests/cases/control_if.js", "--out", str(output_path), "--strict"],
        cwd=Path("."),
    )
    assert result.returncode == 0, result.stderr
    assert output_path.exists()


def test_cli_module_mode(tmp_path):
    output_path = tmp_path / "module_out.py"
    result = _run_cli(
        [
            "convert",
            "tests/cases/module_import.js",
            "--module",
            "--out",
            str(output_path),
        ],
        cwd=Path("."),
    )
    assert result.returncode == 0, result.stderr
    content = output_path.read_text(encoding="utf-8")
    assert "from path import join" in content
    assert "import fs" in content
