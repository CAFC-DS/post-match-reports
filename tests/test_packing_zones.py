import numpy as np

from src.report.expanded import impect_zones as iz
from src.report.expanded import packing_zones as pz
from src.report.expanded.inpossession import PACKING_ZONE_GROUPS


def _grid():
    x, y = np.meshgrid(np.arange(-255, 255) + .5, np.arange(-335, 335) + .5)
    return x, y, np.hypot(x, y - 335)


def test_zones_tile_the_impect_pitch_at_both_levels_of_detail():
    x, y, r = _grid()
    for detail, zones in iz._ZONES.items():
        cover = sum(iz._zone_mask(x, y, r, borders) for borders, _ in zones.values()).astype(int)
        assert (cover == 1).all(), detail


def test_every_group_used_by_the_report_is_a_default_zone():
    assert set(PACKING_ZONE_GROUPS.values()) <= set(iz.PACKING_ZONES["default"])
    assert set(pz.LABELS) == set(iz.PACKING_ZONES["default"])


def test_horizontal_rotation_keeps_attack_right_and_attackers_left_on_top():
    assert pz._to_horizontal(0, 300) == (300, 0)            # far up the Impect pitch -> far right
    assert pz._to_horizontal(-100, 0)[1] > 0                # attacker's left (-x) -> top


def test_zone_image_tints_only_zones_with_a_value():
    image = pz._zone_image({"CM": 5.0}, "#d01012", 5.0, "default", 0)
    top_left = image[5, 5]                                  # own goal, attacker's left: untouched zone
    assert not np.allclose(image[image.shape[0] // 2, 360], top_left)   # CM centre is tinted


def test_chart_renders_with_and_without_values():
    assert pz.zone_chart({}, "#d01012", 1).startswith("data:image/png")
    assert pz.zone_chart({"CB": 2, "IB": 7}, "#857f72", 7, sub={"IB": "3 def."}, small=True).startswith("data:image/png")
