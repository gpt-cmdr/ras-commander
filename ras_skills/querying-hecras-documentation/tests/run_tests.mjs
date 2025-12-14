/**
 * run_tests.mjs
 *
 * Automated test runner for HEC-RAS Documentation Query skill.
 * Validates manual selection accuracy and result quality.
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { selectManual } from '../core/manual_selector.mjs';
import { queryDocumentation } from '../core/query_engine.mjs';
import { getQueryMode } from '../core/fallback_handler.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const TEST_QUERIES_FILE = join(__dirname, 'test_queries.json');
const TEST_RESULTS_DIR = join(__dirname, 'test_results');

/**
 * Load test queries from JSON file
 * @returns {Object} - Test queries configuration
 */
function loadTestQueries() {
  if (!fs.existsSync(TEST_QUERIES_FILE)) {
    throw new Error(`Test queries file not found: ${TEST_QUERIES_FILE}`);
  }

  return JSON.parse(fs.readFileSync(TEST_QUERIES_FILE, 'utf8'));
}

/**
 * Ensure test results directory exists
 */
function ensureResultsDir() {
  if (!fs.existsSync(TEST_RESULTS_DIR)) {
    fs.mkdirSync(TEST_RESULTS_DIR, { recursive: true });
  }
}

/**
 * Validate manual selection against expected result
 * @param {Object} testCase - Test case definition
 * @param {Object} selection - Manual selection result
 * @returns {Object} - Validation result
 */
function validateManualSelection(testCase, selection) {
  const validation = {
    passed: false,
    expected: testCase.expected_manual,
    actual: selection.manual,
    score: selection.score,
    confidence: selection.confidence,
    notes: []
  };

  // Check if actual manual matches expected
  if (selection.manual === testCase.expected_manual) {
    validation.passed = true;
    validation.notes.push('✓ Correct manual selected');
  } else {
    // Check if it's in also_check list (acceptable alternative)
    if (testCase.also_check && testCase.also_check.includes(selection.manual)) {
      validation.passed = true;
      validation.notes.push('✓ Acceptable alternative manual');
    } else {
      validation.notes.push(`✗ Expected ${testCase.expected_manual}, got ${selection.manual}`);
    }
  }

  // Check confidence level
  if (testCase.expected_confidence === 'high' && selection.confidence !== 'high') {
    validation.notes.push(`⚠ Expected high confidence, got ${selection.confidence}`);
  }

  return validation;
}

/**
 * Validate content extraction against test criteria
 * @param {Object} testCase - Test case definition
 * @param {Object} result - Query result
 * @returns {Object} - Validation result
 */
function validateContent(testCase, result) {
  const validation = {
    passed: true,
    checks: [],
    warnings: []
  };

  // Check if result succeeded
  if (!result.success) {
    validation.passed = false;
    validation.checks.push('✗ Query failed: ' + (result.error || 'Unknown error'));
    return validation;
  }

  // Check text length
  if (result.content && result.content.text) {
    const textLength = result.content.text.length;
    if (textLength < 100) {
      validation.warnings.push(`⚠ Text length only ${textLength} chars (expected >100)`);
    } else {
      validation.checks.push(`✓ Text length: ${textLength} chars`);
    }
  }

  // Check for required keywords
  if (testCase.validation && testCase.validation.should_mention) {
    const text = result.content?.text?.toLowerCase() || '';
    const title = result.content?.title?.toLowerCase() || '';
    const combinedText = text + ' ' + title;

    for (const keyword of testCase.validation.should_mention) {
      if (combinedText.includes(keyword.toLowerCase())) {
        validation.checks.push(`✓ Found keyword: "${keyword}"`);
      } else {
        validation.warnings.push(`⚠ Missing keyword: "${keyword}"`);
      }
    }
  }

  // Check screenshot
  if (testCase.validation && testCase.validation.should_have_screenshot) {
    if (result.screenshot && result.screenshot.path) {
      const screenshotExists = fs.existsSync(result.screenshot.path);
      if (screenshotExists) {
        validation.checks.push('✓ Screenshot captured');
      } else {
        validation.warnings.push('⚠ Screenshot path invalid');
      }
    } else {
      validation.warnings.push('⚠ No screenshot captured');
    }
  }

  // Check sections
  if (result.content && result.content.sections) {
    const sectionCount = result.content.sections.length;
    validation.checks.push(`✓ Sections found: ${sectionCount}`);
  }

  return validation;
}

/**
 * Run a single test case
 * @param {Object} testCase - Test case definition
 * @param {Object} options - Test options
 * @returns {Promise<Object>} - Test result
 */
