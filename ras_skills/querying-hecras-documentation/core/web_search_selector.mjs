/**
 * web_search_selector.mjs
 *
 * Site-constrained web search for intelligent manual selection.
 * Phase 2.5 enhancement: Uses search engine understanding to improve accuracy.
 */

import { getManualInfo } from './manual_selector.mjs';

// HEC-RAS documentation URL pattern
const RASDOCS_URL_PATTERN = /rasdocs\/(\w+)\//;
const RASDOCS_SITE = 'hec.usace.army.mil/confluence/rasdocs';

// Valid manual codes
const VALID_MANUALS = ['rasum', 'r2dum', 'rmum', 'ras1dtechref', 'rasrn', 'raski'];

/**
 * Extract manual code from HEC-RAS Confluence URL
 * @param {string} url - Documentation URL
 * @returns {string|null} - Manual code (rasum, r2dum, etc.) or null
 */
export function extractManualFromUrl(url) {
  const match = url.match(RASDOCS_URL_PATTERN);

  if (!match) {
    return null;
  }

  const manual = match[1];

  // Validate it's a known manual code
  if (!VALID_MANUALS.includes(manual)) {
    return null;
  }

  return manual;
}

/**
 * Score manuals based on search result frequency
 * @param {Array} results - Search results with URLs
 * @returns {Object} - Manual counts and scores
 */
export function scoreManualsByFrequency(results) {
  const manualCounts = {};
  const manualUrls = {};

  // Count occurrences of each manual in results
  for (const result of results) {
    const manual = extractManualFromUrl(result.url || result.link || '');

    if (manual) {
      manualCounts[manual] = (manualCounts[manual] || 0) + 1;

      if (!manualUrls[manual]) {
        manualUrls[manual] = [];
      }

      manualUrls[manual].push({
        url: result.url || result.link,
        title: result.title,
        snippet: result.snippet || result.description || ''
      });
    }
  }

  // Sort by count (descending)
  const sorted = Object.entries(manualCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([manual, count]) => ({
      manual,
      count,
      urls: manualUrls[manual]
    }));

  return {
    manualCounts,
    manualUrls,
    sorted
  };
}

/**
 * Determine confidence level based on result consistency
 * @param {number} topCount - Count for top manual
 * @param {number} totalResults - Total search results
 * @returns {string} - 'high', 'medium', or 'low'
 */
export function determineConfidence(topCount, totalResults) {
  if (totalResults === 0) {
    return 'none';
  }

  const percentage = (topCount / totalResults) * 100;

  // High confidence: Manual appears in 60%+ of results OR 3+ times
  if (percentage >= 60 || topCount >= 3) {
    return 'high';
  }

  // Medium confidence: Manual appears 2 times or 40%+
  if (topCount >= 2 || percentage >= 40) {
    return 'medium';
  }

  // Low confidence: Only appears once or <40%
  return 'low';
}

/**
 * Select manual using site-constrained web search
 * @param {string} question - User's question
 * @param {Object} options - Search options
 * @returns {Promise<Object>} - Manual selection result
 */
