/**
 * manual_selector.mjs
 *
 * Smart manual selection using weighted keyword scoring.
 * Analyzes question text to determine which HEC-RAS manual is most relevant.
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load keyword mappings
const keywordMappingsPath = join(__dirname, '../data/keyword_mappings.json');
const keywordMappings = JSON.parse(fs.readFileSync(keywordMappingsPath, 'utf8'));

/**
 * Normalize synonyms in question text
 * @param {string} text - Question text
 * @returns {string} - Text with synonyms expanded
 */
function normalizeSynonyms(text) {
  const lowerText = text.toLowerCase();
  let normalized = lowerText;

  for (const [term, synonyms] of Object.entries(keywordMappings.synonyms)) {
    for (const synonym of synonyms) {
      // Replace synonym with main term (add both to increase matching)
      const regex = new RegExp(`\\b${synonym}\\b`, 'gi');
      normalized = normalized.replace(regex, `${synonym} ${term}`);
    }
  }

  return normalized;
}

/**
 * Score a manual based on keyword matches in question
 * @param {string} question - User's question
 * @param {string} manual - Manual code (rasum, r2dum, etc.)
 * @returns {number} - Weighted score for this manual
 */
function scoreManual(question, manual) {
  const lowerQ = question.toLowerCase();
  const normalizedQ = normalizeSynonyms(lowerQ);
  let score = 0;

  // High-weight keywords
  if (keywordMappings.high_weight[manual]) {
    for (const [phrase, weight] of keywordMappings.high_weight[manual]) {
      if (normalizedQ.includes(phrase.toLowerCase())) {
        score += weight;
        // Bonus for exact phrase match vs just word match
        if (lowerQ.includes(phrase.toLowerCase())) {
          score += weight * 0.2;
        }
      }
    }
  }

  // Medium-weight keywords
  if (keywordMappings.medium_weight[manual]) {
    for (const [phrase, weight] of keywordMappings.medium_weight[manual]) {
      if (normalizedQ.includes(phrase.toLowerCase())) {
        score += weight;
      }
    }
  }

  // UI keywords (special case)
  if (keywordMappings.ui_keywords[manual]) {
    for (const [phrase, weight] of keywordMappings.ui_keywords[manual]) {
      if (normalizedQ.includes(phrase.toLowerCase())) {
        score += weight;
      }
    }
  }

  // Workflow keywords boost (applies to all manuals)
  const isWorkflowQuestion = keywordMappings.workflow_keywords.some(
    keyword => normalizedQ.includes(keyword.toLowerCase())
  );
  if (isWorkflowQuestion && manual === 'rasum') {
    score += 3; // User's Manual preferred for workflows
  }

  return score;
}

/**
 * Select the most appropriate manual for a question
 * @param {string} question - User's question
 * @param {Object} options - Optional configuration
 * @returns {Object} - { manual: string, score: number, scores: Object }
 */
export function selectManual(question, options = {}) {
  const {
    defaultManual = 'rasum',
    minScoreThreshold = 2,
    debug = false
  } = options;

  // Score all manuals
  const manuals = ['rasum', 'r2dum', 'rmum', 'ras1dtechref', 'rasrn', 'raski'];
  const scores = {};

  for (const manual of manuals) {
    scores[manual] = scoreManual(question, manual);
  }

  // Find highest scoring manual
  let bestManual = defaultManual;
  let bestScore = scores[defaultManual] || 0;

  for (const [manual, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      bestManual = manual;
    }
  }

  // If best score is below threshold, use default
  if (bestScore < minScoreThreshold) {
    bestManual = defaultManual;
  }

  if (debug) {
    console.log('Manual Selection Debug:');
    console.log('Question:', question);
    console.log('Scores:', scores);
    console.log('Selected:', bestManual, `(score: ${bestScore})`);
  }

  return {
    manual: bestManual,
    score: bestScore,
    scores: scores,
    confidence: bestScore >= minScoreThreshold ? 'high' : 'low'
  };
}

/**
 * Get manual name and description
 * @param {string} manualCode - Manual code (rasum, r2dum, etc.)
 * @returns {Object} - { code, name, description }
 */
export function getManualInfo(manualCode) {
  const urlMappingsPath = join(__dirname, '../data/url_mappings.json');
  const urlMappings = JSON.parse(fs.readFileSync(urlMappingsPath, 'utf8'));

  const manual = urlMappings.manuals[manualCode];

  if (!manual) {
    return {
      code: manualCode,
      name: 'Unknown Manual',
      description: ''
    };
  }

  return {
    code: manualCode,
    name: manual.name,
    short_name: manual.short_name,
    description: manual.description
  };
}

/**
 * Select multiple candidate manuals for complex queries
 * @param {string} question - User's question
 * @param {number} topN - Number of candidates to return
 * @returns {Array} - Array of { manual, score } objects, sorted by score
 */
export function selectMultipleCandidates(question, topN = 3) {
  const manuals = ['rasum', 'r2dum', 'rmum', 'ras1dtechref', 'rasrn', 'raski'];
  const scores = manuals.map(manual => ({
    manual,
    score: scoreManual(question, manual),
    info: getManualInfo(manual)
  }));

  // Sort by score descending
  scores.sort((a, b) => b.score - a.score);

  // Return top N
  return scores.slice(0, topN);
}

// CLI interface for testing
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const question = process.argv.slice(2).join(' ');

  if (!question) {
    console.log('Usage: node manual_selector.mjs "your question here"');
    console.log('\nExample:');
    console.log('  node manual_selector.mjs "How do I create a 2D mesh?"');
    process.exit(1);
  }

  console.log('\n=== Manual Selection Test ===\n');
  const result = selectManual(question, { debug: true });
  const info = getManualInfo(result.manual);

  console.log('\n=== Selected Manual ===');
  console.log(`Code: ${info.code}`);
  console.log(`Name: ${info.name}`);
  console.log(`Description: ${info.description}`);
  console.log(`Confidence: ${result.confidence}`);

  console.log('\n=== Top 3 Candidates ===');
  const candidates = selectMultipleCandidates(question, 3);
  candidates.forEach((c, i) => {
    console.log(`${i + 1}. ${c.info.short_name} (score: ${c.score})`);
  });
}

/**
 * Select manual with optional web search enhancement
 * @param {string} question - User's question
 * @param {Object} options - Selection options
 * @returns {Promise<Object>|Object} - Manual selection result (async if useWebSearch=true)
 */
export async function selectManualEnhanced(question, options = {}) {
  const {
    useWebSearch = false,
    webSearchFn = null,
    debug = false
  } = options;

  if (!useWebSearch) {
    // Simple keyword selection (synchronous)
    return selectManual(question, { debug });
  }

  // Hybrid selection with web search (asynchronous)
  const { hybridManualSelection } = await import('./web_search_selector.mjs');

  return hybridManualSelection(question, {
    ...options,
    keywordSelector: selectManual
  });
}
