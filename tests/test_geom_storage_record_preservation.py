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
def test_changed_perimeter_keeps_source_row_convention(tmp_path, values_per_line, padding):
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
    assert [len(row) for row in lines] == [len(row.rstrip('\r\n')) for row in rows]
    assert all(row.endswith(padding.encode()) for row in lines)
    block = path.read_text(errors='surrogateescape').splitlines(True)[2:]
    assert GeomStorage._parse_surface_line_coords(
        block, GeomStorage._inspect_storage_area_block(block)
    ) == changed


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
