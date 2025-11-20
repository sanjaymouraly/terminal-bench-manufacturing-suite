# Linux setup

Linux native execution was **not** exercised in this workspace; the commands below follow the same code paths as the verified Windows run and are exercised by GitHub Actions in principle. Treat them as documented, not locally verified.

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv git
# Install Docker Engine using your distribution's official instructions.

git clone <your-fork-url> terminal-bench-manufacturing-tasks
cd terminal-bench-manufacturing-tasks
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

mfgbench toolchain
mfgbench tasks validate
mfgbench smoke --concurrency 3
```

For native Harbor trials:

```bash
python -m pip install "harbor==0.24.0"
docker version
harbor run -p tasks/supplier-reconciliation -a oracle
harbor run -p tasks/supplier-reconciliation -a nop
```

Do not use privileged containers. The task containers run as non-root UID 10001, and the verifier runs in a separate container.

To reproduce the evidence screenshots on Linux, use an operator-controlled terminal capture; the included capture utility is Windows-only.
