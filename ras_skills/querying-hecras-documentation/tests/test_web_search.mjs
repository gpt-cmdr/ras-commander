/**
 * test_web_search.mjs
 *
 * Test suite for web search manual selection
 * Tests URL extraction, scoring, confidence calculation, and hybrid decision logic
 */

import {
  extractManualFromUrl,
  scoreManualsByFrequency,
  determineConfidence,
  webSearchManualSelection,
  hybridManualSelection,
  RASDOCS_SITE,
  VALID_MANUALS
} from '../core/web_search_selector.mjs';

// Test results
let testsPassed = 0;
let testsFailed = 0;
const failures = [];

/**
 * Test helper: Assert equality
 */
function assertEqual(actual, expected, testName) {
  if (actual === expected) {
    testsPassed++;
    console.log(`✅ ${testName}`);
  } else {
    testsFailed++;
    const failure = `❌ ${testName}\n   Expected: ${expected}\n   Actual: ${actual}`;
    console.log(failure);
    failures.push({ test: testName, expected, actual });
  }
}

/**
 * Test helper: Assert truthy
 */
function assertTrue(value, testName) {
  if (value) {
    testsPassed++;
    console.log(`✅ ${testName}`);
  } else {
    testsFailed++;
    const failure = `❌ ${testName}\n   Expected: truthy\n   Actual: ${value}`;
    console.log(failure);
    failures.push({ test: testName, expected: 'truthy', actual: value });
  }
}

/**
 * Test helper: Assert deep equal for objects
 */
function assertDeepEqual(actual, expected, testName) {
  const actualStr = JSON.stringify(actual);
  const expectedStr = JSON.stringify(expected);
  if (actualStr === expectedStr) {
    testsPassed++;
    console.log(`✅ ${testName}`);
  } else {
    testsFailed++;
    const failure = `❌ ${testName}\n   Expected: ${expectedStr}\n   Actual: ${actualStr}`;
    console.log(failure);
    failures.push({ test: testName, expected: expectedStr, actual: actualStr });
  }
}

console.log('\n╔═══════════════════════════════════════════════════════════════╗');
console.log('║          Web Search Manual Selection Tests                   ║');
console.log('╚═══════════════════════════════════════════════════════════════╝\n');

// ============================================================================
// Test 1: URL Extraction
// ============================================================================

console.log('\n[Test Category] URL Pattern Extraction\n');

// Test 1.1: Valid raski URL
const url1 = 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/2d-mesh-issues';
assertEqual(extractManualFromUrl(url1), 'raski', 'Extract raski from valid URL');

// Test 1.2: Valid r2dum URL
const url2 = 'https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest/mesh-generation';
assertEqual(extractManualFromUrl(url2), 'r2dum', 'Extract r2dum from valid URL');

// Test 1.3: Valid rasum URL
const url3 = 'https://www.hec.usace.army.mil/confluence/rasdocs/rasum/latest/running-simulations';
assertEqual(extractManualFromUrl(url3), 'rasum', 'Extract rasum from valid URL');

// Test 1.4: Invalid URL (not rasdocs)
const url4 = 'https://www.google.com/search?q=hecras';
assertEqual(extractManualFromUrl(url4), null, 'Return null for non-rasdocs URL');

// Test 1.5: Invalid manual code
const url5 = 'https://www.hec.usace.army.mil/confluence/rasdocs/invalid/latest/page';
assertEqual(extractManualFromUrl(url5), null, 'Return null for invalid manual code');

// Test 1.6: All valid manuals
console.log('\nValid manuals list:');
console.log(VALID_MANUALS);
assertTrue(VALID_MANUALS.includes('rasum'), 'VALID_MANUALS includes rasum');
assertTrue(VALID_MANUALS.includes('r2dum'), 'VALID_MANUALS includes r2dum');
assertTrue(VALID_MANUALS.includes('rmum'), 'VALID_MANUALS includes rmum');
assertTrue(VALID_MANUALS.includes('raski'), 'VALID_MANUALS includes raski');
assertTrue(VALID_MANUALS.includes('rasrn'), 'VALID_MANUALS includes rasrn');
assertTrue(VALID_MANUALS.includes('ras1dtechref'), 'VALID_MANUALS includes ras1dtechref');

// ============================================================================
// Test 2: Manual Scoring by Frequency
// ============================================================================

console.log('\n[Test Category] Manual Scoring by Frequency\n');

