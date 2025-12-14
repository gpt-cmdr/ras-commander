/**
 * index_builder.mjs
 *
 * Builds and maintains a searchable index of HEC-RAS documentation.
 * Phase 2 feature for enhanced search capabilities.
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const INDEX_FILE = join(__dirname, '../data/manual_index.json');

/**
 * Create a basic pre-built index from known documentation structure
 * This is a starter index that can be enhanced by actually crawling the docs
 * @returns {Object} - Documentation index
 */
export function createPrebuiltIndex() {
  return {
    version: '1.0',
    updated: new Date().toISOString(),
    manuals: {
      rasum: {
        name: "User's Manual",
        sections: [
          {
            title: "Introduction",
            keywords: ["introduction", "getting started", "overview"],
            topics: ["basics", "installation"]
          },
          {
            title: "Geometric Data",
            keywords: ["geometry", "cross section", "river", "reach"],
            topics: ["cross sections", "bridges", "culverts", "inline structures"]
          },
          {
            title: "Steady Flow Analysis",
            keywords: ["steady", "flow", "water surface"],
            topics: ["steady flow", "subcritical", "supercritical", "mixed flow"]
          },
          {
            title: "Unsteady Flow Analysis",
            keywords: ["unsteady", "hydrograph", "time series"],
            topics: ["unsteady flow", "boundary conditions", "initial conditions"]
          },
          {
            title: "Running a Simulation",
            keywords: ["run", "compute", "simulation", "button"],
            topics: ["execution", "computation", "running"]
          },
          {
            title: "Dam Breach",
            keywords: ["dam", "breach", "break", "failure"],
            topics: ["dam breach", "breach parameters", "breach hydrograph"]
          }
        ]
      },
      r2dum: {
        name: "2D Modeling Manual",
        sections: [
          {
            title: "2D Flow Areas",
            keywords: ["2d", "flow area", "area"],
            topics: ["2d modeling", "flow area creation"]
          },
          {
            title: "Mesh Generation",
            keywords: ["mesh", "grid", "cell", "refinement"],
            topics: ["mesh creation", "mesh refinement", "mesh quality"]
          },
          {
            title: "Terrain Processing",
            keywords: ["terrain", "elevation", "topography", "dem"],
            topics: ["terrain data", "elevation processing"]
          },
          {
            title: "2D Boundary Conditions",
            keywords: ["boundary", "2d bc", "inflow"],
            topics: ["2d boundaries", "2d bc lines"]
          }
        ]
      },
      rmum: {
        name: "Mapper Manual",
        sections: [
          {
            title: "RASMapper Interface",
            keywords: ["rasmapper", "interface", "map window"],
            topics: ["mapper basics", "map interface"]
          },
          {
            title: "Terrain Layers",
            keywords: ["terrain", "layer", "elevation", "dem"],
            topics: ["terrain management", "terrain import"]
          },
          {
            title: "Stored Maps",
            keywords: ["stored map", "profile", "inundation"],
            topics: ["stored maps", "flood mapping", "inundation mapping"]
          },
          {
            title: "Result Mapping",
            keywords: ["results", "water surface", "depth", "velocity"],
            topics: ["result visualization", "raster export"]
          }
        ]
      },
      ras1dtechref: {
        name: "Hydraulic Reference",
        sections: [
          {
            title: "Basic Equations",
            keywords: ["equation", "energy", "momentum"],
            topics: ["hydraulic equations", "theory"]
          },
          {
            title: "Numerical Methods",
            keywords: ["numerical", "algorithm", "method"],
            topics: ["computational methods", "solution techniques"]
          },
          {
            title: "Hydraulic Structures",
            keywords: ["bridge", "culvert", "weir", "gate"],
            topics: ["structure hydraulics", "structure equations"]
          }
        ]
      },
      rasrn: {
        name: "Release Notes",
        sections: [
          {
            title: "Version 6.6",
            keywords: ["6.6", "new features", "changes"],
            topics: ["version 6.6", "6.6 features"]
          },
          {
            title: "Version 6.5",
            keywords: ["6.5", "new features", "changes"],
            topics: ["version 6.5", "6.5 features"]
          },
          {
            title: "Version 6.4",
            keywords: ["6.4", "new features", "changes"],
            topics: ["version 6.4", "6.4 features"]
          }
        ]
      },
      raski: {
        name: "Known Issues",
        sections: [
          {
            title: "2D Modeling Issues",
            keywords: ["2d", "issue", "problem", "mesh"],
            topics: ["2d bugs", "2d problems"]
          },
          {
            title: "Computation Errors",
            keywords: ["error", "computation", "crash", "unstable"],
            topics: ["computation errors", "stability issues"]
          },
          {
            title: "Interface Issues",
            keywords: ["interface", "ui", "button", "crash"],
            topics: ["ui bugs", "interface problems"]
          }
        ]
      }
    }
  };
}

