from __future__ import annotations

from PIL import Image, ImageStat

from viralcut.config import EditConfig
from viralcut.plates import blur_image, intro_frames, outro_frames, zoom_image


def base_image(size=(216, 384)) -> Image.Image:
    img = Image.new("RGB", size, (20, 90, 180))
    for x in range(0, size[0], 24):
        for y in range(0, size[1], 24):
            img.paste((240, 220, 40), (x, y, min(x + 12, size[0]), min(y + 12, size[1])))
    return img


def sharpness(img: Image.Image) -> float:
    """Crude focus metric: stddev of the luminance channel."""
    return ImageStat.Stat(img.convert("L")).stddev[0]


def test_zoom_keeps_frame_size():
    img = base_image()
    assert zoom_image(img, 1.2).size == img.size
    assert zoom_image(img, 0.8).size == img.size
    assert zoom_image(img, 1.0) is img


def test_blur_reduces_detail():
    img = base_image()
    assert sharpness(blur_image(img, 12)) < sharpness(img) * 0.6


def test_intro_resolves_exactly_into_the_source_frame():
    cfg = EditConfig(intro="blurzoom", fps=30)
    frames = list(intro_frames(base_image(), cfg, 12, 1.0))
    assert len(frames) == 12
    # starts blurred/dark, ends on the untouched frame
    assert sharpness(frames[0]) < sharpness(frames[-1])
    assert ImageStat.Stat(frames[0]).mean[0] < ImageStat.Stat(frames[-1]).mean[0]
    diff = sum(abs(a - b) for a, b in zip(
        frames[-1].convert("L").getdata(), base_image().convert("L").getdata(), strict=True))
    assert diff / (frames[-1].width * frames[-1].height) < 2.0  # visually identical


def test_outro_fades_towards_black():
    cfg = EditConfig(outro="blurout", fps=30)
    frames = list(outro_frames(base_image(), cfg, 12, 1.0))
    assert ImageStat.Stat(frames[-1]).mean[0] < 12
    assert sharpness(frames[-1]) < sharpness(frames[0])


def test_flash_intro_starts_bright():
    cfg = EditConfig(intro="flash", fps=30)
    frames = list(intro_frames(base_image(), cfg, 10, 1.0))
    assert ImageStat.Stat(frames[0]).mean[0] > 200


def test_zoomout_outro_shrinks_the_frame():
    cfg = EditConfig(outro="zoomout", fps=30)
    frames = list(outro_frames(base_image(), cfg, 10, 1.0))
    assert frames[-1].size == base_image().size
