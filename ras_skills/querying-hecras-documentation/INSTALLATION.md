# Installation Guide - HEC-RAS Documentation Query Skill

This skill works in two modes:
1. **Visual Mode** (recommended): Full screenshots + text using dev-browser
2. **Text-Only Mode** (fallback): Text extraction using WebFetch

## Quick Check

Test if dev-browser is available:

```bash
node core/fallback_handler.mjs
```

**Output**:
- ✅ Visual mode available → You're all set!
- ❌ Text-only mode → Follow installation instructions below

## Text-Only Mode (No Installation Required)

The skill automatically falls back to text-only mode when dev-browser is unavailable.

**Capabilities**:
- ✅ Smart manual selection
- ✅ Text content extraction
- ✅ URL provision for manual browsing
- ❌ No screenshot capture
- ❌ No image visibility

**Usage**: Just use the skill - it will automatically use text-only mode and provide installation instructions if you want visual mode.

## Visual Mode Setup (dev-browser)

For full functionality with screenshots and visual context, install the dev-browser plugin.

### Prerequisites

- **Node.js**: Version 16+ (check with `node --version`)
- **npm**: Installed with Node.js (check with `npm --version`)
- **Claude Code**: Installed and running

### Installation Steps

#### 1. Install dev-browser Plugin

**Via Claude Code CLI**:
```bash
claude code plugins install dev-browser
```

**Or visit**: https://github.com/SawyerHood/dev-browser

#### 2. Navigate to Plugin Directory

**Windows**:
```powershell
cd %USERPROFILE%\.claude\plugins\cache\dev-browser-marketplace\dev-browser\*\skills\dev-browser
```

**Linux/Mac**:
```bash
cd ~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser
```

**Tip**: Use tab completion or `ls` to find the exact version directory.

#### 3. Install Dependencies

**IMPORTANT**: Use npm on Windows (not bun):

```bash
npm install
```

**Why npm on Windows**: Bun has known issues with Chromium on Windows (crash exitCode=21). Use npm/npx for reliable operation.

#### 4. Start dev-browser Server

```bash
npx tsx scripts/start-server.ts
```

**Expected Output**:
```
dev-browser server started on port 9222
Chromium launched successfully
Ready to accept connections
```

**Keep this terminal open** while using the skill.

#### 5. Verify Installation

In a separate terminal:

```bash
# Check if server is running
curl http://localhost:9222

# Or use the fallback handler
node core/fallback_handler.mjs
```

**Expected**: "dev-browser available and connected"

## Platform-Specific Instructions

### Windows

#### Prerequisites
- Windows 10 or later
- Node.js 16+ from https://nodejs.org
- Visual Studio Build Tools (usually installed with Node.js)

#### Steps
```powershell
# Navigate to plugin directory
cd %USERPROFILE%\.claude\plugins\cache\dev-browser-marketplace\dev-browser\

# Find version directory
dir

# Navigate into version directory (replace * with actual version)
cd *\skills\dev-browser

# Install dependencies (USE NPM, not bun)
npm install

# Start server
npx tsx scripts/start-server.ts
```

#### Troubleshooting Windows

**Issue**: "Port 9222 already in use"

```powershell
# Find process using port 9222
netstat -ano | findstr :9222

# Kill the process (replace <PID> with actual process ID)
taskkill /F /PID <PID>
```

**Issue**: "Chromium crash exitCode=21"

**Solution**: Use npm instead of bun:
```powershell
# Remove node_modules if you used bun
rm -r node_modules

# Reinstall with npm
npm install
npx tsx scripts/start-server.ts
```

### Linux

#### Prerequisites
- Ubuntu 20.04+ (or equivalent)
- Node.js 16+ (`sudo apt install nodejs npm`)
- Chromium dependencies:
  ```bash
  sudo apt install -y \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libnspr4 \
    libnss3
  ```

