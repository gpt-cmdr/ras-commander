import pytest
from ras_commander.geom._bc_projection import project_pieces, invert_station

RING = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]


def test_offset_projection_and_both_cuts():
    pieces = project_pieces([(1, -2), (5, -2), (9, -2)], RING)
    assert invert_station(pieces, 2) == pytest.approx(1)
    assert invert_station(pieces, 8) == pytest.approx(7)


def test_reverse_offset():
    pieces = project_pieces([(9, -2), (1, -2)], RING)
    assert invert_station(pieces, 8) == pytest.approx(1)


def test_doubled_back_refused():
    with pytest.raises(ValueError, match='Backwards'):
        project_pieces([(1, -2), (9, -2), (3, -2)], RING)


def test_nonadjacent_equal_edges_refused():
    with pytest.raises(ValueError, match='Ambiguous|Discontinuous'):
        project_pieces([(2, 5), (8, 5)], RING)


def test_bounded_work():
    with pytest.raises(ValueError, match='work limit'):
        project_pieces([(1, -2), (9, -2)], RING, work_limit=1)


@pytest.mark.parametrize('points', [[(5,5),(9,-1)], [(9,-1),(5,5)]])
def test_ambiguous_drawn_endpoint_refused(points):
    with pytest.raises(ValueError, match='Ambiguous'):
        project_pieces(points, RING)


@pytest.mark.parametrize('reverse', [False, True])
def test_narrow_channel_nonadjacent_ties_refused(reverse):
    ring = [(0,0), (1e-6,0), (1e-6,10), (0,10), (0,0)]
    points = [(5e-7,2), (5e-7,8)]
    with pytest.raises(ValueError, match='Ambiguous'):
        project_pieces(points[::-1] if reverse else points, ring)

