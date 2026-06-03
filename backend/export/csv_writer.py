import csv
import io
import json
from typing import Any


def rows_to_csv(rows: list[dict]) -> str:
    """
    Serialise a list of dicts to a CSV string.

    Column headers are derived from the keys of the first row. All
    subsequent rows must have the same keys (extra keys are ignored,
    missing keys produce empty cells).

    Parameters
    ----------
    rows : list of dict
        The data rows to serialise. Must be non-empty.

    Returns
    -------
    str
        UTF-8 CSV string including a header row.

    Raises
    ------
    ValueError
        If rows is empty.
    """
    if not rows:
        raise ValueError("Cannot serialise an empty rows list to CSV.")

    headers = list(rows[0].keys())
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=headers,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()

    for row in rows:
        writer.writerow({k: _coerce(v) for k, v in row.items()})

    return output.getvalue()


def _coerce(value: Any) -> str:
    """
    Coerce a value to a CSV-safe string.

    Parameters
    ----------
    value : Any

    Returns
    -------
    str
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)