#### Steps
```bash
# Navigate to plugin directory
cd ~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser

# Install dependencies
npm install

# Start server
npx tsx scripts/start-server.ts
```

#### Troubleshooting Linux

**Issue**: "Chromium dependencies missing"

```bash
# Install all required libraries
sudo apt install -y libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
  libatspi2.0-0 libnspr4 libnss3
```

**Issue**: "Permission denied on port 9222"

```bash
# Use a different port
PORT=9223 npx tsx scripts/start-server.ts

# Update query engine to use new port (edit core/query_engine.mjs)
```

### macOS

#### Prerequisites
- macOS 10.15 (Catalina) or later
- Node.js 16+ (`brew install node`)
- Xcode Command Line Tools (`xcode-select --install`)

#### Steps
```bash
# Navigate to plugin directory
cd ~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser

# Install dependencies
npm install

# Start server
npx tsx scripts/start-server.ts
```

#### Troubleshooting macOS

**Issue**: "Chromium blocked by Gatekeeper"

```bash
# Allow Chromium to run
xattr -cr node_modules/playwright/.local-browsers/chromium-*/chrome-mac/Chromium.app
```

**Issue**: "Port 9222 already in use"

```bash
# Find and kill process
lsof -ti:9222 | xargs kill
```

## Verification

### Test Query

```javascript
import { queryDocumentation } from './core/query_engine.mjs';

const result = await queryDocumentation("Where is the Run Simulation button?");

// Check for screenshot
if (result.screenshot) {
  console.log("✅ Visual mode working!");
  console.log(`Screenshot: ${result.screenshot.path}`);
} else {
  console.log("⚠ Text-only mode (no screenshot)");
}
```

### Run Test Suite

```bash
# Basic tests (selection only)
node tests/run_tests.mjs

# Full tests (requires visual mode)
node tests/run_tests.mjs --full
```

## Common Issues

### Issue: Module not found '@/client.js'

**Cause**: dev-browser not installed or not in correct directory

**Solution**:
1. Verify you're in the correct directory (see step 2 above)
2. Reinstall: `npm install`
3. Check Node.js version: `node --version` (should be 16+)

### Issue: Connection refused on port 9222

**Cause**: Server not running or port blocked

**Solution**:
```bash
# Start the server
npx tsx scripts/start-server.ts

# Verify it's running
curl http://localhost:9222
```

### Issue: Server starts but queries fail

**Cause**: Firewall blocking localhost connections

**Solution**:
- Windows: Allow npx.exe through Windows Firewall
- Linux: Check iptables rules
- macOS: Check System Preferences → Security & Privacy → Firewall

### Issue: Screenshots not captured

**Possible causes**:
1. Page load timeout → Increase timeout in query_engine.mjs
2. Chromium sandbox issues → Try `--no-sandbox` flag (dev-browser config)
3. Cache permission issues → Check `screenshots/cache/` permissions

## Performance Tips

### Speed Up Queries

1. **Enable caching**: Already enabled by default
   ```javascript
   captureScreenshot(page, manual, url, { useCache: true })
   ```

2. **Keep server running**: Don't restart between queries
   - First query: 2-5 seconds
   - Cached queries: 0.5-1 second

3. **Clear old cache**: Periodically clean cache
   ```bash
   node core/screenshot_manager.mjs clear
   ```

### Reduce Memory Usage

dev-browser uses Chromium, which can consume significant memory:

- **Typical usage**: 200-500 MB
- **With multiple tabs**: 500 MB - 1 GB

**To reduce**:
- Restart server periodically
- Clear screenshot cache
- Close other Chromium/Chrome instances

## Running as Background Service

### Linux (systemd)

Create `/etc/systemd/system/dev-browser.service`:

```ini
[Unit]
Description=dev-browser server
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser
ExecStart=/usr/bin/npx tsx scripts/start-server.ts
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable dev-browser
sudo systemctl start dev-browser
sudo systemctl status dev-browser
```

