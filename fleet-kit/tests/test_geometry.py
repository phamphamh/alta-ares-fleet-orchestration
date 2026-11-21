"""Unit tests for the exact geometry."""
import math

from fleetkit import geometry as g


def test_segment_tangent_to_the_cylinder_does_not_enter():
    assert not g.segment_enters_cylinder((600, 700, 60), (1400, 700, 60), (1000, 500), 200, 80)


def test_segment_slightly_inside_enters():
    assert g.segment_enters_cylinder((600, 699.99, 60), (1400, 699.99, 60), (1000, 500), 200, 80)


def test_flying_at_the_ceiling_does_not_enter_but_below_does():
    assert not g.segment_enters_cylinder((0, 500, 80), (2000, 500, 80), (1000, 500), 200, 80)
    assert g.segment_enters_cylinder((0, 500, 79.9), (2000, 500, 79.9), (1000, 500), 200, 80)


def test_sloped_leg_clears_the_ceiling_only_inside_the_footprint():
    # climbs from 0 to 200 m over 2000 m: inside the footprint (x 800 to 1200) the altitude is 80 to 120
    assert not g.segment_enters_cylinder((0, 500, 0), (2000, 500, 200), (1000, 500), 200, 80)
    assert g.segment_enters_cylinder((0, 500, 0), (2000, 500, 150), (1000, 500), 200, 80)


def test_vertical_leg_inside_the_footprint():
    assert g.segment_enters_cylinder((1000, 500, 0), (1000, 500, 60), (1000, 500), 200, 80)
    assert not g.segment_enters_cylinder((1000, 500, 80), (1000, 500, 120), (1000, 500), 200, 80)


def test_full_height_cylinder_is_never_overflown():
    assert g.segment_enters_cylinder((0, 0, 140), (200, 0, 140), (100, 0), 50)


def test_closest_approach_of_two_head_on_pieces():
    a = (0.0, 10.0, (0.0, 0.0, 50.0), (100.0, 0.0, 50.0))
    b = (0.0, 10.0, (100.0, 3.0, 50.0), (0.0, 3.0, 50.0))
    assert math.isclose(g.min_distance(a, b, 0.0, 10.0), 3.0, abs_tol=1e-9)


def test_close_interval_matches_a_hand_computation():
    # relative position (30, 0, 0) closing at 10 m/s: within 20 m from t = 1 to t = 5
    a = (0.0, 10.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    b = (0.0, 10.0, (30.0, 0.0, 0.0), (-70.0, 0.0, 0.0))
    lo, hi = g.close_intervals(a, b, 0.0, 10.0, 20.0)
    assert math.isclose(lo, 1.0, abs_tol=1e-9) and math.isclose(hi, 5.0, abs_tol=1e-9)


def test_stationary_pieces_use_the_constant_distance():
    a = (0.0, 5.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    b = (0.0, 5.0, (0.0, 39.0, 0.0), (0.0, 39.0, 0.0))
    assert g.close_intervals(a, b, 0.0, 5.0, 40.0) == (0.0, 5.0)
    assert g.close_intervals(a, b, 0.0, 5.0, 39.0) is None


def test_within_radius_interval():
    a = (0.0, 10.0, (0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
    lo, hi = g.within_radius_interval(a, 0.0, 10.0, (100.0, 0.0, 0.0), 30.0)
    assert math.isclose(lo, 7.0, abs_tol=1e-9) and math.isclose(hi, 10.0, abs_tol=1e-9)


def test_a_leg_that_only_touches_the_boundary_at_its_end_does_not_enter():
    assert not g.segment_enters_cylinder((0, 500, 60), (800, 500, 60), (1000, 500), 200, 80)    # ends on the circle
    assert not g.segment_enters_cylinder((1200, 500, 60), (2000, 500, 60), (1000, 500), 200, 80)  # starts on it
    assert g.segment_enters_cylinder((0, 500, 60), (800.01, 500, 60), (1000, 500), 200, 80)       # 1 cm inside
