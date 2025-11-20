# Windows setup (PowerShell)

Validated on Windows with Python 3.14.8, Docker Desktop 29.8.2 and Harbor 0.24.0.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

mfgbench tasks list
mfgbench tasks validate
mfgbench smoke --concurrency 3
mfgbench report --format html --output reports\latest.html
Start-Process reports\latest.html
```

If PowerShell blocks activation, use a process-local policy rather than changing machine policy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Docker Desktop and Harbor

1. Install Docker Desktop for Windows and start it.
2. Verify from PowerShell: `docker version` and `docker ps`.
3. Install Harbor in the active environment: `python -m pip install "harbor==0.24.0"`.
4. Verify: `harbor --version`.
5. Run Oracle and NOP:

```powershell
harbor run -p tasks\supplier-reconciliation -a oracle
harbor run -p tasks\supplier-reconciliation -a nop
```

The images use Linux containers. Docker Desktop's default backend is sufficient; no WSL shell commands are required.

## Observed on this host

| Check | Result |
|---|---|
| Python | 3.14.8 |
| Docker | 29.8.2 (Docker Desktop, containerized engine) |
| Harbor | 0.24.0 |
| Native Harbor Oracle | 1.0 on all five tasks |
| Native Harbor NOP | 0.0 on all five tasks |
| Local smoke | 15/15 contracts |
| `pytest` | 21 passed, 1 skipped (POSIX `sh` entrypoint, covered by Harbor/Docker) |

## Notes

- `Capture terminal screenshots` uses `scripts/capture_terminal.py` on Windows with Pillow and Windows Terminal. It is evidence tooling only.
- The local runner does not replace Harbor's container isolation.
- `reports/*.html`, `runs/`, `jobs/` and `.mfgbench/` are local, ignored runtime data.
