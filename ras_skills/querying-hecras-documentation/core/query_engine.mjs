/**
 * query_engine.mjs
 *
 * Main query engine for HEC-RAS documentation.
 * Integrates manual selection, dev-browser navigation, content extraction, and screenshots.
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { selectManual, selectManualEnhanced, getManualInfo } from './manual_selector.mjs';
import { checkDevBrowser, fallbackQuery, getQueryMode, logModeStatus } from './fallback_handler.mjs';
import { captureScreenshot, getScreenshotMetadata } from './screenshot_manager.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load URL mappings
const urlMappingsPath = join(__dirname, '../data/url_mappings.json');
const urlMappings = JSON.parse(fs.readFileSync(urlMappingsPath, 'utf8'));

/**
 * Extract content from documentation page
 * @param {Object} page - Playwright page object
 * @returns {Promise<Object>} - { title, text, images, links }
 */
async function extractPageContent(page) {
  const content = await page.evaluate(() => {
    const result = {
      title: document.title,
      text: '',
      images: [],
      links: [],
      sections: []
    };

    // Extract main text content
    const mainContent = document.querySelector('main') ||
                       document.querySelector('.wiki-content') ||
                       document.querySelector('article') ||
                       document.body;

    if (mainContent) {
      result.text = mainContent.innerText.substring(0, 10000); // First 10k chars
    }

    // Extract images with metadata
    const imgElements = document.querySelectorAll('img');
    result.images = Array.from(imgElements).map(img => ({
      src: img.src,
      alt: img.alt || '',
      width: img.naturalWidth,
      height: img.naturalHeight,
      visible: img.offsetWidth > 0 && img.offsetHeight > 0
    })).filter(img => img.visible);

    // Extract section headings
    const headings = document.querySelectorAll('h1, h2, h3, h4');
    result.sections = Array.from(headings).map(h => ({
      level: parseInt(h.tagName[1]),
      text: h.textContent.trim(),
      id: h.id || ''
    }));

    // Extract relevant links
    const linkElements = document.querySelectorAll('a[href]');
    result.links = Array.from(linkElements)
      .map(a => ({
        text: a.textContent.trim(),
        href: a.href
      }))
      .filter(link => link.text.length > 0 && link.text.length < 100)
      .slice(0, 50); // Limit to 50 links

    return result;
  });

  return content;
}

/**
 * Query HEC-RAS documentation using visual mode (dev-browser)
 * @param {string} question - User's question
 * @param {string} manualCode - Manual to query
 * @param {string} url - Documentation URL
 * @param {Object} options - Query options
 * @returns {Promise<Object>} - Query result
 */
async function queryVisualMode(question, manualCode, url, options = {}) {
  const { connect, waitForPageLoad } = await import('@/client.js');

  const client = await connect('http://localhost:9222');
  const page = await client.page('hecras-docs');

  try {
    console.log(`[Visual Mode] Navigating to ${manualCode.toUpperCase()}...`);
    await page.goto(url);
    await waitForPageLoad(page);

    // Extract content
    console.log('[Visual Mode] Extracting content...');
    const content = await extractPageContent(page);

    // Capture screenshot
    console.log('[Visual Mode] Capturing screenshot...');
    const screenshotPath = await captureScreenshot(page, manualCode, url, {
      fullPage: true,
      useCache: true
    });

    const screenshotMeta = getScreenshotMetadata(screenshotPath);

    return {
      success: true,
      mode: 'visual',
      manual: manualCode,
      url,
      content,
      screenshot: {
        path: screenshotPath,
        metadata: screenshotMeta
      },
      timestamp: new Date().toISOString()
    };
  } catch (error) {
    console.error(`[Visual Mode] Error: ${error.message}`);
    throw error;
  } finally {
    await client.disconnect();
  }
}

/**
 * Query HEC-RAS documentation with automatic mode selection
 * @param {string} question - User's question
 * @param {Object} options - Query options
 * @returns {Promise<Object>} - Query result
 */