### macOS (launchd)

Create `~/Library/LaunchAgents/com.claude.dev-browser.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.dev-browser</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/npx</string>
        <string>tsx</string>
        <string>scripts/start-server.ts</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/youruser/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Load service:
```bash
launchctl load ~/Library/LaunchAgents/com.claude.dev-browser.plist
launchctl start com.claude.dev-browser
```

### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create Basic Task → "dev-browser server"
3. Trigger: "When I log on"
4. Action: "Start a program"
   - Program: `C:\Program Files\nodejs\npx.cmd`
   - Arguments: `tsx scripts/start-server.ts`
   - Start in: `%USERPROFILE%\.claude\plugins\cache\dev-browser-marketplace\dev-browser\*\skills\dev-browser`
5. Finish

## Uninstallation

### Remove dev-browser Plugin

```bash
claude code plugins uninstall dev-browser
```

### Manual Cleanup

**Windows**:
```powershell
rm -r %USERPROFILE%\.claude\plugins\cache\dev-browser-marketplace
```

**Linux/Mac**:
```bash
rm -rf ~/.claude/plugins/cache/dev-browser-marketplace
```

### Keep Screenshots

Screenshots are stored in `screenshots/cache/` and not removed by plugin uninstallation. To remove:

```bash
rm -rf screenshots/cache/*
```

## Advanced Configuration

### Custom Port

Edit `core/query_engine.mjs` to use a different port:

```javascript
const client = await connect('http://localhost:9223');  // Changed from 9222
```

Then start server with custom port:
```bash
PORT=9223 npx tsx scripts/start-server.ts
```

### Proxy Configuration

If behind a corporate proxy, set environment variables:

```bash
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
npx tsx scripts/start-server.ts
```

### Headless Mode

dev-browser runs headless by default. To see browser window (debugging):

Edit `scripts/start-server.ts`:
```javascript
const browser = await chromium.launch({ headless: false });
```

## Getting Help

### Check Status

```bash
# Check mode
node core/fallback_handler.mjs

# Check server
curl http://localhost:9222

# View cache stats
node core/screenshot_manager.mjs stats

# Run test suite
node tests/run_tests.mjs --verbose
```

### Logs

**dev-browser logs**: Console output where server is running

**Skill logs**: Check Claude Code logs for query execution details

### Support Resources

- **dev-browser GitHub**: https://github.com/SawyerHood/dev-browser
- **Claude Code docs**: https://claude.com/claude-code
- **ras-commander issues**: https://github.com/gpt-cmdr/ras-commander/issues

## Next Steps

After successful installation:

1. ✅ Run test suite: `node tests/run_tests.mjs --full`
2. ✅ Try example queries (see [README.md](README.md))
3. ✅ Check documentation: [SKILL.md](SKILL.md)
4. ✅ Integrate with ras-commander workflows

## Appendix: Directory Structure

```
dev-browser plugin location:
~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/
└── <version>/
    └── skills/
        └── dev-browser/
            ├── scripts/
            │   └── start-server.ts  ← Start script
            ├── node_modules/        ← Dependencies
            └── package.json

HEC-RAS Documentation Query skill:
ras_skills/querying-hecras-documentation/
├── core/                        ← Query engine
├── screenshots/
│   └── cache/                   ← Screenshot cache
├── tests/                       ← Test suite
└── INSTALLATION.md              ← This file
```

## Quick Reference Card

```bash
# Check if dev-browser available
node core/fallback_handler.mjs

# Start dev-browser server
cd ~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser
npx tsx scripts/start-server.ts

# Run test suite
node tests/run_tests.mjs --full

# View cache
node core/screenshot_manager.mjs stats

# Test query
node core/query_engine.mjs "Where is the Run Simulation button?"
```

---

**Installation complete!** Your HEC-RAS Documentation Query skill is ready to use in visual mode.