async function runTestCase(testCase, options = {}) {
  const { verbose = false, queryMode = 'selection-only' } = options;

  console.log(`\n--- Running test: ${testCase.id} ---`);
  console.log(`Question: "${testCase.question}"`);

  const result = {
    id: testCase.id,
    question: testCase.question,
    timestamp: new Date().toISOString(),
    manualSelection: null,
    contentValidation: null,
    fullQuery: null,
    passed: false,
    duration_ms: 0
  };

  const startTime = Date.now();

  try {
    // Test 1: Manual Selection
    const selection = selectManual(testCase.question, { debug: verbose });
    result.manualSelection = validateManualSelection(testCase, selection);

    console.log(`  Manual: ${selection.manual} (score: ${selection.score}, confidence: ${selection.confidence})`);
    console.log(`  ${result.manualSelection.passed ? '✓ PASS' : '✗ FAIL'} - Manual selection`);

    // Test 2: Full Query (if mode allows and requested)
    if (queryMode === 'full') {
      console.log('  Executing full query...');

      const queryResult = await queryDocumentation(testCase.question, {
        manual: testCase.expected_manual,  // Force expected manual for validation
        debug: verbose
      });

      result.fullQuery = queryResult;
      result.contentValidation = validateContent(testCase, queryResult);

      console.log(`  ${result.contentValidation.passed ? '✓ PASS' : '✗ FAIL'} - Content validation`);

      // Print validation checks
      if (verbose) {
        result.contentValidation.checks.forEach(check => console.log(`    ${check}`));
        result.contentValidation.warnings.forEach(warn => console.log(`    ${warn}`));
      }
    }

    // Overall pass/fail
    result.passed = result.manualSelection.passed &&
                   (queryMode === 'selection-only' || result.contentValidation?.passed);

    result.duration_ms = Date.now() - startTime;

    console.log(`  Overall: ${result.passed ? '✓ PASS' : '✗ FAIL'} (${result.duration_ms}ms)`);

  } catch (error) {
    result.error = error.message;
    result.passed = false;
    result.duration_ms = Date.now() - startTime;

    console.log(`  ✗ ERROR: ${error.message}`);
  }

  return result;
}

/**
 * Run all tests in a category
 * @param {string} categoryName - Category name
 * @param {Object} category - Category definition
 * @param {Object} options - Test options
 * @returns {Promise<Array>} - Array of test results
 */
async function runCategory(categoryName, category, options = {}) {
  console.log(`\n╔═══════════════════════════════════════════════════════════════╗`);
  console.log(`║  Category: ${categoryName.padEnd(52)} ║`);
  console.log(`╚═══════════════════════════════════════════════════════════════╝`);
  console.log(`Description: ${category.description}`);

  const results = [];

  for (const testCase of category.tests) {
    const result = await runTestCase(testCase, options);
    results.push(result);

    // Brief pause between tests
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  return results;
}

/**
 * Generate test report
 * @param {Object} allResults - All test results by category
 * @param {Object} testConfig - Test configuration
 * @returns {Object} - Summary report
 */
function generateReport(allResults, testConfig) {
  let totalTests = 0;
  let totalPassed = 0;
  let totalFailed = 0;
  let totalErrors = 0;
  let totalDuration = 0;

  const categorySummaries = {};

  for (const [categoryName, results] of Object.entries(allResults)) {
    const categoryPassed = results.filter(r => r.passed).length;
    const categoryFailed = results.filter(r => !r.passed && !r.error).length;
    const categoryErrors = results.filter(r => r.error).length;
    const categoryDuration = results.reduce((sum, r) => sum + r.duration_ms, 0);

    categorySummaries[categoryName] = {
      total: results.length,
      passed: categoryPassed,
      failed: categoryFailed,
      errors: categoryErrors,
      duration_ms: categoryDuration
    };

    totalTests += results.length;
    totalPassed += categoryPassed;
    totalFailed += categoryFailed;
    totalErrors += categoryErrors;
    totalDuration += categoryDuration;
  }

  const report = {
    timestamp: new Date().toISOString(),
    summary: {
      total: totalTests,
      passed: totalPassed,
      failed: totalFailed,
      errors: totalErrors,
      pass_rate: totalTests > 0 ? ((totalPassed / totalTests) * 100).toFixed(1) + '%' : '0%',
      total_duration_ms: totalDuration,
      avg_duration_ms: totalTests > 0 ? Math.round(totalDuration / totalTests) : 0
    },
    categories: categorySummaries,
    results: allResults
  };

  return report;
}

/**
 * Print test report to console
 * @param {Object} report - Test report
 */
function printReport(report) {
  console.log('\n\n╔═══════════════════════════════════════════════════════════════╗');
  console.log('║                      TEST REPORT                              ║');
  console.log('╚═══════════════════════════════════════════════════════════════╝\n');

  console.log('Summary:');
  console.log(`  Total Tests: ${report.summary.total}`);
  console.log(`  Passed: ${report.summary.passed} (${report.summary.pass_rate})`);
  console.log(`  Failed: ${report.summary.failed}`);
  console.log(`  Errors: ${report.summary.errors}`);
  console.log(`  Total Duration: ${(report.summary.total_duration_ms / 1000).toFixed(2)}s`);
  console.log(`  Average Duration: ${report.summary.avg_duration_ms}ms\n`);

  console.log('Categories:');
  for (const [name, summary] of Object.entries(report.categories)) {
    const passRate = summary.total > 0 ? ((summary.passed / summary.total) * 100).toFixed(0) : '0';
    console.log(`  ${name}: ${summary.passed}/${summary.total} (${passRate}%)`);
  }

  console.log('\n' + '═'.repeat(67));
  console.log(`Overall: ${report.summary.passed === report.summary.total ? '✓ ALL TESTS PASSED' : '✗ SOME TESTS FAILED'}`);
  console.log('═'.repeat(67) + '\n');
}

/**
 * Save test report to file
 * @param {Object} report - Test report
 * @param {string} filename - Output filename
 */
function saveReport(report, filename = 'test_report.json') {
  ensureResultsDir();

  const reportPath = join(TEST_RESULTS_DIR, filename);
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));

  console.log(`\nReport saved to: ${reportPath}`);
}

