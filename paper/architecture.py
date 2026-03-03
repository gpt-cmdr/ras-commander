"""Generate architecture diagram for JOSS paper."""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

fig, ax = plt.subplots(1, 1, figsize=(10, 7))
ax.set_xlim(0, 10)
ax.set_ylim(0, 8)
ax.axis('off')

# Colors
core_color = '#4472C4'
sub_color = '#5B9BD5'
ext_color = '#A9D18E'
data_color = '#F4B183'
header_text = 'white'
body_text = '#333333'

def draw_box(x, y, w, h, label, color, fontsize=9, bold=False):
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.1",
        facecolor=color, edgecolor='#333333', linewidth=1.2
    )
    ax.add_patch(rect)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w/2, y + h/2, label, ha='center', va='center',
            fontsize=fontsize, color=header_text if color in [core_color, sub_color] else body_text,
            fontweight=weight, wrap=True)

def draw_arrow(x1, y1, x2, y2):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color='#555555', lw=1.5))

# Title
ax.text(5, 7.6, 'ras-commander Architecture', ha='center', va='center',
        fontsize=14, fontweight='bold', color='#333333')

# Top layer - User Interface
draw_box(0.3, 6.8, 2.8, 0.6, 'init_ras_project()', core_color, 10, True)
draw_box(3.5, 6.8, 3.0, 0.6, 'RasCmdr (Execution)', core_color, 10, True)
draw_box(6.9, 6.8, 2.8, 0.6, 'Hdf* (Results)', core_color, 10, True)

# Arrow flow
draw_arrow(3.1, 7.1, 3.5, 7.1)
draw_arrow(6.5, 7.1, 6.9, 7.1)

# Middle layer - Core components
draw_box(0.3, 5.8, 2.0, 0.7, 'RasPrj\n(DataFrames)', sub_color, 8)
draw_box(2.6, 5.8, 2.0, 0.7, 'RasPlan\nRasUnsteady', sub_color, 8)
draw_box(4.9, 5.8, 2.0, 0.7, 'RasGeometry\nRasGeo', sub_color, 8)
draw_box(7.2, 5.8, 2.5, 0.7, 'RasMap\nRasValidation', sub_color, 8)

# Subpackages layer
y_sub = 4.5
draw_box(0.2, y_sub, 1.5, 0.9, 'hdf\n(23 modules)\nResults', ext_color, 7)
draw_box(1.9, y_sub, 1.5, 0.9, 'geom\n(13 modules)\nGeometry', ext_color, 7)
draw_box(3.6, y_sub, 1.5, 0.9, 'usgs\n(14 modules)\nGauge Data', ext_color, 7)
draw_box(5.3, y_sub, 1.5, 0.9, 'remote\n(12 modules)\nDistributed', ext_color, 7)
draw_box(7.0, y_sub, 1.4, 0.9, 'precip\n(7 modules)\nRainfall', ext_color, 7)
draw_box(8.6, y_sub, 1.2, 0.9, 'fixit\n(6 modules)\nRepair', ext_color, 7)

# Additional small subpackages
y_sub2 = 3.3
draw_box(0.2, y_sub2, 1.8, 0.7, 'dss (3)\nBoundary I/O', ext_color, 7)
draw_box(2.2, y_sub2, 1.8, 0.7, 'terrain (3)\nTerrain CLI', ext_color, 7)
draw_box(4.2, y_sub2, 1.8, 0.7, 'check (5)\nQA/QC', ext_color, 7)
draw_box(6.2, y_sub2, 1.8, 0.7, 'results (3)\nSummary', ext_color, 7)
draw_box(8.2, y_sub2, 1.6, 0.7, 'callbacks\nMonitoring', ext_color, 7)

# Bottom layer - External systems
y_ext = 1.8
draw_box(0.3, y_ext, 2.2, 0.9, 'HEC-RAS\n(Ras.exe /\nHECRASController)', data_color, 8)
draw_box(2.8, y_ext, 2.0, 0.9, 'HDF5 Files\n(.p##.hdf\n.g##.hdf)', data_color, 8)
draw_box(5.1, y_ext, 2.0, 0.9, 'Text Files\n(.g## .p## .u##\n.prj .rasmap)', data_color, 8)
draw_box(7.4, y_ext, 2.3, 0.9, 'External APIs\n(USGS NWIS\nNOAA Atlas 14)', data_color, 8)

# Connecting arrows (core to subpackages)
for x in [1.0, 2.7, 4.4, 6.1, 7.7, 9.2]:
    draw_arrow(min(x, 9.0), 5.8, min(x, 9.0), 5.4)

# Arrows from subpackages to external
draw_arrow(1.0, 4.5, 1.4, 2.7)
draw_arrow(1.0, 4.5, 3.8, 2.7)
draw_arrow(2.7, 4.5, 6.1, 2.7)
draw_arrow(4.4, 4.5, 8.5, 2.7)
draw_arrow(6.1, 4.5, 1.4, 2.7)

# Legend
legend_y = 0.5
ax.text(0.5, legend_y, 'Legend:', fontsize=8, fontweight='bold', color='#333333')
for i, (color, label) in enumerate([
    (core_color, 'Public API'),
    (sub_color, 'Core Classes'),
    (ext_color, 'Subpackages'),
    (data_color, 'External Systems'),
]):
    rect = mpatches.FancyBboxPatch(
        (1.8 + i*2.2, legend_y - 0.15), 0.4, 0.3,
        boxstyle="round,pad=0.05", facecolor=color, edgecolor='#333333', linewidth=0.8
    )
    ax.add_patch(rect)
    ax.text(2.4 + i*2.2, legend_y, label, fontsize=7, va='center', color='#333333')

plt.tight_layout()
plt.savefig('/home/user/ras-commander/paper/architecture.png', dpi=300, bbox_inches='tight',
            facecolor='white', edgecolor='none')
plt.close()
print("Architecture diagram saved to paper/architecture.png")
