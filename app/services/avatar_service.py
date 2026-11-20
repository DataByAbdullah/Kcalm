"""Bounded, local-only validation and storage of user avatars."""
import base64
import binascii
from io import BytesIO
import struct
import warnings
import zlib

from PIL import Image
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import APIErrorException
from app.models.user import User


MAX_AVATAR_BYTES = 307200
MAX_AVATAR_BASE64_LENGTH = 4 * ((MAX_AVATAR_BYTES + 2) // 3)
MAX_AVATAR_DATA_URL_LENGTH = len("data:image/jpeg;base64,") + MAX_AVATAR_BASE64_LENGTH
MAX_AVATAR_PIXELS = 4_194_304
MAX_AVATAR_DIMENSION = 4096
MAX_AVATAR_METADATA_BYTES = 512 * 1024
AVATAR_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def invalid_avatar_error() -> APIErrorException:
    return APIErrorException(422, "INVALID_AVATAR", "Provide a valid static JPEG, PNG, or WebP image Data URL.")


def avatar_too_large_error() -> APIErrorException:
    return APIErrorException(422, "AVATAR_TOO_LARGE", "Avatar exceeds the byte or pixel limits.")


def validate_avatar_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise invalid_avatar_error()
    if max(width, height) > MAX_AVATAR_DIMENSION or width * height > MAX_AVATAR_PIXELS:
        raise avatar_too_large_error()


def bounded_metadata_decompress(content: bytes, remaining: int) -> bytes:
    """Never ask zlib for more than the remaining per-avatar budget plus one."""
    decoder = zlib.decompressobj()
    try:
        expanded = decoder.decompress(content, remaining + 1)
    except zlib.error:
        raise invalid_avatar_error() from None
    if len(expanded) > remaining:
        raise avatar_too_large_error()
    # Require exactly one complete stream, including its checksum. Do not flush:
    # an unbounded flush could allocate output before its size can be checked.
    if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise invalid_avatar_error()
    return expanded


def png_metadata_size(kind: bytes, data: bytes, remaining: int) -> int:
    if kind == b"tEXt":
        keyword, separator, text = data.partition(b"\0")
        if not separator or not 1 <= len(keyword) <= 79 or b"\0" in text:
            raise invalid_avatar_error()
    if kind not in {b"zTXt", b"iTXt", b"iCCP"}:
        if len(data) > remaining:
            raise avatar_too_large_error()
        return len(data)

    keyword, separator, rest = data.partition(b"\0")
    if not separator or not 1 <= len(keyword) <= 79:
        raise invalid_avatar_error()
    prefix_size = len(keyword) + 1
    if kind == b"iTXt":
        if len(rest) < 2 or rest[0] not in (0, 1) or rest[1] != 0:
            raise invalid_avatar_error()
        compressed = bool(rest[0])
        language, separator, rest = rest[2:].partition(b"\0")
        if not separator:
            raise invalid_avatar_error()
        translated, separator, payload = rest.partition(b"\0")
        if not separator:
            raise invalid_avatar_error()
        prefix_size += 2 + len(language) + 1 + len(translated) + 1
        try:
            language.decode("ascii")
            translated.decode("utf-8")
        except UnicodeError:
            raise invalid_avatar_error() from None
    else:
        if not rest or rest[0] != 0:
            raise invalid_avatar_error()
        compressed, payload = True, rest[1:]
        prefix_size += 1
    if prefix_size > remaining:
        raise avatar_too_large_error()
    available = remaining - prefix_size
    if compressed:
        expanded = bounded_metadata_decompress(payload, available)
    else:
        if len(payload) > available:
            raise avatar_too_large_error()
        expanded = payload
    if kind == b"iTXt":
        try:
            expanded.decode("utf-8")
        except UnicodeError:
            raise invalid_avatar_error() from None
    elif kind == b"zTXt" and b"\0" in expanded:
        raise invalid_avatar_error()
    return prefix_size + len(expanded)


def validate_png_metadata(content: bytes) -> None:
    """Check all chunks, including metadata after IDAT, before Pillow opens PNG.

    PNG text and ICC chunks can inflate independently of the pixel canvas.
    Count every ancillary chunk, even duplicate keys that Pillow overwrites.
    JPEG APP/COM and WebP EXIF/XMP/ICC are stored without metadata inflation by
    the decoders used here; their metadata is bounded by MAX_AVATAR_BYTES.
    """
    offset, metadata_bytes = 8, 0
    view = memoryview(content)
    while offset + 12 <= len(content):
        length = int.from_bytes(view[offset:offset + 4], "big")
        kind = content[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(content) or not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind):
            raise invalid_avatar_error()
        if binascii.crc32(view[offset + 4:end - 4]) & 0xFFFFFFFF != int.from_bytes(view[end - 4:end], "big"):
            raise invalid_avatar_error()
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise invalid_avatar_error()
            validate_avatar_dimensions(
                int.from_bytes(view[offset + 8:offset + 12], "big"),
                int.from_bytes(view[offset + 12:offset + 16], "big"),
            )
        if kind[0] & 0x20:
            metadata_bytes += png_metadata_size(
                kind, content[offset + 8:end - 4], MAX_AVATAR_METADATA_BYTES - metadata_bytes,
            )
        if kind == b"IEND":
            if length or end != len(content):
                raise invalid_avatar_error()
            return
        offset = end
    raise invalid_avatar_error()


def validate_webp_canvas(content: bytes) -> None:
    """Bound the canvas before libwebp's decoder constructor can allocate it.

    WebP's first chunk is VP8 (lossy), VP8L (lossless), or VP8X (extended).
    Pillow still validates the full file after this header-only size check.
    """
    if int.from_bytes(content[4:8], "little") != len(content) - 8:
        raise invalid_avatar_error()
    chunk = content[12:16]
    if chunk == b"VP8X" and len(content) >= 30:
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
    elif chunk == b"VP8 " and len(content) >= 30 and content[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(content[26:28], "little") & 0x3FFF
        height = int.from_bytes(content[28:30], "little") & 0x3FFF
    elif chunk == b"VP8L" and len(content) >= 25 and content[20] == 0x2F:
        bits = int.from_bytes(content[21:25], "little")
        width = 1 + (bits & 0x3FFF)
        height = 1 + ((bits >> 14) & 0x3FFF)
    else:
        raise invalid_avatar_error()
    validate_avatar_dimensions(width, height)


def normalize_avatar_data_url(value: str) -> str:
    # Reject before splitting, allocating decoded bytes, or invoking a decoder.
    if len(value) > MAX_AVATAR_DATA_URL_LENGTH:
        raise avatar_too_large_error()
    header, separator, encoded = value.partition(",")
    headers = {f"data:{mime};base64": mime for mime in AVATAR_FORMATS}
    mime = headers.get(header.lower())
    if not separator or mime is None or not encoded:
        raise invalid_avatar_error()
    if len(encoded) > MAX_AVATAR_BASE64_LENGTH:
        raise avatar_too_large_error()
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise invalid_avatar_error() from None
    if len(content) > MAX_AVATAR_BYTES:
        raise avatar_too_large_error()
    canonical = base64.b64encode(content).decode("ascii")
    # validate=True alone accepts some noncanonical padding and pad bits.
    if canonical != encoded:
        raise invalid_avatar_error()
    expected_format = AVATAR_FORMATS[mime]
    signatures_match = {
        "JPEG": content.startswith(b"\xff\xd8\xff"),
        "PNG": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "WEBP": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not signatures_match[expected_format]:
        raise invalid_avatar_error()
    if expected_format == "PNG":
        validate_png_metadata(content)
    if expected_format == "WEBP":
        validate_webp_canvas(content)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=[expected_format]) as image:
                if image.format != expected_format:
                    raise invalid_avatar_error()
                validate_avatar_dimensions(image.width, image.height)
                if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                    raise invalid_avatar_error()
                image.verify()
            # Structure/CRC verification alone cannot detect every bad pixel stream.
            with Image.open(BytesIO(content), formats=[expected_format]) as image:
                image.load()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise avatar_too_large_error() from None
    except (OSError, ValueError, SyntaxError, EOFError, struct.error):
        raise invalid_avatar_error() from None
    return f"data:{mime};base64,{canonical}"


def save_avatar(db: Session, user: User, avatar: str | None) -> User:
    # Setting the deferred column does not fetch its previous large value.
    user.avatar_data_url = avatar
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        # SQL errors can contain bound image parameters; never chain them into
        # the application's public error or logging path.
        raise APIErrorException(500, "AVATAR_UPDATE_FAILED", "Avatar could not be updated.") from None
    return user