/**
 * Load documentation index from file or create if doesn't exist
 * @returns {Object} - Documentation index
 */
export function loadIndex() {
  if (fs.existsSync(INDEX_FILE)) {
    return JSON.parse(fs.readFileSync(INDEX_FILE, 'utf8'));
  }

  // Create pre-built index if file doesn't exist
  const index = createPrebuiltIndex();
  saveIndex(index);
  return index;
}

/**
 * Save documentation index to file
 * @param {Object} index - Documentation index
 */
export function saveIndex(index) {
  index.updated = new Date().toISOString();
  fs.writeFileSync(INDEX_FILE, JSON.stringify(index, null, 2));
  console.log('[Index] Saved to', INDEX_FILE);
}

/**
 * Search index for relevant sections
 * @param {string} query - Search query
 * @param {Object} options - Search options
 * @returns {Array} - Array of matching sections with scores
 */
export function searchIndex(query, options = {}) {
  const {
    manual = null,
    topN = 5
  } = options;

  const index = loadIndex();
  const results = [];
  const lowerQuery = query.toLowerCase();
  const queryWords = lowerQuery.split(/\s+/);

  const manualsToSearch = manual ? [manual] : Object.keys(index.manuals);

  for (const manualCode of manualsToSearch) {
    const manualData = index.manuals[manualCode];

    if (!manualData) continue;

    for (const section of manualData.sections) {
      let score = 0;

      // Title match (high weight)
      if (section.title.toLowerCase().includes(lowerQuery)) {
        score += 10;
      }

      // Individual word matches in title
      for (const word of queryWords) {
        if (section.title.toLowerCase().includes(word)) {
          score += 3;
        }
      }

      // Keyword matches (medium weight)
      for (const keyword of section.keywords) {
        if (lowerQuery.includes(keyword)) {
          score += 5;
        }
        for (const word of queryWords) {
          if (keyword.includes(word)) {
            score += 2;
          }
        }
      }

      // Topic matches (low weight)
      for (const topic of section.topics) {
        if (lowerQuery.includes(topic)) {
          score += 3;
        }
      }

      if (score > 0) {
        results.push({
          manual: manualCode,
          manualName: manualData.name,
          section: section.title,
          keywords: section.keywords,
          topics: section.topics,
          score
        });
      }
    }
  }

  // Sort by score descending
  results.sort((a, b) => b.score - a.score);

  return results.slice(0, topN);
}

/**
 * Get all sections for a manual
 * @param {string} manual - Manual code
 * @returns {Array} - Array of sections
 */
export function getManualSections(manual) {
  const index = loadIndex();
  const manualData = index.manuals[manual];

  if (!manualData) {
    return [];
  }

  return manualData.sections.map(section => ({
    title: section.title,
    keywords: section.keywords,
    topics: section.topics
  }));
}

// CLI interface for testing
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const command = process.argv[2];

  if (command === 'create') {
    const index = createPrebuiltIndex();
    saveIndex(index);
    console.log('✅ Index created and saved');
  } else if (command === 'search') {
    const query = process.argv.slice(3).join(' ');
    const results = searchIndex(query);

    console.log(`\n=== Search Results for: "${query}" ===\n`);
    results.forEach((result, i) => {
      console.log(`${i + 1}. [${result.manual}] ${result.section}`);
      console.log(`   Manual: ${result.manualName}`);
      console.log(`   Score: ${result.score}`);
      console.log(`   Keywords: ${result.keywords.join(', ')}`);
      console.log('');
    });
  } else if (command === 'sections') {
    const manual = process.argv[3];
    const sections = getManualSections(manual);

    console.log(`\n=== Sections in ${manual} ===\n`);
    sections.forEach((section, i) => {
      console.log(`${i + 1}. ${section.title}`);
      console.log(`   Keywords: ${section.keywords.join(', ')}`);
      console.log('');
    });
  } else {
    console.log('Usage:');
    console.log('  node index_builder.mjs create                    - Create index');
    console.log('  node index_builder.mjs search "query"            - Search index');
    console.log('  node index_builder.mjs sections <manual>         - List sections');
  }
}
