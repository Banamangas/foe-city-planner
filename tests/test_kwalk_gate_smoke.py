import subprocess
import sys


def test_gate_cli_help_lists_subcommands():
    out = subprocess.run([sys.executable, "scripts/kwalk_gate.py", "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "train" in out.stdout and "walk" in out.stdout
