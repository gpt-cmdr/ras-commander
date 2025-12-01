# RemoteWorkers.json Configuration Guide

**Purpose:** Secure credential storage for remote HEC-RAS execution workers

**Security:** This file is in `.gitignore` and will NOT be committed to the repository.

---

## Quick Setup

### 1. Copy the template:
```bash
copy RemoteWorkers.json.template RemoteWorkers.json
```

### 2. Edit `RemoteWorkers.json` with your worker details

### 3. Run the notebook - credentials load automatically!

---

## JSON File Format

```json
{
  "workers": [
    {
      "name": "Descriptive Name",
      "hostname": "IP_or_hostname",
      "share_path": "\\\\hostname\\ShareName",
      "username": "your_username",
      "password": "your_password",
      "ras_exe_path": "C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\RAS.exe",
      "session_id": 2,
      "priority": "low",
      "enabled": true
    }
  ]
}
```

---

## Field Descriptions

| Field | Description | Example | Required |
|-------|-------------|---------|----------|
| `name` | Friendly name for the worker | `"Office Workstation"` | Yes |
| `hostname` | IP address or machine name | `"192.168.1.100"` or `"WORKSTATION-01"` | Yes |
| `share_path` | UNC path to network share | `"\\\\192.168.1.100\\RasRemote"` | Yes |
| `username` | Windows username | `"bill"` or `"DOMAIN\\user"` | Yes |
| `password` | Windows password | `"SecurePass123"` | Yes |
| `ras_exe_path` | Full path to RAS.exe on remote machine | `"C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\RAS.exe"` | Yes |
| `session_id` | User session ID (use `query user` to find) | `2` | Yes |
| `priority` | Process priority | `"low"`, `"below normal"`, or `"normal"` | No (default: `"low"`) |
| `enabled` | Whether to use this worker | `true` or `false` | No (default: `true`) |

---

## Finding Session ID

**On the remote machine**, run:
```cmd
query user
```

Output example:
```
USERNAME    SESSIONNAME    ID  STATE
bill        console         2  Active
```

Use the **ID** value (2 in this example) for `session_id`.

**Typical values:**
- Session 2: Most common for single-user workstations
- Session 1: Older Windows or first console session
- Session 3+: Additional RDP sessions

---

## Multiple Workers Example

```json
{
  "workers": [
    {
      "name": "Office PC 1",
      "hostname": "192.168.1.10",
      "share_path": "\\\\192.168.1.10\\RasRemote",
      "username": "bill",
      "password": "pass1",
      "ras_exe_path": "C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\RAS.exe",
      "session_id": 2,
      "enabled": true
    },
    {
      "name": "Office PC 2",
      "hostname": "192.168.1.11",
      "share_path": "\\\\192.168.1.11\\RasRemote",
      "username": "user2",
      "password": "pass2",
      "ras_exe_path": "C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
      "session_id": 2,
      "enabled": true
    },
    {
      "name": "Backup PC (disabled)",
      "hostname": "192.168.1.12",
      "share_path": "\\\\192.168.1.12\\RasRemote",
      "username": "user3",
      "password": "pass3",
      "ras_exe_path": "C:\\Program Files\\HEC\\HEC-RAS\\6.6\\RAS.exe",
      "session_id": 2,
      "enabled": false
    }
  ]
}
```

The notebook will use all workers where `enabled: true`.

---

## Security Best Practices

### ✅ DO:
- Keep `RemoteWorkers.json` local only (it's in `.gitignore`)
- Use strong passwords
- Rotate passwords regularly
- Limit file permissions (Windows: Right-click → Properties → Security)
- Use VPN when accessing remote office networks

### ❌ DON'T:
- Don't commit `RemoteWorkers.json` to git
- Don't share the file publicly
- Don't use weak passwords
- Don't email the file (credentials in plain text)
- Don't store in cloud storage (Dropbox, OneDrive, etc.)

---

## Path Format Notes

### Windows Paths - Use Double Backslashes:
```json
"share_path": "\\\\192.168.1.100\\RasRemote",
"ras_exe_path": "C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\RAS.exe"
```

**Why double backslashes?**
- JSON requires escaping backslashes
- `\\` in JSON becomes `\` in Python
- `\\\\hostname` in JSON becomes `\\hostname` (UNC path) in Python

---

## Troubleshooting

### "RemoteWorkers.json not found"
**Solution:** Copy the template:
```cmd
copy RemoteWorkers.json.template RemoteWorkers.json
```

### JSON Syntax Errors
**Common issues:**
- Missing commas between objects
- Trailing comma after last object
- Unescaped backslashes (use `\\` not `\`)
- Smart quotes instead of straight quotes

**Validate JSON:** Use https://jsonlint.com/ or VS Code's JSON validator

### Wrong Session ID
**Symptoms:** PsExec hangs or timeout

**Solution:**
1. On remote machine: `query user`
2. Find the ID column value
3. Update `session_id` in JSON
4. Restart notebook kernel and reload

---

## Example: Converting from Hardcoded to JSON

**Old notebook code (hardcoded):**
```python
REMOTE_CONFIG = {
    "hostname": "192.168.3.8",
    "password": "Katzen84!!",  # Credentials in notebook!
    # ...
}
```

**New notebook code (JSON):**
```python
import json
with open("RemoteWorkers.json") as f:
    worker_configs = json.load(f)
REMOTE_CONFIG = worker_configs["workers"][0]
# Credentials loaded securely from external file
```

---

## Advanced: Environment Variables

For even more security, use environment variables:

**Set environment variable (PowerShell):**
```powershell
$env:RAS_REMOTE_PASSWORD="YourPassword"
```

**Load in notebook:**
```python
import os
REMOTE_CONFIG["password"] = os.environ.get("RAS_REMOTE_PASSWORD", "")
```

---

## Worker Management

### Temporarily Disable a Worker:
```json
{
  "name": "Slow PC",
  "enabled": false,  # Set to false to skip
  // ...
}
```

### Add New Worker:
Add a new object to the `workers` array with all required fields.

### Remove Worker:
Delete the object from the `workers` array or set `enabled: false`.

---

## File Location

**Where to put RemoteWorkers.json:**
- Same directory as the notebook (`examples/`)
- The notebook looks for it in the current working directory
- Use absolute path if needed: `Path("/path/to/RemoteWorkers.json")`

---

**Template file:** `RemoteWorkers.json.template` (safe to commit)
**Your file:** `RemoteWorkers.json` (in .gitignore, never committed)

**Status:** ✅ Secure credential management implemented!
