from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from app.services import tasting_photos as tp


def upload(fmt="PNG", size=(3000, 1500), name="p.png"):
    buffer = BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue())


class TestProcessing:
    @pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
    def test_allowed_formats_become_a_bounded_webp(self, fmt):
        image = Image.open(BytesIO(tp.process_tasting_photo(upload(fmt)).read()))
        assert image.format == "WEBP" and image.size == (tp.MAX_SIDE, tp.MAX_SIDE // 2)  # ratio conservé

    def test_small_images_are_not_enlarged(self):
        image = Image.open(BytesIO(tp.process_tasting_photo(upload(size=(200, 100))).read()))
        assert image.size == (200, 100)

    @pytest.mark.parametrize("fmt", ["GIF", "BMP"])
    def test_other_formats_are_refused(self, fmt):
        with pytest.raises(ValidationError):
            tp.process_tasting_photo(upload(fmt))

    def test_svg_and_fake_images_are_refused(self):
        for content, name in [(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "a.svg"), (b"MZ\x90\x00", "a.png")]:
            with pytest.raises(ValidationError):
                tp.process_tasting_photo(SimpleUploadedFile(name, content))

    def test_oversized_file_is_refused(self):
        with pytest.raises(ValidationError) as error:
            tp.process_tasting_photo(SimpleUploadedFile("big.png", b"x" * (tp.MAX_UPLOAD_BYTES + 1)))
        assert error.value.code == "too_large"

    def test_metadata_is_stripped(self):
        image = Image.new("RGB", (50, 50), "red")
        exif = Image.Exif()
        exif[0x010F] = "SecretCamera"
        buffer = BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        result = Image.open(BytesIO(tp.process_tasting_photo(SimpleUploadedFile("a.jpg", buffer.getvalue())).read()))
        assert not result.getexif()

    def test_stored_name_is_random_and_ignores_the_visitor_filename(self):
        first, second = (tp.tasting_photo_path(None, "../../etc/passwd") for _ in range(2))
        assert first != second and first.startswith("tastings/") and first.endswith(".webp") and ".." not in first
