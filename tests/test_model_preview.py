from edakit.threed.preview import parse_obj, render_model_png
import pytest


def test_obj_materials_negative_indices_and_rotation():
    mesh = parse_obj(b'newmtl body\nKd 0.8 0.2 0.1\nv 0 0 0\nv 3 0 0\nv 0 2 0\nusemtl body\nf -3/-1 -2/-1 -1/-1\n')
    assert mesh.faces[0][0] == (0, 1, 2)
    assert mesh.faces[0][1] == (0.8, 0.2, 0.1)
    assert render_model_png(b'v 0 0 0\nv 3 0 0\nv 0 2 1\nf 1 2 3', 512, 0) != render_model_png(b'v 0 0 0\nv 3 0 0\nv 0 2 1\nf 1 2 3', 512, 45)


@pytest.mark.parametrize('data', [b'not an obj', b'v nan 0 0', b'v 0 0 0\nf 0 2 3'])
def test_bad_obj_is_rejected(data):
    with pytest.raises(ValueError):
        parse_obj(data)
