"""Validate the dataset loader against the real `data/convfinqa_dataset.json` file.

No fixtures, no mocking: this loads the actual 21MB dataset file, exercising the exact path
the eval pipeline uses. Three facts are asserted, established independently of this test (see
the plan): exact train/dev record counts, zero document overlap between train and dev (the
proof that iterating on train cannot leak into the once-only dev report number), and that
every record validates against the pydantic schema (loading without raising is sufficient
proof of this, since `ConvFinQARecord.model_validate` is what does the validating).
"""

import re
from pathlib import Path

from src.domain.loader import load_dataset
from src.domain.models import ConvFinQARecord

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "convfinqa_dataset.json"

EXPECTED_TRAIN_COUNT = 3037
EXPECTED_DEV_COUNT = 421

# An id embeds a document reference like `Single_MRO/2007/page_134.pdf-1` or
# `Double_RSG/2016/page_144.pdf`. Stripping the leading Single_/Double_ prefix, the trailing
# `.pdf`, and any trailing `-N` turn-index suffix yields the underlying document key, e.g.
# `MRO/2007/page_134`.
DOCUMENT_KEY_PATTERN = re.compile(r"^(?:Single|Double)_(.+)\.pdf(?:-\d+)?$")


def _document_key(record_id: str) -> str:
    """Extract the underlying document key from a record id, stripping split/turn markers."""
    match = DOCUMENT_KEY_PATTERN.match(record_id)
    assert match is not None, (
        f"record id does not match expected pattern: {record_id!r}"
    )
    return match.group(1)


def test_load_dataset_returns_expected_split_counts() -> None:
    """The real dataset file has exactly 3037 train and 421 dev records."""
    dataset = load_dataset(DATA_PATH)

    assert len(dataset["train"]) == EXPECTED_TRAIN_COUNT
    assert len(dataset["dev"]) == EXPECTED_DEV_COUNT


def test_train_and_dev_share_no_underlying_document() -> None:
    """No document referenced in train is also referenced in dev.

    This is the proof behind the run's train/dev split strategy: iterating on train cannot
    leak into the dev number reported once at the end, because the two splits never describe
    the same source document.
    """
    dataset = load_dataset(DATA_PATH)

    train_keys = {_document_key(record.id) for record in dataset["train"]}
    dev_keys = {_document_key(record.id) for record in dataset["dev"]}

    assert train_keys & dev_keys == set()


def test_every_loaded_record_is_a_validated_record() -> None:
    """Every record returned by the loader is a fully validated `ConvFinQARecord` instance."""
    dataset = load_dataset(DATA_PATH)

    for split_records in dataset.values():
        for record in split_records:
            assert isinstance(record, ConvFinQARecord)
