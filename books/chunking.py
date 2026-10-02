"""
E5-token-aware splitting for generic digital-text PDFs (Stage 1).

This module does NOT create embeddings. It only uses the tokenizer from
intfloat/multilingual-e5-large so chunks will fit the model later.

Two counts are tracked:

- content_token_count: tokens of the chunk text alone (no prefix, no specials).
  Used as the splitter TARGET (~400–450 tokens, ~40–50 overlap).

- e5_input_token_count: tokens of ``"passage: " + chunk`` WITH special tokens.
  This is the AUTHORITATIVE size vs E5's 512-token input limit.

The Gita experiment used word-based packing and later found 221/1443 chunks
would be truncated (max ~866 tokens). Stage 1 must never emit such a chunk.
"""

from __future__ import annotations

from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

E5_MODEL_NAME = "intfloat/multilingual-e5-large"
E5_MAX_INPUT_TOKENS = 512
PASSAGE_PREFIX = "passage: "

# Conservative TARGET for the splitter's length_function (content tokens).
# The hard gate is e5_input_token_count <= 512, measured separately.
DEFAULT_CONTENT_CHUNK_SIZE = 450
DEFAULT_CONTENT_CHUNK_OVERLAP = 50
MIN_CONTENT_CHUNK_SIZE = 32

# Paragraph → line → sentence-ish → word → character.
# The empty separator lets us split a pathological run that still exceeds 512.
SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def load_e5_tokenizer(model_name: str = E5_MODEL_NAME):
    """Load the E5 tokenizer only. Does not load embedding weights."""
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_name)


def content_token_count(tokenizer, text: str) -> int:
    """Chunk-body tokens. Used as the splitter target, not the E5 hard limit."""
    if not text:
        return 0
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])


def e5_input_token_count(tokenizer, text: str) -> int:
    """Authoritative E5 input size: prefix + chunk + special tokens."""
    return len(
        tokenizer(PASSAGE_PREFIX + (text or ""), add_special_tokens=True)["input_ids"]
    )


def measure_prefix_overhead(tokenizer) -> dict[str, int]:
    """
    Measure prefix/special-token overhead with the real tokenizer.

    Do not assume a large budget (e.g. 60–110 tokens). Count it.
    """
    specials_only = len(tokenizer("", add_special_tokens=True)["input_ids"])
    prefix_no_specials = len(
        tokenizer(PASSAGE_PREFIX, add_special_tokens=False)["input_ids"]
    )
    prefix_with_specials = len(
        tokenizer(PASSAGE_PREFIX, add_special_tokens=True)["input_ids"]
    )
    return {
        "n_special_tokens_on_empty_string": specials_only,
        "n_tokens_passage_prefix_without_specials": prefix_no_specials,
        "n_tokens_passage_prefix_with_specials": prefix_with_specials,
        "implied_overhead_on_empty_chunk": prefix_with_specials,
        "e5_max_input_tokens": E5_MAX_INPUT_TOKENS,
    }


def make_content_splitter(
    tokenizer,
    chunk_size: int = DEFAULT_CONTENT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CONTENT_CHUNK_OVERLAP,
) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=lambda t: content_token_count(tokenizer, t),
        separators=SEPARATORS,
        is_separator_regex=False,
    )


def _resplit_until_safe(
    text: str,
    tokenizer,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Split one over-limit piece further. Never truncate. Never drop text."""
    if e5_input_token_count(tokenizer, text) <= E5_MAX_INPUT_TOKENS:
        return [text] if text.strip() else []

    next_size = max(MIN_CONTENT_CHUNK_SIZE, chunk_size // 2)
    next_overlap = min(chunk_overlap, max(0, next_size // 8))
    splitter = make_content_splitter(tokenizer, next_size, next_overlap)
    parts = [p for p in splitter.split_text(text) if p.strip()]

    # If the splitter could not break the string, force character-level split.
    if len(parts) <= 1 and e5_input_token_count(tokenizer, text) > E5_MAX_INPUT_TOKENS:
        char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=max(MIN_CONTENT_CHUNK_SIZE, next_size),
            chunk_overlap=0,
            length_function=lambda t: content_token_count(tokenizer, t),
            separators=[""],
            is_separator_regex=False,
        )
        parts = [p for p in char_splitter.split_text(text) if p.strip()]

    if len(parts) <= 1:
        raise ValueError(
            "Could not split a chunk to fit E5's 512-token input limit "
            "without truncating. This should be extremely rare."
        )

    out: list[str] = []
    for part in parts:
        out.extend(_resplit_until_safe(part, tokenizer, next_size, next_overlap))
    return out


def split_documents_e5_safe(
    documents: list[Document],
    tokenizer,
    chunk_size: int = DEFAULT_CONTENT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CONTENT_CHUNK_OVERLAP,
) -> tuple[list[Document], dict[str, Any]]:
    """
    Split page Documents into E5-safe chunk Documents.

    First pass uses the content-token TARGET. Any first-pass chunk whose
    e5_input_token_count exceeds 512 is split further (not truncated).
    """
    splitter = make_content_splitter(tokenizer, chunk_size, chunk_overlap)
    first_pass = splitter.split_documents(documents)

    n_first_pass = len(first_pass)
    n_initially_over = 0
    warnings: list[str] = []
    final_docs: list[Document] = []

    for i, doc in enumerate(first_pass):
        text = doc.page_content or ""
        e5_n = e5_input_token_count(tokenizer, text)
        if e5_n <= E5_MAX_INPUT_TOKENS:
            final_docs.append(doc)
            continue

        n_initially_over += 1
        page = doc.metadata.get("page")
        warnings.append(
            f"First-pass chunk {i} (page={page}) had e5_input_token_count={e5_n} > "
            f"{E5_MAX_INPUT_TOKENS}; splitting further without truncation."
        )
        pieces = _resplit_until_safe(text, tokenizer, chunk_size, chunk_overlap)
        for piece in pieces:
            final_docs.append(
                Document(page_content=piece, metadata=dict(doc.metadata))
            )

    # Assign sequential chunk_index and token stats on the FINAL list.
    for idx, doc in enumerate(final_docs):
        text = doc.page_content
        content_n = content_token_count(tokenizer, text)
        e5_n = e5_input_token_count(tokenizer, text)
        doc.metadata["chunk_index"] = idx
        doc.metadata["content_token_count"] = content_n
        doc.metadata["e5_input_token_count"] = e5_n
        if e5_n > E5_MAX_INPUT_TOKENS:
            raise RuntimeError(
                f"Final chunk {idx} still exceeds E5 limit: {e5_n} tokens."
            )

    stats = {
        "n_first_pass_chunks": n_first_pass,
        "n_chunks_initially_exceeding_512": n_initially_over,
        "n_final_chunks": len(final_docs),
        "n_final_chunks_exceeding_512": 0,
        "target_content_chunk_size": chunk_size,
        "target_content_chunk_overlap": chunk_overlap,
        "warnings": warnings,
    }
    return final_docs, stats