export async function webSearchManualSelection(question, options = {}) {
  const {
    topN = 5,
    debug = false,
    webSearchFn = null  // Allow injecting WebSearch function for testing
  } = options;

  console.log(`\n[Web Search] Querying: "${question}"`);

  // Construct site-constrained search query
  const searchQuery = `site:${RASDOCS_SITE} ${question}`;

  if (debug) {
    console.log(`[Web Search] Query: ${searchQuery}`);
  }

  try {
    // Note: In actual Claude Code environment, WebSearch would be available
    // This implementation expects webSearchFn to be passed or WebSearch to be available
    let results;

    if (webSearchFn) {
      // Use injected function (for testing)
      results = await webSearchFn(searchQuery);
    } else {
      // In Claude Code, this would use the WebSearch tool
      // For now, return structure for manual integration
      throw new Error('WebSearch not available. Pass webSearchFn option or integrate with Claude Code WebSearch tool.');
    }

    if (!results || results.length === 0) {
      console.log('[Web Search] No results found');
      return {
        success: false,
        method: 'web-search',
        error: 'No search results found',
        confidence: 'none'
      };
    }

    // Score manuals by frequency
    const scoring = scoreManualsByFrequency(results.slice(0, topN));

    if (scoring.sorted.length === 0) {
      console.log('[Web Search] No valid manual URLs found in results');
      return {
        success: false,
        method: 'web-search',
        error: 'No manual URLs extracted from results',
        confidence: 'none'
      };
    }

    // Get top manual
    const top = scoring.sorted[0];
    const confidence = determineConfidence(top.count, results.slice(0, topN).length);

    if (debug) {
      console.log(`[Web Search] Manual counts:`, scoring.manualCounts);
      console.log(`[Web Search] Top manual: ${top.manual} (${top.count} occurrences)`);
      console.log(`[Web Search] Confidence: ${confidence}`);
    }

    return {
      success: true,
      method: 'web-search',
      manual: top.manual,
      count: top.count,
      confidence,
      allManuals: scoring.sorted,
      topUrls: top.urls,
      query: searchQuery
    };

  } catch (error) {
    console.error(`[Web Search] Error: ${error.message}`);

    return {
      success: false,
      method: 'web-search',
      error: error.message,
      confidence: 'none'
    };
  }
}

/**
 * Hybrid manual selection: Combine web search with keyword fallback
 * @param {string} question - User's question
 * @param {Object} options - Selection options
 * @returns {Promise<Object>} - Manual selection result
 */
export async function hybridManualSelection(question, options = {}) {
  const {
    useWebSearch = true,
    fallbackToKeywords = true,
    keywordSelector = null,  // Function to call for keyword selection
    debug = false
  } = options;

  console.log('\n[Hybrid Selection] Starting...');

  // Always get keyword result (fast, no network)
  let keywordResult = null;

  if (keywordSelector) {
    keywordResult = keywordSelector(question, { debug });

    if (debug) {
      console.log(`[Keyword] Selected: ${keywordResult.manual} (score: ${keywordResult.score})`);
    }
  }

  // If web search disabled or no keyword fallback available, return keyword result
  if (!useWebSearch || !fallbackToKeywords) {
    return {
      ...keywordResult,
      method: 'keyword-only',
      hybridMode: false
    };
  }

  // Try web search
  try {
    const webResult = await webSearchManualSelection(question, options);

    if (!webResult.success) {
      // Web search failed, use keyword fallback
      console.log('[Hybrid] Web search failed, using keyword fallback');

      return {
        ...keywordResult,
        method: 'keyword-fallback',
        webSearchError: webResult.error,
        hybridMode: true
      };
    }

    // Decision logic: Choose between web search and keywords
    if (webResult.confidence === 'high') {
      // Strong web signal - trust it
      console.log(`[Hybrid] High confidence web search, selecting ${webResult.manual}`);

      return {
        manual: webResult.manual,
        method: 'web-search',
        confidence: webResult.confidence,
        score: webResult.count,
        topUrls: webResult.topUrls,
        keywordAlternative: keywordResult,
        hybridMode: true
      };

    } else if (webResult.confidence === 'medium') {
      // Medium web signal - check if keyword agrees
      if (keywordResult && webResult.manual === keywordResult.manual) {
        // Agreement - high confidence
        console.log(`[Hybrid] Web + keyword agreement on ${webResult.manual}`);

        return {
          manual: webResult.manual,
          method: 'web-keyword-agreement',
          confidence: 'high',
          score: webResult.count,
          keywordScore: keywordResult.score,
          topUrls: webResult.topUrls,
          hybridMode: true
        };

      } else if (keywordResult && keywordResult.confidence === 'high') {
        // Conflict - trust keyword if it has high confidence
        console.log(`[Hybrid] Web/keyword conflict, keyword has high confidence, selecting ${keywordResult.manual}`);

        return {
          ...keywordResult,
          method: 'keyword-override',
          webSearchAlternative: webResult,
          hybridMode: true
        };

      } else {
        // Conflict with weak signals - trust web search
        console.log(`[Hybrid] Web/keyword conflict, weak signals, selecting web result ${webResult.manual}`);

        return {
          manual: webResult.manual,
          method: 'web-search-weak',
          confidence: webResult.confidence,
          score: webResult.count,
          keywordAlternative: keywordResult,
          topUrls: webResult.topUrls,
          hybridMode: true
        };
      }

    } else {
      // Low/none web signal - use keyword
      console.log(`[Hybrid] Low web confidence, using keyword result ${keywordResult?.manual}`);

      return {
        ...keywordResult,
        method: 'keyword-fallback',
        webSearchAlternative: webResult,
        hybridMode: true
      };
    }

  } catch (error) {
    // Web search error - use keyword fallback
    console.error(`[Hybrid] Error: ${error.message}`);

    if (keywordResult) {
      return {
        ...keywordResult,
        method: 'keyword-fallback',
        webSearchError: error.message,
        hybridMode: true
      };
    } else {
      throw error;
    }
  }
}

