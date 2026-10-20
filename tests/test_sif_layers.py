from studio_core.sif import Canvas, Group, ImportLayer, Space, Switch, Vec


def test_import_layer_with_pivot_puts_the_pivot_at_local_origin() -> None:
    space = Space(1920, 1080, ppu=100)
    layer = ImportLayer.with_pivot("arm", "arm.png", (50, 200), (25, 20), space)
    # 25 px left of the pivot, 20 px above it; 25 px right, 180 px below.
    assert layer.tl == Vec(-0.25, 0.2)
    assert layer.br == Vec(0.25, -1.8)


def test_canvas_header_and_determinism() -> None:
    def build() -> str:
        c = Canvas(width=1920, height=1080, fps=24, frames=240, ppu=120)
        c.layers.append(Group("g", children=[Switch("mouth", active="X")]))
        return c.to_string()

    text = build()
    assert 'view-box="-8.000000 4.500000 8.000000 -4.500000"' in text
    assert 'end-time="239f"' in text and 'fps="24"' in text
    assert '<layer type="switch"' in text and "<string>X</string>" in text
    assert text == build()  # byte-identical output for the same input
