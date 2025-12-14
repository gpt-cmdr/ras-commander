/**
 * search_engine.mjs
 *
 * Smart search engine for HEC-RAS documentation.
 * Phase 2 feature: Combines manual selection with index search for multi-page queries.
 */

import { selectManual, selectMultipleCandidates } from './manual_selector.mjs';
import { searchIndex, loadIndex } from './index_builder.mjs';
import { queryDocumentation } from './query_engine.mjs';
import { fileURLToPath } from 'url';

/**
 * Perform smart search across documentation
 * @param {string} question - User's question
 * @param {Object} options - Search options
 * @returns {Promise<Object>} - Search results with recommendations
 */
export async function smartSearch(question, options = {}) {
  const {
    topN = 5,
    multiPage = false
  } = options;

  console.log('\n=== Smart Search ===');
  console.log(`Question: "${question}"`);

  // Step 1: Manual selection (primary)
  const primaryManual = selectManual(question, { debug: false });
  console.log(`\nPrimary Manual: ${primaryManual.manual} (score: ${primaryManual.score})`);

  // Step 2: Index search (supplementary)
  const indexResults = searchIndex(question, { topN });
  console.log(`\nIndex Search: Found ${indexResults.length} relevant sections`);

  // Step 3: Get candidate manuals
  const candidates = selectMultipleCandidates(question, 3);
  console.log(`\nCandidate Manuals:`);
  candidates.forEach((c, i) => {
    console.log(`  ${i + 1}. ${c.info.short_name} (score: ${c.score})`);
  });

  // Step 4: Combine results
  const combined = {
    question,
    primaryManual: {
      code: primaryManual.manual,
      score: primaryManual.score,
      confidence: primaryManual.confidence
    },
    indexResults: indexResults.map(r => ({
      manual: r.manual,
      manualName: r.manualName,
      section: r.section,
      score: r.score,
      keywords: r.keywords
    })),
    candidateManuals: candidates.map(c => ({
      manual: c.manual,
      name: c.info.name,
      score: c.score
    })),
    recommendation: {
      primary: primaryManual.manual,
      also_check: indexResults
        .filter(r => r.manual !== primaryManual.manual)
        .slice(0, 2)
        .map(r => ({ manual: r.manual, section: r.section }))
    }
  };

  return combined;
}

/**
 * Execute multi-page query (retrieves information from multiple sections)
 * @param {string} question - User's question
 * @param {Object} options - Query options
 * @returns {Promise<Object>} - Combined results from multiple pages
 */
export async function multiPageQuery(question, options = {}) {
  const {
    maxPages = 3
  } = options;

  console.log('\n=== Multi-Page Query ===');
  console.log(`Question: "${question}"`);
  console.log(`Max Pages: ${maxPages}\n`);

  // Get search recommendations
  const search = await smartSearch(question, { topN: maxPages });

  // Query primary manual
  console.log('\n--- Querying Primary Manual ---');
  const primaryResult = await queryDocumentation(question, {
    manual: search.primaryManual.code
  });

  const results = {
    question,
    pages: [
      {
        source: 'primary',
        manual: search.primaryManual.code,
        result: primaryResult
      }
    ],
    search: search
  };

  // Query additional relevant sections if multi-page is needed
  const additionalSections = search.indexResults
    .filter(r => r.manual !== search.primaryManual.code)
    .slice(0, maxPages - 1);

  for (const section of additionalSections) {
    console.log(`\n--- Querying ${section.manualName}: ${section.section} ---`);

    try {
      const result = await queryDocumentation(
        `${question} (${section.section})`,
        { manual: section.manual }
      );

      results.pages.push({
        source: 'supplementary',
        manual: section.manual,
        section: section.section,
        result: result
      });
    } catch (error) {
      console.error(`Error querying ${section.manual}: ${error.message}`);
    }
  }

  return results;
}

/**
 * Format search results for display
 * @param {Object} searchResults - Results from smartSearch()
 * @returns {string} - Formatted output
 */
export function formatSearchResults(searchResults) {
  let output = '\n';
  output += '╔═══════════════════════════════════════════════════════════════╗\n';
  output += '║                   Smart Search Results                        ║\n';
  output += '╚═══════════════════════════════════════════════════════════════╝\n\n';

  output += `Question: "${searchResults.question}"\n\n`;

  output += `📘 Primary Manual: ${searchResults.primaryManual.code.toUpperCase()}\n`;
  output += `   Confidence: ${searchResults.primaryManual.confidence}\n`;
  output += `   Score: ${searchResults.primaryManual.score}\n\n`;

  if (searchResults.indexResults.length > 0) {
    output += `🔍 Relevant Sections Found:\n\n`;
    searchResults.indexResults.forEach((result, i) => {
      output += `   ${i + 1}. [${result.manual}] ${result.section}\n`;
      output += `      Manual: ${result.manualName}\n`;
      output += `      Score: ${result.score}\n`;
      output += `      Keywords: ${result.keywords.slice(0, 5).join(', ')}\n\n`;
    });
  }

  if (searchResults.recommendation.also_check.length > 0) {
    output += `💡 Also Check:\n`;
    searchResults.recommendation.also_check.forEach(rec => {
      output += `   - ${rec.manual.toUpperCase()}: ${rec.section}\n`;
    });
    output += '\n';
  }

  return output;
}

// CLI interface for testing
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const question = process.argv.slice(2).join(' ');

  if (!question) {
    console.log('Usage: node search_engine.mjs "your question here"');
    console.log('\nExamples:');
    console.log('  node search_engine.mjs "How do I create a 2D mesh?"');
    console.log('  node search_engine.mjs "What is the complete workflow for dam breach modeling?"');
    process.exit(1);
  }

  (async () => {
    const results = await smartSearch(question, { topN: 5 });
    console.log(formatSearchResults(results));
  })();
}