export async function queryDocumentation(question, options = {}) {
  const {
    manual: forcedManual = null,
    version = 'latest',
    debug = false,
    useWebSearch = false,
    webSearchFn = null
  } = options;

  console.log('\n╔═══════════════════════════════════════════════════════════════╗');
  console.log('║           HEC-RAS Documentation Query                        ║');
  console.log('╚═══════════════════════════════════════════════════════════════╝\n');
  console.log(`Question: "${question}"\n`);

  // Step 1: Check query mode (visual vs text-only)
  const mode = await getQueryMode();
  logModeStatus(mode);

  // Step 2: Select appropriate manual
  let manualCode;
  let manualSelection;

  if (forcedManual) {
    manualCode = forcedManual;
    manualSelection = { manual: forcedManual, score: null, forced: true };
    console.log(`\n[Manual Selection] Forced: ${forcedManual.toUpperCase()}`);
  } else {
    // Use enhanced selection with optional web search
    manualSelection = await selectManualEnhanced(question, { debug, useWebSearch, webSearchFn });
    manualCode = manualSelection.manual;

    console.log(`\n[Manual Selection] Selected: ${manualCode.toUpperCase()}`);
    console.log(`                   Score: ${manualSelection.score}`);
    console.log(`                   Confidence: ${manualSelection.confidence}`);

    if (debug) {
      console.log('\n                   All Scores:');
      for (const [m, score] of Object.entries(manualSelection.scores)) {
        console.log(`                   - ${m}: ${score}`);
      }
    }
  }

  const manualInfo = getManualInfo(manualCode);
  console.log(`                   Name: ${manualInfo.name}`);

  // Step 3: Get URL for selected manual
  const manualData = urlMappings.manuals[manualCode];

  if (!manualData) {
    return {
      success: false,
      error: `Unknown manual code: ${manualCode}`,
      availableManuals: Object.keys(urlMappings.manuals)
    };
  }

  const url = manualData.versions[version] || manualData.url;
  console.log(`\n[URL] ${url}`);

  // Step 4: Execute query based on available mode
  let result;

  try {
    if (mode.mode === 'visual') {
      result = await queryVisualMode(question, manualCode, url, options);
    } else {
      // Fallback to text-only mode
      console.log('\n[Fallback] Using text-only mode...');
      result = await fallbackQuery(url, manualCode);
    }

    // Add manual selection info to result
    result.manualSelection = manualSelection;
    result.manualInfo = manualInfo;
    result.question = question;

    return result;
  } catch (error) {
    console.error(`\n[Error] Query failed: ${error.message}`);

    // Try fallback if visual mode failed
    if (mode.mode === 'visual') {
      console.log('\n[Fallback] Visual mode failed, trying text-only...');
      result = await fallbackQuery(url, manualCode);
      result.manualSelection = manualSelection;
      result.manualInfo = manualInfo;
      result.question = question;
      result.warning = 'Visual mode failed, using fallback';
      return result;
    }

    return {
      success: false,
      error: error.message,
      manual: manualCode,
      url,
      question,
      instructions: mode.instructions
    };
  }
}

/**
 * Format query result for display
 * @param {Object} result - Query result from queryDocumentation()
 * @returns {string} - Formatted text output
 */
export function formatResult(result) {
  let output = '\n';
  output += '╔═══════════════════════════════════════════════════════════════╗\n';
  output += '║                      Query Result                             ║\n';
  output += '╚═══════════════════════════════════════════════════════════════╝\n\n';

  if (!result.success) {
    output += `❌ Query Failed\n`;
    output += `   Error: ${result.error}\n\n`;

    if (result.instructions) {
      output += result.instructions;
    }

    return output;
  }

  output += `✅ Query Successful (${result.mode} mode)\n\n`;
  output += `Question: ${result.question}\n\n`;
  output += `Manual: ${result.manualInfo.name}\n`;
  output += `        ${result.manualInfo.description}\n\n`;
  output += `URL: ${result.url}\n\n`;

  if (result.content) {
    output += `Title: ${result.content.title}\n\n`;

    if (result.content.sections && result.content.sections.length > 0) {
      output += `Sections Found:\n`;
      result.content.sections.slice(0, 10).forEach(section => {
        const indent = '  '.repeat(section.level - 1);
        output += `${indent}- ${section.text}\n`;
      });
      output += '\n';
    }

    if (result.content.images && result.content.images.length > 0) {
      output += `Images: ${result.content.images.length} visible images found\n`;
      result.content.images.slice(0, 5).forEach((img, i) => {
        output += `  ${i + 1}. ${img.alt || '[No alt text]'} (${img.width}x${img.height})\n`;
      });
      output += '\n';
    }

    if (result.content.text) {
      const preview = result.content.text.substring(0, 500);
      output += `Content Preview:\n`;
      output += `${preview}...\n\n`;
    }
  }

  if (result.screenshot) {
    output += `Screenshot: ${result.screenshot.path}\n`;
    output += `            Size: ${result.screenshot.metadata.sizeMB} MB\n`;
    output += `            Age: ${result.screenshot.metadata.ageHours}h\n\n`;
  }

  output += `Timestamp: ${result.timestamp}\n`;

  return output;
}

// CLI interface for testing
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const question = process.argv.slice(2).join(' ');

  if (!question) {
    console.log('Usage: node query_engine.mjs "your question here"');
    console.log('\nExamples:');
    console.log('  node query_engine.mjs "How do I create a 2D mesh?"');
    console.log('  node query_engine.mjs "Where is the Run Simulation button?"');
    console.log('  node query_engine.mjs "What\'s new in HEC-RAS 6.6?"');
    process.exit(1);
  }

  (async () => {
    try {
      const result = await queryDocumentation(question, { debug: true });
      console.log(formatResult(result));

      if (!result.success && result.instructions) {
        console.log('\n' + result.instructions);
      }
    } catch (error) {
      console.error('\nFatal Error:', error.message);
      console.error(error.stack);
      process.exit(1);
    }
  })();
}
