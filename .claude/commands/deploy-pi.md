---
description: Compile source files to .pyc and deploy them to the Raspberry Pi
argument-hint: [pi-address] [file ...]
---

Deploy instrument_cluster source files to the Raspberry Pi as bytecode-only (.pyc) using `deploy_pi.sh`.

Arguments: `$ARGUMENTS`

- If the **first** argument looks like an address (an IP like `10.22.33.81` or a hostname like `instrument-cluster.local`), use it as the Pi's address. Otherwise all arguments are file paths and the address defaults to `instrument-cluster.local` — the Pi's DHCP address changes with every image flash, so the mDNS name is preferred. (A re-flash also regenerates the SSH host key; if ssh refuses, run `ssh-keygen -R instrument-cluster.local` and retry.)
- The remaining arguments are file paths relative to `src/instrument_cluster/` (e.g. `signals/delta_signal.py`).
- If **no file paths** are given, deploy **all changed `.py` files** under `src/instrument_cluster/` — tracked files with staged or unstaged modifications; **never untracked files**. Enumerate them with:

  ```bash
  git diff --name-only HEAD -- 'src/instrument_cluster/*.py' | sed 's|^src/instrument_cluster/||'
  ```

  If that list is empty, report that nothing has changed and stop — do not deploy anything.

Run from the repo root. `deploy_pi.sh` defaults to `root@instrument-cluster.local`; pass an explicit address via the `PI_HOST` environment variable:

```bash
PI_HOST="root@<pi-address>" ./deploy_pi.sh <file> [file ...]
```

Afterwards, report whether the service came back up (`systemctl is-active` output is printed by the script). If ssh/scp fails because the rootfs is read-only, remount it first with `ssh root@<pi-address> "mount -o remount,rw /"` and retry, per CLAUDE.md.
