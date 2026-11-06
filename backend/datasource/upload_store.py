"""
datasource/upload_store.py
--------------------------
Storage for RDF files uploaded through the dashboard.

An uploaded file becomes an ordinary rdf_file source, so this module
only has to put the bytes somewhere the backend can read them again and
report back the path and serialisation format to use. The data source
strategies and the factory are untouched: uploading is a way of
obtaining a file, not a new kind of source.

Stored names carry a short random prefix. Two uploads of the same file
therefore land at different paths, which keeps the graph cache — keyed
by source configuration rather than by modification time — from serving
the previous contents after a file is re-uploaded.
"""

import re
import uuid
from pathlib import Path

from rdflib.util import guess_format

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

_UNSAFE_CHARS = re.compile(r"[^\w\-.]")


class UploadError(ValueError):
    """
    Raised when an uploaded file cannot be accepted.

    The message is written to be shown to the user directly, because
    every case is something they can act on: an empty file, one that is
    too large, or a name with nothing usable in it.
    """


def save(filename: str, content: bytes) -> dict:
    """
    Store an uploaded RDF file and describe how to load it.

    Parameters
    ----------
    filename : str
        Name reported by the browser. Only its final component is used,
        and unsafe characters are replaced, so a path sent by a client
        cannot decide where the file is written.
    content : bytes
        Raw file contents.

    Returns
    -------
    dict
        Structure:

            {
                "file_path":  str,
                "filename":   str,
                "format":     str | None,
                "size_bytes": int
            }

        file_path is what belongs in a source configuration, and format
        is the serialisation guessed from the extension, or None when
        the extension is not recognised.

    Raises
    ------
    UploadError
        If the file is empty, exceeds the size limit, or has no usable
        name.
    """
    if not content:
        raise UploadError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise UploadError(
            f"The uploaded file is larger than the {limit_mb} MB limit."
        )

    safe_name = _safe_name(filename)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    stored_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    stored_path.write_bytes(content)

    return {
        "file_path":  str(stored_path),
        "filename":   safe_name,
        "format":     guess_format(safe_name),
        "size_bytes": len(content),
    }


def _safe_name(filename: str) -> str:
    """
    Reduce a client-supplied filename to a safe single component.

    Parameters
    ----------
    filename : str
        Name as reported by the browser.

    Returns
    -------
    str
        The final path component with unsafe characters replaced.

    Raises
    ------
    UploadError
        If nothing usable remains.
    """
    base = Path(str(filename or "")).name
    safe = _UNSAFE_CHARS.sub("_", base).strip("._")
    if not safe:
        raise UploadError("The uploaded file has no usable name.")
    return safe