// Test 2.1: Single manual dominant
const results1 = [
  { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/page1', title: 'Known Issues 1' },
  { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/page2', title: 'Known Issues 2' },
  { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/page3', title: 'Known Issues 3' }
];

const scoring1 = scoreManualsByFrequency(results1);
assertEqual(scoring1.sorted[0].manual, 'raski', 'Single manual dominant - raski selected');
assertEqual(scoring1.sorted[0].count, 3, 'Single manual dominant - count is 3');
assertEqual(scoring1.sorted.length, 1, 'Single manual dominant - only 1 manual');

// Test 2.2: Mixed manuals
const results2 = [
  { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/page1', title: 'Known Issues' },
  { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/page2', title: 'Known Issues' },
  { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest/page1', title: '2D Modeling' }
];

const scoring2 = scoreManualsByFrequency(results2);
assertEqual(scoring2.sorted[0].manual, 'raski', 'Mixed manuals - raski first (2 occurrences)');
assertEqual(scoring2.sorted[0].count, 2, 'Mixed manuals - raski count is 2');
assertEqual(scoring2.sorted[1].manual, 'r2dum', 'Mixed manuals - r2dum second (1 occurrence)');
assertEqual(scoring2.sorted[1].count, 1, 'Mixed manuals - r2dum count is 1');

// Test 2.3: No valid manuals
const results3 = [
  { url: 'https://www.google.com/search?q=hecras', title: 'Google' },
  { url: 'https://www.hec.usace.army.mil/software/hec-ras/', title: 'HEC-RAS Software' }
];

const scoring3 = scoreManualsByFrequency(results3);
assertEqual(scoring3.sorted.length, 0, 'No valid manuals - empty sorted array');

// ============================================================================
// Test 3: Confidence Determination
// ============================================================================

console.log('\n[Test Category] Confidence Calculation\n');

// Test 3.1: High confidence - 60%+ frequency
assertEqual(determineConfidence(3, 5), 'high', 'High confidence: 3/5 = 60%');
assertEqual(determineConfidence(4, 5), 'high', 'High confidence: 4/5 = 80%');
assertEqual(determineConfidence(5, 5), 'high', 'High confidence: 5/5 = 100%');

// Test 3.2: High confidence - 3+ occurrences
assertEqual(determineConfidence(3, 10), 'high', 'High confidence: 3 occurrences (30%)');
assertEqual(determineConfidence(4, 20), 'high', 'High confidence: 4 occurrences (20%)');

// Test 3.3: Medium confidence - 2 occurrences or 40%+
assertEqual(determineConfidence(2, 5), 'medium', 'Medium confidence: 2/5 = 40%');
assertEqual(determineConfidence(2, 10), 'medium', 'Medium confidence: 2/10 = 20% but 2 occurrences');

// Test 3.4: Low confidence
assertEqual(determineConfidence(1, 5), 'low', 'Low confidence: 1/5 = 20%');
assertEqual(determineConfidence(1, 10), 'low', 'Low confidence: 1/10 = 10%');

// Test 3.5: No results
assertEqual(determineConfidence(0, 0), 'none', 'No confidence: 0/0');

// ============================================================================
// Test 4: Web Search Manual Selection (with Mock)
// ============================================================================

console.log('\n[Test Category] Web Search Manual Selection\n');

// Mock WebSearch function
const mockWebSearch = async (query) => {
  // Simulate search results for "known issues with 2D mesh"
  return [
    { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/2d-mesh-issues', title: 'Known Issues: 2D Mesh Generation' },
    { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/mesh-problems', title: 'Common 2D Mesh Problems' },
    { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/troubleshooting', title: 'Troubleshooting 2D Areas' },
    { url: 'https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest/mesh-generation', title: '2D Mesh Generation Guide' }
  ];
};

// Test 4.1: High confidence selection
const question1 = "What are the known issues with 2D mesh generation?";
const result1 = await webSearchManualSelection(question1, { webSearchFn: mockWebSearch });

assertTrue(result1.success, 'Web search succeeds');
assertEqual(result1.manual, 'raski', 'Web search selects raski (3/4 = 75%)');
assertEqual(result1.count, 3, 'Web search count is 3');
assertEqual(result1.confidence, 'high', 'Web search confidence is high');
assertTrue(result1.topUrls.length > 0, 'Web search returns top URLs');

// ============================================================================
// Test 5: Hybrid Selection (Web + Keyword)
// ============================================================================

console.log('\n[Test Category] Hybrid Selection\n');

// Mock keyword selector
const mockKeywordSelector = (question, options) => {
  // Simulate keyword selection
  if (question.includes('2D mesh')) {
    return { manual: 'r2dum', score: 19, confidence: 'high' };
  } else if (question.includes('known issues')) {
    return { manual: 'raski', score: 5, confidence: 'low' };
  }
  return { manual: 'rasum', score: 0, confidence: 'low' };
};

// Test 5.1: High confidence web search - should trust web
const hybridResult1 = await hybridManualSelection(
  "What are the known issues with 2D mesh generation?",
  {
    useWebSearch: true,
    webSearchFn: mockWebSearch,
    keywordSelector: mockKeywordSelector
  }
);

assertEqual(hybridResult1.manual, 'raski', 'Hybrid: High confidence web search trusted over keywords');
assertEqual(hybridResult1.method, 'web-search', 'Hybrid: Method is web-search');
assertTrue(hybridResult1.hybridMode, 'Hybrid: hybridMode flag is true');

// Test 5.2: Web search disabled - should use keywords only
const hybridResult2 = await hybridManualSelection(
  "How do I create a 2D mesh?",
  {
    useWebSearch: false,
    keywordSelector: mockKeywordSelector
  }
);

assertEqual(hybridResult2.manual, 'r2dum', 'Hybrid: Web disabled uses keywords');
assertEqual(hybridResult2.method, 'keyword-only', 'Hybrid: Method is keyword-only');

// ============================================================================
// Test Summary
// ============================================================================

console.log('\n╔═══════════════════════════════════════════════════════════════╗');
console.log('║                      Test Summary                             ║');
console.log('╚═══════════════════════════════════════════════════════════════╝\n');

const totalTests = testsPassed + testsFailed;
const passRate = totalTests > 0 ? (testsPassed / totalTests * 100).toFixed(1) : 0;

console.log(`Total Tests: ${totalTests}`);
console.log(`Passed: ${testsPassed} (${passRate}%)`);
console.log(`Failed: ${testsFailed}`);

if (testsFailed > 0) {
  console.log('\n[Failed Tests]');
  failures.forEach(f => {
    console.log(`\n${f.test}`);
    console.log(`  Expected: ${f.expected}`);
    console.log(`  Actual: ${f.actual}`);
  });
}

// Exit with appropriate code
process.exit(testsFailed > 0 ? 1 : 0);
