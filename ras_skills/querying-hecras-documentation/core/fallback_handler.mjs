/**
 * fallback_handler.mjs
 *
 * Handles graceful degradation when dev-browser is not available.
 * Provides installation instructions and fallback to text-only methods.
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Check if dev-browser is available and running
 * @returns {Promise<Object>} - { available: boolean, mode: string, message: string }
 */
export async function checkDevBrowser() {
  try {
    // Try to import dev-browser client
    const { connect } = await import('@/client.js').catch(() => null);

    if (!connect) {
      return {
        available: false,
        mode: 'webfetch',
        message: 'dev-browser module not found. Install instructions below.'
      };
    }

    // Try to connect to server
    try {
      const client = await connect('http://localhost:9222', { timeout: 2000 });
      await client.disconnect();

      return {
        available: true,
        mode: 'visual',
        message: 'dev-browser available and connected'
      };
    } catch (connectError) {
      return {
        available: false,
        mode: 'webfetch',
        message: `dev-browser server not running on port 9222. ${connectError.message}`
      };
    }
  } catch (error) {
    return {
      available: false,
      mode: 'webfetch',
      message: `dev-browser check failed: ${error.message}`
    };
  }
}

/**
 * Get installation instructions for dev-browser
 * @returns {string} - Formatted installation instructions
 */
export function getInstallationInstructions() {
  return `
╔═══════════════════════════════════════════════════════════════════════════╗
║                    dev-browser Installation Instructions                  ║
╚═══════════════════════════════════════════════════════════════════════════╝

The HEC-RAS Documentation Query skill works best with dev-browser for visual
documentation (screenshots + images). However, it's not currently available.

OPTION 1: Install dev-browser (Recommended for full visual capability)
────────────────────────────────────────────────────────────────────────────

1. Install the dev-browser plugin for Claude Code:

   See: https://github.com/SawyerHood/dev-browser

   OR install via Claude Code plugin marketplace

2. Navigate to the plugin directory:

   Windows:
   cd %USERPROFILE%\\.claude\\plugins\\cache\\dev-browser-marketplace\\dev-browser\\*\\skills\\dev-browser

   Linux/Mac:
   cd ~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser

3. Install dependencies (IMPORTANT: Use npm, NOT bun on Windows):

   npm install

4. Start the dev-browser server:

   npx tsx scripts/start-server.ts

   Keep this terminal open while using the skill.

5. Verify server is running:

   Open browser to: http://localhost:9222
   OR run: curl http://localhost:9222

OPTION 2: Use Text-Only Mode (Available now, limited features)
────────────────────────────────────────────────────────────────────────────

The skill will automatically fall back to WebFetch for text-only queries:
✅ Extract text content from documentation
✅ Identify relevant manual sections
✅ Provide documentation URLs
❌ No screenshot capture
❌ No image visibility
❌ Limited visual context

To use text-only mode, just proceed with your question. The skill will
handle the fallback automatically.

TROUBLESHOOTING
────────────────────────────────────────────────────────────────────────────

Issue: "Port 9222 already in use"
Solution: Kill existing process:
  Windows: netstat -ano | findstr :9222
           taskkill /F /PID <pid>
  Linux/Mac: lsof -ti:9222 | xargs kill

Issue: "Chromium crash exitCode=21" (Windows)
Solution: Use npm/npx instead of bun:
  npm install
  npx tsx scripts/start-server.ts

Issue: "Module not found"
Solution: Ensure you're in the correct directory and ran npm install

Issue: "Connection refused"
Solution: Verify server is running:
  netstat -ano | findstr :9222  (Windows)
  lsof -i :9222                 (Linux/Mac)

For more details, see:
- INSTALLATION.md in this skill directory
- dev-browser documentation: https://github.com/SawyerHood/dev-browser

╚═══════════════════════════════════════════════════════════════════════════╝
`;
}

/**
 * Fallback query using WebFetch (text-only mode)
 * @param {string} url - Documentation URL
 * @param {string} manual - Manual code
 * @returns {Promise<Object>} - { success: boolean, content: Object, error?: string }
 */
export async function fallbackQuery(url, manual) {
  try {
    // Note: This is a placeholder. In actual Claude Code environment,
    // WebFetch would be called via the tool system, not directly imported.
    // This code shows the structure for integration.

    console.log(`[Fallback Mode] Fetching documentation via WebFetch...`);
    console.log(`URL: ${url}`);

    // In the actual implementation, this would use Claude's WebFetch tool
    // For now, we provide the structure for manual integration

    return {
      success: false,
      content: {
        mode: 'fallback',
        manual,
        url,
        message: 'WebFetch integration pending. See documentation URL above.'
      },
      instructions: `
To retrieve this documentation manually:

1. Visit: ${url}

2. Search for relevant sections using your browser's search (Ctrl+F / Cmd+F)

3. The HEC-RAS documentation is well-organized with a table of contents
   on the left side for easy navigation.

Alternatively, install dev-browser for automatic querying (see instructions above).
      `
    };
  } catch (error) {
    return {
      success: false,
      error: error.message,
      instructions: getInstallationInstructions()
    };
  }
}

/**
 * Get appropriate mode and instructions based on availability
 * @returns {Promise<Object>} - { mode: string, instructions?: string, canProceed: boolean }
 */
export async function getQueryMode() {
  const check = await checkDevBrowser();

  if (check.available) {
    return {
      mode: 'visual',
      canProceed: true,
      message: 'Full visual mode available (screenshots + text)'
    };
  }

  return {
    mode: 'text-only',
    canProceed: true,
    message: 'Text-only mode active. For visual capability, install dev-browser.',
    instructions: getInstallationInstructions()
  };
}

/**
 * Log mode status
 * @param {Object} modeInfo - Mode information from getQueryMode()
 */
export function logModeStatus(modeInfo) {
  const modeIcons = {
    'visual': '📸',
    'text-only': '📝',
    'error': '⚠️'
  };

  const icon = modeIcons[modeInfo.mode] || '❓';

  console.log(`\n${icon} Query Mode: ${modeInfo.mode.toUpperCase()}`);
  console.log(`   ${modeInfo.message}`);

  if (modeInfo.instructions && process.env.VERBOSE) {
    console.log(modeInfo.instructions);
  }

  if (modeInfo.mode === 'text-only' && !process.env.QUIET) {
    console.log('\n   💡 Tip: Install dev-browser for visual documentation');
    console.log('   Run with VERBOSE=1 for installation instructions\n');
  }
}

// CLI interface for testing
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  (async () => {
    console.log('=== dev-browser Availability Check ===\n');

    const check = await checkDevBrowser();
    console.log('Status:', check.available ? '✅ Available' : '❌ Not Available');
    console.log('Mode:', check.mode);
    console.log('Message:', check.message);

    console.log('\n=== Query Mode ===\n');
    const mode = await getQueryMode();
    logModeStatus(mode);

    if (!check.available) {
      console.log('\n=== Installation Instructions ===');
      console.log(getInstallationInstructions());
    }
  })();
}