/**
 * Main test runner
 */
async function main() {
  const args = process.argv.slice(2);

  // Parse command-line arguments
  const options = {
    verbose: args.includes('--verbose') || args.includes('-v'),
    queryMode: args.includes('--full') ? 'full' : 'selection-only',
    category: args.find(arg => arg.startsWith('--category='))?.split('=')[1],
    saveReport: !args.includes('--no-save')
  };

  console.log('╔═══════════════════════════════════════════════════════════════╗');
  console.log('║     HEC-RAS Documentation Query - Test Suite                 ║');
  console.log('╚═══════════════════════════════════════════════════════════════╝\n');

  // Check query mode
  if (options.queryMode === 'full') {
    const mode = await getQueryMode();
    console.log(`Query Mode: ${mode.mode.toUpperCase()}`);
    console.log(`Message: ${mode.message}\n`);

    if (mode.mode !== 'visual') {
      console.log('⚠ Warning: Full query tests require dev-browser (visual mode)');
      console.log('Falling back to selection-only mode\n');
      options.queryMode = 'selection-only';
    }
  } else {
    console.log('Mode: SELECTION-ONLY (manual selection tests only)\n');
  }

  // Load test queries
  const testConfig = loadTestQueries();
  console.log(`Loaded ${Object.keys(testConfig.categories).length} test categories\n`);

  // Run tests
  const allResults = {};

  for (const [categoryName, category] of Object.entries(testConfig.categories)) {
    // Skip if category filter specified
    if (options.category && categoryName !== options.category) {
      continue;
    }

    const results = await runCategory(categoryName, category, options);
    allResults[categoryName] = results;
  }

  // Generate and print report
  const report = generateReport(allResults, testConfig);
  printReport(report);

  // Save report
  if (options.saveReport) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').split('T')[0];
    saveReport(report, `test_report_${timestamp}.json`);
  }

  // Exit with appropriate code
  process.exit(report.summary.failed + report.summary.errors > 0 ? 1 : 0);
}

// CLI interface
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  // Print usage if --help
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log('Usage: node run_tests.mjs [options]\n');
    console.log('Options:');
    console.log('  --verbose, -v          Verbose output');
    console.log('  --full                 Run full queries (requires dev-browser)');
    console.log('  --category=<name>      Run only specified category');
    console.log('  --no-save              Don\'t save report to file');
    console.log('  --help, -h             Show this help\n');
    console.log('Examples:');
    console.log('  node run_tests.mjs                    # Run selection tests');
    console.log('  node run_tests.mjs --full             # Run full query tests');
    console.log('  node run_tests.mjs --category=ui_location');
    console.log('  node run_tests.mjs --verbose --full');
    process.exit(0);
  }

  main().catch(error => {
    console.error('\nFatal Error:', error.message);
    console.error(error.stack);
    process.exit(1);
  });
}

export { runTestCase, runCategory, generateReport };
