"""Byte-level regressions for updates to an existing 2D perimeter."""

import pytest

from ras_commander.geom import GeomStorage


COORDS = [(0., 0.), (100., 0.), (100., 100.), (0., 100.), (0., 0.)]


def _fixture(tmp_path):
    rows = [f'{x:16.7f}{y:16.7f}' + ' ' * 16 + '\r\n' for x, y in COORDS]
    content = (
        'Geom Title=Record preservation\r\n'
        'Program Version=7.01\r\n'
        'Storage Area=MainArea     ,50.0000000,50.0000000\r\n'
        'Storage Area Surface Line= 5 \r\n' + ''.join(rows) +
        'Storage Area Type= 1 \r\n'
        'Storage Area Area= 10000 \r\n'
        'Storage Area Min Elev= 0 \r\n'
        'Storage Area Is2D=-1 \r\n'
        'Storage Area Point Generation Data=,,60.000000,60.000000 \r\n'
        'Storage Area 2D Points= 1 \r\n'
        '      50.0000000      50.0000000                \r\n'
        'Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00 \r\n'
        '2D Face Area Laminar Depth=0.06 \r\n'
        'Storage Area Mannings=0.0400 \r\n'
        'Custom Setting=retained \r\n'
        '2D Face Area Tolerance=0.0100 \r\n'
        '\r\n'
        'Storage Area=OtherArea,0,0\r\n'
        'Storage Area Type= 0 \r\n'
        'LCMann Time=0\r\n'
    ).encode() + b'Unrelated Text=legacy \xe9'
    path = tmp_path / 'records.g01'
    path.write_bytes(content)
    return path, content


@pytest.mark.parametrize('explicit_spacing', [False, True])
def test_unchanged_perimeter_preserves_every_byte(tmp_path, explicit_spacing):
    path, original = _fixture(tmp_path)
    kwargs = {'point_generation_data': ',,60.000000,60.000000'} if explicit_spacing else {}
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=COORDS, create_backup=False, **kwargs
    )
    assert path.read_bytes() == original


def test_spacing_update_changes_only_requested_record(tmp_path):
    path, original = _fixture(tmp_path)
    backup = GeomStorage.set_2d_flow_area_perimeter(
        str(path), 'MainArea', coordinates=COORDS, point_generation_data=',,30,30'
    )
    assert backup.read_bytes() == original
    assert path.read_bytes() == original.replace(
        b'Storage Area Point Generation Data=,,60.000000,60.000000 ',
        b'Storage Area Point Generation Data=,,30,30 ',
    )


@pytest.mark.parametrize('recompute_centroid', [False, True])
def test_changed_perimeter_preserves_unmanaged_records(tmp_path, recompute_centroid):
    path, original = _fixture(tmp_path)
    coords = [(0., 0.), (200., 0.), (200., 100.), (100., 150.), (0., 100.), (0., 0.)]
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=coords,
        recompute_centroid=recompute_centroid, create_backup=False,
    )
    updated = path.read_bytes()
    before = original.split(b'Storage Area Surface Line=', 1)
    after = updated.split(b'Storage Area Surface Line=', 1)
    if not recompute_centroid:
        assert before[0] == after[0]
    old_tail = before[1].split(b'Storage Area Type=', 1)[1]
    new_tail = after[1].split(b'Storage Area Type=', 1)[1]
    old_mesh_start = old_tail.index(b'Storage Area 2D Points=')
    new_mesh_start = new_tail.index(b'Storage Area 2D Points=')
    assert old_tail[:old_mesh_start] == new_tail[:new_mesh_start]
    assert old_tail.split(b'2D Face Area Laminar Depth=', 1)[1] == new_tail.split(
        b'2D Face Area Laminar Depth=', 1
    )[1]
    assert b'Storage Area 2D Points= 0' in updated
    assert b'01Jan2026 00:00:00' not in updated
    surface = after[1].split(b'Storage Area Type=', 1)[0].splitlines()
    assert surface[0] == b' 6 '
    assert len(surface[1:]) == 6
    assert all(len(row) == 48 and row.endswith(b' ' * 16) for row in surface[1:])
    info = GeomStorage._inspect_storage_area_block(updated.decode(errors='surrogateescape').splitlines(True)[2:])
    assert GeomStorage._parse_surface_line_coords(updated.decode(errors='surrogateescape').splitlines(True)[2:], info) == coords


