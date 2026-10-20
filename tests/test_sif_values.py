import xml.etree.ElementTree as ET

import pytest

from studio_core.sif import Angle, Animated, Color, Interp, Transform, Vec, Waypoint, value_xml


def xml(value: object) -> str:
    return ET.tostring(value_xml(value), encoding="unicode")


def test_static_values() -> None:
    assert xml(1.5) == '<real value="1.500000" />'
    assert xml(-0.0) == '<real value="0.000000" />'  # no negative zero
    assert xml(3) == '<integer value="3" />'
    assert xml(True) == '<bool value="true" />'
    assert xml("A") == "<string>A</string>"
    assert xml(Vec(1, -2)) == "<vector><x>1.000000</x><y>-2.000000</y></vector>"
    assert xml(Angle(90)) == '<angle value="90.000000" />'
    assert Color.hex("#ff8000") == Color(1.0, 128 / 255, 0.0)


def test_animated_waypoints() -> None:
    a = Animated("angle", (Waypoint(0, Angle(0), Interp.EASE), Waypoint(12, Angle(45))))
    assert xml(a) == (
        '<animated type="angle">'
        '<waypoint time="0f" before="halt" after="halt"><angle value="0.000000" /></waypoint>'
        '<waypoint time="12f" before="clamped" after="clamped"><angle value="45.000000" />'
        "</waypoint></animated>"
    )


def test_animated_validation() -> None:
    with pytest.raises(ValueError):
        Animated("angle", ())
    with pytest.raises(ValueError):
        Animated("angle", (Waypoint(5, Angle(0)), Waypoint(5, Angle(1))))
    with pytest.raises(ValueError):  # strings can only step
        Animated("string", (Waypoint(0, "A", Interp.LINEAR),))
    Animated("string", (Waypoint(0, "A", Interp.CONSTANT),))


def test_transform_composite() -> None:
    out = xml(Transform(offset=Vec(1, 2), angle=Angle(30)))
    assert out.startswith('<composite type="transformation"><offset><vector><x>1.000000</x>')
    assert "<skew_angle><angle" in out and "<scale><vector><x>1.000000</x><y>1.000000</y>" in out


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        value_xml(object())
