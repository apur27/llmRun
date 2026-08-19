"""Cross-turn conversation state for one ConvFinQA conversation.

Holds the ordered list of (question, model-predicted-answer) pairs for turns already answered
earlier in the same conversation, so a client answering a later turn can see what the model
itself said before -- never gold. Slice 12's real-data probe (`notes/risky-unknown.md`) showed
the model reliably reuses a recorded prior-turn answer, including a derived (non-literal) one,
over re-deriving it, once this history is present -- this type is what makes that history
explicit and testable rather than implicit in whatever an adapter happens to send.

Provider-agnostic on purpose: holds only plain `Turn` values, never a message-dict or other
SDK-shaped type. Turning prior turns into a specific provider's request shape (e.g. alternating
`user`/`assistant` messages) is each adapter's own job -- see `AnthropicClient`. Lives in
`src/services` per the module map: this is deployment/session state for the conversation loop,
not a pure domain concept (`src/domain`) and not provider-specific (`src/adapters`).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Turn:
    """One already-answered turn: the question asked and the model's own predicted answer."""

    question: str
    answer: float | str


@dataclass
class TurnState:
    """Accumulates prior turns for one conversation, in order.

    Not frozen: `add` appends in place as the eval loop scores each turn of one conversation in
    sequence. Build exactly one instance per conversation (`ConvFinQARecord`) -- never share or
    reuse one across records, since a prior turn from a different conversation is never
    something a later turn's client should see.
    """

    turns: list[Turn] = field(default_factory=list)

    def add(self, question: str, answer: float | str) -> None:
        """Append one more resolved turn: the question and the model's own predicted answer."""
        self.turns.append(Turn(question=question, answer=answer))