@pytest.mark.parametrize('values_per_line', [2, 4, 10])
@pytest.mark.parametrize('padding', ['', ' ' * 16])
def test_changed_perimeter_uses_native_rows_with_source_padding(tmp_path, values_per_line, padding):
    path, original = _fixture(tmp_path)
    fields = [value for xy in COORDS for value in xy]
    rows = [
        ''.join(f'{v:16.7f}' for v in fields[i:i + values_per_line]) + padding + '\r\n'
        for i in range(0, len(fields), values_per_line)
    ]
    start = original.index(b'\r\n', original.index(b'Storage Area Surface Line=')) + 2
    end = original.index(b'Storage Area Type=')
    path.write_bytes(original[:start] + ''.join(rows).encode() + original[end:])
    changed = [(x + 200, y) for x, y in COORDS]
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=changed, create_backup=False,
    )
    lines = path.read_bytes()[start:].split(b'Storage Area Type=', 1)[0].splitlines()
    assert len(lines) == len(COORDS)
    assert all(len(row) == 32 + len(padding) for row in lines)
    assert all(row.endswith(padding.encode()) for row in lines)
    block = path.read_text(errors='surrogateescape').splitlines(True)[2:]
    assert GeomStorage._parse_surface_line_coords(
        block, GeomStorage._inspect_storage_area_block(block)
    ) == changed
    areas = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    assert list(areas.geometry.iloc[0].exterior.coords) == changed


def test_centroid_only_changes_header(tmp_path):
    path, original = _fixture(tmp_path)
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=COORDS, recompute_centroid=True, create_backup=False,
    )
    assert path.read_bytes() == original.replace(
        b'Storage Area=MainArea     ,50.0000000,50.0000000',
        b'Storage Area=MainArea,50.0000000,50.0000000',
    )


def test_existing_area_without_perimeter_gains_owned_records(tmp_path):
    path = tmp_path / 'incomplete.g01'
    path.write_bytes(b'Geom Title=Test\r\nStorage Area=MainArea,0,0\r\n')
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=COORDS, create_backup=False,
    )
    block = path.read_text().splitlines(True)[1:]
    info = GeomStorage._inspect_storage_area_block(block)
    assert GeomStorage._parse_surface_line_coords(block, info) == COORDS
    assert info['is_2d']
    assert info['points_idx'] > info['surface_line_idx']


@pytest.mark.integration
def test_public_bald_eagle_perimeters_are_byte_identical(tmp_path):
    import os

    if os.environ.get('RAS_COMMANDER_TEST_EXAMPLES') != '1':
        pytest.skip('Set RAS_COMMANDER_TEST_EXAMPLES=1 to extract the public example')
    from ras_commander import RasExamples

    project = RasExamples.extract_project('BaldEagleCrkMulti2D', output_path=tmp_path)
    path = project / 'BaldEagleDamBrk.g11'
    original = path.read_bytes()
    areas = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    two_d = areas.loc[areas['is_2d']]
    assert len(two_d) == 2
    for _, area in two_d.iterrows():
        GeomStorage.set_2d_flow_area_perimeter(
            path, area['Name'], geometry=area.geometry, create_backup=False,
        )
        assert path.read_bytes() == original

    target = two_d.iloc[1]
    source_lines = path.read_text().splitlines(True)
    start, end, old_block = GeomStorage._find_storage_area_block(source_lines, target['Name'])
    coords = list(target.geometry.exterior.coords)
    coords[1] = (coords[1][0] + 1., coords[1][1])
    GeomStorage.set_2d_flow_area_perimeter(
        path, target['Name'], coordinates=coords, create_backup=False,
    )
    new_lines = path.read_text().splitlines(True)
    new_start, new_end, new_block = GeomStorage._find_storage_area_block(new_lines, target['Name'])
    assert source_lines[:start] == new_lines[:new_start]
    assert source_lines[end:] == new_lines[new_end:]

    def unmanaged(block):
        info = GeomStorage._inspect_storage_area_block(block)
        managed = set(range(info['surface_line_idx'], info['surface_line_end']))
        managed.update(range(info['points_idx'], info['points_end']))
        managed.add(info['points_time_idx'])
        return [line for index, line in enumerate(block) if index not in managed]

    assert unmanaged(old_block) == unmanaged(new_block)
    readback = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    polygon = readback.loc[readback['Name'] == target['Name']].geometry.iloc[0]
    from shapely.geometry import Polygon
    assert polygon.equals_exact(Polygon(coords), tolerance=1e-6)


