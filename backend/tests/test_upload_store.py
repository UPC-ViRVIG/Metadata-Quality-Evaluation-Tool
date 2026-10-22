"""
tests/test_upload_store.py
--------------------------
Unit tests for the uploaded file store.

Covers the contract the upload endpoint depends on: a stored file is
readable at the returned path, its serialisation is guessed from the
extension, and a client-supplied name can neither escape the upload
directory nor collide with an earlier upload.

Files are written into the real upload directory and removed again, so
the suite needs no server and no fixtures.
"""

import pytest
from pathlib import Path

from datasource.upload_store import (
    MAX_UPLOAD_BYTES,
    UPLOAD_DIR,
    UploadError,
    save,
)


TURTLE = b'<http://example.org/a> <http://purl.org/dc/elements/1.1/title> "A" .\n'


@pytest.fixture
def cleanup():
    """Remove whatever a test stored, leaving the directory as found."""
    stored: list[str] = []
    yield stored
    for path in stored:
        Path(path).unlink(missing_ok=True)


# ------------------------------------------------------------------
# SUCCESS CASES
# ------------------------------------------------------------------

def test_saved_file_is_readable_at_returned_path(cleanup):
    """The path handed back must load as an ordinary local file."""

    result = save("dataset.ttl", TURTLE)
    cleanup.append(result["file_path"])

    assert Path(result["file_path"]).read_bytes() == TURTLE
    assert result["size_bytes"] == len(TURTLE)
    assert result["filename"] == "dataset.ttl"


@pytest.mark.parametrize("name,expected", [
    ("dataset.ttl",    "turtle"),
    ("dataset.rdf",    "xml"),
    ("dataset.nt",     "nt"),
    ("dataset.n3",     "n3"),
    ("dataset.jsonld", "json-ld"),
    ("dataset.bin",    None),
])
def test_format_is_guessed_from_the_extension(name, expected, cleanup):
    """An unrecognised extension reports no format rather than a wrong one."""

    result = save(name, TURTLE)
    cleanup.append(result["file_path"])

    assert result["format"] == expected


def test_same_name_twice_does_not_overwrite(cleanup):
    """
    Re-uploading must land at a new path.

    The graph cache is keyed by source configuration, not by
    modification time, so reusing a path would serve the previous
    contents from cache.
    """
    first = save("dataset.ttl", TURTLE)
    second = save("dataset.ttl", TURTLE + b"\n")
    cleanup.extend([first["file_path"], second["file_path"]])

    assert first["file_path"] != second["file_path"]
    assert Path(first["file_path"]).exists()


# ------------------------------------------------------------------
# NAME HANDLING
# ------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "../../evil.ttl",
    "..\\..\\evil.ttl",
    "/etc/passwd.ttl",
    "C:\\Windows\\evil.ttl",
])
def test_client_name_cannot_escape_the_upload_directory(name, cleanup):
    """Only the final path component of a supplied name is used."""

    result = save(name, TURTLE)
    cleanup.append(result["file_path"])

    stored = Path(result["file_path"])
    assert stored.parent == UPLOAD_DIR
    assert ".." not in result["filename"]


def test_unsafe_characters_are_replaced(cleanup):
    """Spaces and punctuation are reduced to a safe single component."""

    result = save("my data (final).ttl", TURTLE)
    cleanup.append(result["file_path"])

    assert result["filename"] == "my_data__final_.ttl"
    assert result["format"] == "turtle"


# ------------------------------------------------------------------
# ERROR CASES
# ------------------------------------------------------------------

def test_empty_file_is_rejected():
    """An empty upload is a mistake worth reporting, not an empty graph."""

    with pytest.raises(UploadError, match="empty"):
        save("dataset.ttl", b"")


def test_oversized_file_is_rejected():
    """The size limit is enforced before anything is written."""

    with pytest.raises(UploadError, match="larger than"):
        save("dataset.ttl", b"x" * (MAX_UPLOAD_BYTES + 1))


@pytest.mark.parametrize("name", ["", "...", "___", None])
def test_unusable_name_is_rejected(name):
    """A name with nothing safe left in it is refused."""

    with pytest.raises(UploadError, match="usable name"):
        save(name, TURTLE)
