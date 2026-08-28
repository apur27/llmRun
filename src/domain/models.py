"""Pydantic models for the ConvFinQA dataset records.

Schema mirrors `dataset.md`'s "Data Fields" section verbatim (the repo's own authoritative
source for the on-disk shape of `data/convfinqa_dataset.json`). Pure data classes: no I/O, no
SDK, no network. Loading and validating the real file is `src/domain/loader.py`'s job, not
this module's.
"""

from pydantic import BaseModel


class Document(BaseModel):
    """The source financial document a conversation is grounded in."""

    pre_text: str
    post_text: str
    table: dict[str, dict[str, float | str | int]]


class Dialogue(BaseModel):
    """The conversational turns, their gold answers, and their DSL programs."""

    conv_questions: list[str]
    conv_answers: list[str]
    turn_program: list[str]
    executed_answers: list[float | str]
    qa_split: list[bool]


class Features(BaseModel):
    """Dataset-provided descriptive flags about a record's dialogue and table."""

    num_dialogue_turns: int
    has_type2_question: bool
    has_duplicate_columns: bool
    has_non_numeric_values: bool


class ConvFinQARecord(BaseModel):
    """One ConvFinQA record: a document, its conversation, and descriptive features."""

    id: str
    doc: Document
    dialogue: Dialogue
    features: Features