/**
 * Format web search result for display
 * @param {Object} result - Web search result
 * @returns {string} - Formatted output
 */
export function formatWebSearchResult(result) {
  let output = '\n';
  output += '╔═══════════════════════════════════════════════════════════════╗\n';
  output += '║            Web Search Manual Selection                       ║\n';
  output += '╚═══════════════════════════════════════════════════════════════╝\n\n';

  if (!result.success) {
    output += `❌ Web Search Failed\n`;
    output += `   Error: ${result.error}\n`;
    return output;
  }

  const manualInfo = getManualInfo(result.manual);

  output += `✅ Selected Manual: ${result.manual.toUpperCase()}\n`;
  output += `   Name: ${manualInfo.name}\n`;
  output += `   Method: ${result.method}\n`;
  output += `   Confidence: ${result.confidence}\n`;
  output += `   Occurrences: ${result.count} in top results\n\n`;

  if (result.topUrls && result.topUrls.length > 0) {
    output += `🔗 Top URLs:\n`;
    result.topUrls.slice(0, 3).forEach((urlInfo, i) => {
      output += `   ${i + 1}. ${urlInfo.title || '[No title]'}\n`;
      output += `      ${urlInfo.url}\n`;
    });
    output += '\n';
  }

  if (result.allManuals && result.allManuals.length > 1) {
    output += `📊 All Manuals Found:\n`;
    result.allManuals.forEach(m => {
      output += `   - ${m.manual}: ${m.count} occurrences\n`;
    });
  }

  return output;
}

// CLI interface for testing (with mock WebSearch)
if (import.meta.url === `file://${process.argv[1].replace(/\\/g, '/')}`) {
  const question = process.argv.slice(2).join(' ');

  if (!question) {
    console.log('Usage: node web_search_selector.mjs "your question here"');
    console.log('\nExamples:');
    console.log('  node web_search_selector.mjs "What are the known issues with 2D mesh?"');
    console.log('  node web_search_selector.mjs "When was terrain layering added?"');
    console.log('\nNote: Requires WebSearch function to be available or mocked.');
    process.exit(1);
  }

  // Mock WebSearch for testing
  const mockWebSearch = async (query) => {
    console.log('[Mock] WebSearch not available, returning example structure');
    console.log('[Mock] In production, this would use Claude Code WebSearch tool');

    // Return mock structure showing what real results would look like
    return [
      {
        url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/2d-mesh-issues',
        title: 'Known Issues with 2D Mesh Generation',
        snippet: 'Common problems and workarounds...'
      }
    ];
  };

  (async () => {
    try {
      const result = await webSearchManualSelection(question, {
        debug: true,
        webSearchFn: mockWebSearch
      });

      console.log(formatWebSearchResult(result));
    } catch (error) {
      console.error('Error:', error.message);
      process.exit(1);
    }
  })();
}

export { RASDOCS_SITE, VALID_MANUALS };
