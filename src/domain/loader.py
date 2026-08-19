"""Load and validate the ConvFinQA dataset file into typed records.

Pure: reads one JSON file from disk and validates it against `src/domain/models.py`. No
network, no SDK, no clock. A record that fails schema validation is not skipped — pydantic's
`ValidationError` propagates unmodified, so a malformed record fails the whole load rather than
silently shrinking the set.
"""

import json
from pathlib import Path

from src.domain.models import ConvFinQARecord

DATASET_SPLITS = ("train", "dev")


def load_dataset(path: Path) -> dict[str, list[ConvFinQARecord]]:
    """Load and validate every record in each split of the dataset file at `path`.

    Returns a dict keyed by split name (`train`, `dev`) mapping to validated records. Raises
    whatever `json.JSONDecodeError` or pydantic `ValidationError` the first malformed input
    produces — a record that does not validate exits the load, it is never dropped silently.
    """
    raw = json.loads(path.read_text())
    return {
        split: [ConvFinQARecord.model_validate(record) for record in raw[split]]
        for split in DATASET_SPLITS
    }
