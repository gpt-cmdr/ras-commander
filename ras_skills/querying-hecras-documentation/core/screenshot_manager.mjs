/**
 * screenshot_manager.mjs
 *
 * Manages screenshot capture, caching, and retrieval for documentation pages.
 */

import fs from 'fs';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Screenshot cache directory
const CACHE_DIR = join(__dirname, '../screenshots/cache');
const SCREENSHOTS_DIR = join(__dirname, '../screenshots');

/**
 * Ensure cache directory exists
 */
function ensureCacheDir() {
  if (!fs.existsSync(CACHE_DIR)) {
    fs.mkdirSync(CACHE_DIR, { recursive: true });
  }
}

/**
 * Generate cache key from manual and URL
 * @param {string} manual - Manual code (rasum, r2dum, etc.)
 * @param {string} url - Documentation URL
 * @returns {string} - Cache key (md5 hash)
 */
export function generateCacheKey(manual, url) {
  const content = `${manual}:${url}`;
  return crypto.createHash('md5').update(content).digest('hex');
}

/**
 * Get cached screenshot path if it exists
 * @param {string} cacheKey - Cache key
 * @returns {string|null} - Path to cached screenshot or null
 */
export function getCachedScreenshot(cacheKey) {
  ensureCacheDir();
  const cachePath = join(CACHE_DIR, `${cacheKey}.png`);

  if (fs.existsSync(cachePath)) {
    const stats = fs.statSync(cachePath);
    const ageHours = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60);

    // Log cache hit
    console.log(`[Cache] Found cached screenshot (age: ${ageHours.toFixed(1)}h)`);

    return cachePath;
  }

  return null;
}

/**
 * Save screenshot to cache
 * @param {string} cacheKey - Cache key
 * @param {string} sourcePath - Path to screenshot file
 * @returns {string} - Path to cached screenshot
 */
export function cacheScreenshot(cacheKey, sourcePath) {
  ensureCacheDir();
  const cachePath = join(CACHE_DIR, `${cacheKey}.png`);

  try {
    fs.copyFileSync(sourcePath, cachePath);
    console.log(`[Cache] Screenshot cached: ${cacheKey}.png`);
    return cachePath;
  } catch (error) {
    console.error(`[Cache] Failed to cache screenshot: ${error.message}`);
    return sourcePath; // Return original if caching fails
  }
}

/**
 * Capture screenshot using dev-browser
 * @param {Object} page - Playwright page object
 * @param {string} manual - Manual code
 * @param {string} url - Documentation URL
 * @param {Object} options - Screenshot options
 * @returns {Promise<string>} - Path to screenshot
 */
export async function captureScreenshot(page, manual, url, options = {}) {
  const {
    fullPage = true,
    useCache = true
  } = options;

  // Generate cache key
  const cacheKey = generateCacheKey(manual, url);

  // Check cache first
  if (useCache) {
    const cachedPath = getCachedScreenshot(cacheKey);
    if (cachedPath) {
      return cachedPath;
    }
  }

  // Capture new screenshot
  const timestamp = Date.now();
  const filename = `${manual}_${timestamp}.png`;
  const screenshotPath = join(SCREENSHOTS_DIR, filename);

  try {
    await page.screenshot({ path: screenshotPath, fullPage });
    console.log(`[Screenshot] Captured: ${filename}`);

    // Cache the screenshot
    if (useCache) {
      cacheScreenshot(cacheKey, screenshotPath);
    }

    return screenshotPath;
  } catch (error) {
    console.error(`[Screenshot] Failed to capture: ${error.message}`);
    throw error;
  }
}

/**
 * Get screenshot metadata
 * @param {string} screenshotPath - Path to screenshot
 * @returns {Object} - { path, size, modified, exists }
 */
export function getScreenshotMetadata(screenshotPath) {
  if (!fs.existsSync(screenshotPath)) {
    return {
      path: screenshotPath,
      exists: false
    };
  }

  const stats = fs.statSync(screenshotPath);

  return {
    path: screenshotPath,
    exists: true,
    size: stats.size,
    sizeKB: (stats.size / 1024).toFixed(2),
    sizeMB: (stats.size / (1024 * 1024)).toFixed(2),
    modified: stats.mtime,
    ageHours: ((Date.now() - stats.mtimeMs) / (1000 * 60 * 60)).toFixed(1)
  };
}

/**
 * Clear screenshot cache
 * @param {Object} options - { olderThanHours?: number, manual?: string }
 * @returns {number} - Number of files deleted
 */
export function clearCache(options = {}) {
  const { olderThanHours, manual } = options;

  ensureCacheDir();
  const files = fs.readdirSync(CACHE_DIR);
  let deletedCount = 0;

  for (const file of files) {
    if (!file.endsWith('.png')) continue;

    const filePath = join(CACHE_DIR, file);
    const stats = fs.statSync(filePath);
    const ageHours = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60);

    let shouldDelete = false;

    // Delete if older than specified hours
    if (olderThanHours && ageHours > olderThanHours) {
      shouldDelete = true;
    }

    // Delete if manual-specific
    if (manual && file.startsWith(manual)) {
      shouldDelete = true;
    }

    // Delete all if no filters
    if (!olderThanHours && !manual) {
      shouldDelete = true;
    }

    if (shouldDelete) {
      try {
        fs.unlinkSync(filePath);
        deletedCount++;
      } catch (error) {
        console.error(`Failed to delete ${file}: ${error.message}`);
      }
    }
  }

  console.log(`[Cache] Cleared ${deletedCount} cached screenshots`);
  return deletedCount;
}

/**
 * Get cache statistics
 * @returns {Object} - { totalFiles, totalSizeMB, oldestHours, newestHours }
 */
export function getCacheStats() {
  ensureCacheDir();
  const files = fs.readdirSync(CACHE_DIR).filter(f => f.endsWith('.png'));

  if (files.length === 0) {
    return {
      totalFiles: 0,
      totalSizeMB: 0,
      oldestHours: null,
      newestHours: null
    };
  }

  let totalSize = 0;
  let oldestTime = Date.now();
  let newestTime = 0;

  for (const file of files) {
    const filePath = join(CACHE_DIR, file);
    const stats = fs.statSync(filePath);

    totalSize += stats.size;
    oldestTime = Math.min(oldestTime, stats.mtimeMs);
    newestTime = Math.max(newestTime, stats.mtimeMs);
  }

  return {
    totalFiles: files.length,
    totalSizeMB: (totalSize / (1024 * 1024)).toFixed(2),
    totalSizeKB: (totalSize / 1024).toFixed(2),
    oldestHours: ((Date.now() - oldestTime) / (1000 * 60 * 60)).toFixed(1),
    newestHours: ((Date.now() - newestTime) / (1000 * 60 * 60)).toFixed(1)
  };
}

// CLI interface for testing
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const command = process.argv[2];

  if (command === 'stats') {
    const stats = getCacheStats();
    console.log('=== Screenshot Cache Statistics ===');
    console.log(`Total Files: ${stats.totalFiles}`);
    console.log(`Total Size: ${stats.totalSizeMB} MB (${stats.totalSizeKB} KB)`);
    console.log(`Oldest: ${stats.oldestHours}h ago`);
    console.log(`Newest: ${stats.newestHours}h ago`);
  } else if (command === 'clear') {
    const count = clearCache();
    console.log(`Cleared ${count} files from cache`);
  } else {
    console.log('Usage:');
    console.log('  node screenshot_manager.mjs stats    - Show cache statistics');
    console.log('  node screenshot_manager.mjs clear    - Clear all cached screenshots');
  }
}