@pytest.mark.parametrize('first_record', [
    'Storage Area 2D Points= 0',
    'Storage Area 2D PointsPerimeterTime=old',
    'Storage Area Point Generation Data=,,50,50',
])
def test_missing_surface_insert_precedes_same_index_replacement(tmp_path, first_record):
    path = tmp_path / 'missing.g01'
    path.write_bytes((
        f'Storage Area=MainArea,0,0\r\n{first_record}\r\nStorage Area Is2D=-1\r\n'
    ).encode())
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=COORDS, point_generation_data=(None, None, 25, 25),
        create_backup=False,
    )
    result = path.read_text()
    assert result.count('Storage Area Surface Line=') == 1
    assert result.count('Storage Area 2D Points=') == 1
    assert result.count('Storage Area Point Generation Data=') == 1
    areas = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    assert list(areas.geometry.iloc[0].exterior.coords) == COORDS


@pytest.mark.parametrize('last_record', ['', '\nStorage Area Is2D=-1'])
def test_insert_after_unterminated_last_record(tmp_path, last_record):
    path = tmp_path / 'unterminated.g01'
    path.write_text('Storage Area=MainArea,0,0' + last_record)
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=COORDS, create_backup=False,
    )
    areas = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    assert list(areas.geometry.iloc[0].exterior.coords) == COORDS
    assert areas['is_2d'].iloc[0]


@pytest.mark.parametrize('count', ['', 'bad', '-1', '99'])
@pytest.mark.parametrize('changed', [False, True])
def test_invalid_surface_count_is_repaired(tmp_path, count, changed):
    path, original = _fixture(tmp_path)
    path.write_bytes(original.replace(b'Storage Area Surface Line= 5 ',
                                     f'Storage Area Surface Line= {count} '.encode()))
    coords = [(x + 200, y) for x, y in COORDS] if changed else COORDS
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=coords, create_backup=False,
    )
    areas = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    assert list(areas.geometry.iloc[0].exterior.coords) == coords
    padding = b'  ' if count == '' else b' '
    assert b'Storage Area Surface Line= 5' + padding + b'\r\n' in path.read_bytes()


def test_numeric_equivalent_spacing_preserves_original_bytes(tmp_path):
    path, original = _fixture(tmp_path)
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=COORDS,
        point_generation_data=(None, None, 60., 60.), create_backup=False,
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize('section', ['surface', 'points'])
def test_section_replacement_preserves_blank_separator(tmp_path, section):
    path = tmp_path / 'separator.g01'
    source = 'Storage Area=MainArea,0,0\r\nStorage Area Surface Line= 5\r\n'
    source += ''.join(f'{x:16.7f}{y:16.7f}\r\n' for x, y in COORDS)
    if section == 'points':
        source += 'Storage Area Is2D=-1\r\nStorage Area 2D Points= 1\r\n'
        source += f'{50.:16.7f}{50.:16.7f}\r\n'
    suffix = '\r\n \t\r\nStorage Area=OtherArea,0,0\r\nStorage Area Type= 0 \r\n'
    path.write_bytes((source + suffix).encode())
    GeomStorage.set_2d_flow_area_perimeter(
        path, 'MainArea', coordinates=[(x + 200, y) for x, y in COORDS], create_backup=False,
    )
    assert path.read_bytes().endswith(suffix.encode())
    areas = GeomStorage.get_storage_area_polygons(path, exclude_2d=False)
    assert areas['Name'].tolist() == ['MainArea']
