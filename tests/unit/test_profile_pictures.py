from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from app.services import profile_pictures as pp


def upload(fmt="PNG", size=(800, 400), name="p.png", **save_kwargs):
    buffer = BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=fmt, **save_kwargs)
    return SimpleUploadedFile(name, buffer.getvalue())


def decode(content):
    return Image.open(BytesIO(content.read()))


class TestProcessing:
    @pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
    def test_allowed_formats_become_a_square_webp(self, fmt):
        image = decode(pp.process_profile_picture(upload(fmt)))
        assert (image.format, image.size) == ("WEBP", (pp.OUTPUT_SIZE, pp.OUTPUT_SIZE))

    @pytest.mark.parametrize("fmt", ["GIF", "BMP"])
    def test_other_formats_are_refused(self, fmt):
        with pytest.raises(ValidationError) as error:
            pp.process_profile_picture(upload(fmt))
        assert error.value.code == "bad_format"

    def test_svg_and_non_images_are_refused(self):
        for content, name in [(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "a.svg"), (b"MZ\x90\x00 exe", "a.png")]:
            with pytest.raises(ValidationError):
                pp.process_profile_picture(SimpleUploadedFile(name, content))

    def test_oversized_file_is_refused_before_decoding(self):
        big = SimpleUploadedFile("big.png", b"x" * (pp.MAX_UPLOAD_BYTES + 1))
        with pytest.raises(ValidationError) as error:
            pp.process_profile_picture(big)
        assert error.value.code == "too_large"

    def test_decompression_bomb_is_refused(self, monkeypatch):
        monkeypatch.setattr("app.services.images.MAX_SOURCE_PIXELS", 100)
        with pytest.raises(ValidationError) as error:
            pp.process_profile_picture(upload(size=(50, 50)))
        assert error.value.code == "too_many_pixels"

    def test_exif_metadata_is_stripped(self):
        exif = Image.Exif()
        exif[0x010F] = "SecretCamera"
        image = decode(pp.process_profile_picture(upload("JPEG", exif=exif)))
        assert not image.getexif()

    def test_filename_is_random_and_never_the_visitor_one(self):
        names = {pp.profile_picture_path(None, "../../evil.php") for _ in range(2)}
        assert len(names) == 2 and all(n.endswith(".webp") and "/" not in n for n in names)
