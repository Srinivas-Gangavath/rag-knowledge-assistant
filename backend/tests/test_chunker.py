import pytest

from app.services.chunker import (
    Chunker,
    FixedWordWindowChunker,
    RecursiveChunker,
    create_chunker,
    normalize_chunking_strategy,
)
from app.services.pdf_parser import PageText
from tests.conftest import make_settings


def _source_words(pages: list[PageText]) -> list[str]:
    words: list[str] = []
    for page in pages:
        words.extend(page.text.split())
    return words


def _covers_all_words(pages: list[PageText], chunks) -> bool:
    remaining = list(_source_words(pages))
    for chunk in chunks:
        for word in chunk.content.split():
            if remaining and remaining[0] == word:
                remaining.pop(0)
    return not remaining


def test_short_text_creates_one_chunk():
    chunks = Chunker(chunk_size=700, chunk_overlap=100).chunk(
        [PageText(page_number=1, text="Short document text")]
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert chunks[0].content == "Short document text"


def test_long_text_creates_multiple_chunks_with_size_and_overlap():
    words = [f"word{i}" for i in range(12)]
    chunks = Chunker(chunk_size=5, chunk_overlap=2).chunk(
        [PageText(page_number=3, text=" ".join(words))]
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]
    assert chunks[0].content.split() == words[0:5]
    assert chunks[1].content.split() == words[3:8]
    assert chunks[2].content.split() == words[6:11]
    assert chunks[3].content.split() == words[9:12]
    assert all(chunk.page_number == 3 for chunk in chunks)


def test_chunker_does_not_split_words():
    chunks = Chunker(chunk_size=3, chunk_overlap=1).chunk(
        [PageText(page_number=1, text="alpha beta gamma delta")]
    )

    all_tokens = [token for chunk in chunks for token in chunk.content.split()]
    assert "alpha" in all_tokens
    assert "beta" in all_tokens
    assert all(" " not in token for token in all_tokens)
    assert all(len(token) > 1 or token.isalpha() for token in all_tokens)


def test_chunker_is_deterministic():
    pages = [PageText(page_number=1, text="one two three four five six seven")]
    chunker = Chunker(chunk_size=4, chunk_overlap=1)

    first = chunker.chunk(pages)
    second = chunker.chunk(pages)

    assert [(c.chunk_index, c.page_number, c.content) for c in first] == [
        (c.chunk_index, c.page_number, c.content) for c in second
    ]


def test_empty_input_produces_no_chunks():
    assert Chunker(chunk_size=700, chunk_overlap=100).chunk([]) == []
    assert Chunker(chunk_size=700, chunk_overlap=100).chunk(
        [PageText(page_number=1, text="   ")]
    ) == []


def test_multiple_pages_preserve_page_numbers_and_indexes():
    chunks = Chunker(chunk_size=2, chunk_overlap=0).chunk(
        [
            PageText(page_number=1, text="alpha beta gamma"),
            PageText(page_number=2, text=""),
            PageText(page_number=3, text="delta"),
        ]
    )

    assert [(c.chunk_index, c.page_number, c.content) for c in chunks] == [
        (0, 1, "alpha beta"),
        (1, 1, "gamma"),
        (2, 3, "delta"),
    ]


def test_boundary_exact_chunk_size():
    words = [f"w{i}" for i in range(5)]
    chunks = Chunker(chunk_size=5, chunk_overlap=1).chunk(
        [PageText(page_number=1, text=" ".join(words))]
    )

    assert len(chunks) == 1
    assert chunks[0].content.split() == words


def test_chunker_rejects_overlap_not_smaller_than_size():
    with pytest.raises(ValueError, match="smaller than chunk_size"):
        Chunker(chunk_size=700, chunk_overlap=700)
    with pytest.raises(ValueError, match="smaller than chunk_size"):
        Chunker(chunk_size=700, chunk_overlap=800)


def test_chunker_exposes_configured_window():
    chunker = Chunker(chunk_size=500, chunk_overlap=50)
    assert chunker.chunk_size == 500
    assert chunker.chunk_overlap == 50


def test_chunk_configuration_changes_chunk_counts():
    words = [f"word{i}" for i in range(3000)]
    pages = [PageText(page_number=1, text=" ".join(words))]
    small = Chunker(chunk_size=500, chunk_overlap=50).chunk(pages)
    medium = Chunker(chunk_size=700, chunk_overlap=100).chunk(pages)
    large = Chunker(chunk_size=1000, chunk_overlap=150).chunk(pages)

    assert len(small) > len(medium) > len(large)
    assert all(chunk.page_number == 1 for chunk in small)
    assert [chunk.chunk_index for chunk in small] == list(range(len(small)))
    assert all(chunk.content for chunk in small)


def test_default_window_progresses_without_repeating_the_same_chunk():
    words = [f"w{i}" for i in range(1500)]
    chunks = Chunker(chunk_size=700, chunk_overlap=100).chunk(
        [PageText(page_number=1, text=" ".join(words))]
    )

    assert len(chunks) == 3
    assert chunks[0].content.split() == words[0:700]
    assert chunks[1].content.split() == words[600:1300]
    assert chunks[2].content.split() == words[1200:1500]
    assert chunks[0].content != chunks[1].content
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]


def test_chunker_is_the_fixed_word_window_strategy():
    chunker = Chunker(chunk_size=700, chunk_overlap=100)
    assert isinstance(chunker, FixedWordWindowChunker)
    assert chunker.name == "fixed_word_window"


def test_factory_selects_fixed_and_recursive_strategies():
    settings = make_settings()
    fixed = create_chunker(settings, strategy="fixed_word_window")
    recursive = create_chunker(settings, strategy="recursive")

    assert isinstance(fixed, FixedWordWindowChunker)
    assert not isinstance(recursive, FixedWordWindowChunker)
    assert isinstance(recursive, RecursiveChunker)
    assert fixed.name == "fixed_word_window"
    assert recursive.name == "recursive"


def test_factory_rejects_unknown_and_semantic_strategies():
    settings = make_settings()
    with pytest.raises(ValueError, match="semantic"):
        create_chunker(settings, strategy="semantic")
    with pytest.raises(ValueError, match="Unknown|must be one of"):
        create_chunker(settings, strategy="hyde")
    with pytest.raises(ValueError, match="semantic"):
        normalize_chunking_strategy("semantic")


def test_recursive_empty_and_whitespace_pages_produce_no_chunks():
    chunker = RecursiveChunker(chunk_size=700, chunk_overlap=100)
    assert chunker.chunk([]) == []
    assert chunker.chunk([PageText(page_number=1, text="   ")]) == []


def test_recursive_short_page_is_one_chunk():
    pages = [PageText(page_number=1, text="Short document text")]
    chunks = RecursiveChunker(chunk_size=700, chunk_overlap=100).chunk(pages)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert chunks[0].content == "Short document text"


def test_recursive_page_smaller_than_target_stays_one_chunk():
    words = [f"word{i}" for i in range(20)]
    pages = [PageText(page_number=2, text=" ".join(words))]
    chunks = RecursiveChunker(chunk_size=50, chunk_overlap=5).chunk(pages)

    assert len(chunks) == 1
    assert chunks[0].content.split() == words
    assert chunks[0].page_number == 2


def test_recursive_prefers_paragraph_boundaries():
    paragraph_a = " ".join(f"alpha{i}" for i in range(4))
    paragraph_b = " ".join(f"beta{i}" for i in range(4))
    paragraph_c = " ".join(f"gamma{i}" for i in range(4))
    text = f"{paragraph_a}\n\n{paragraph_b}\n\n{paragraph_c}"
    pages = [PageText(page_number=1, text=text)]
    chunks = RecursiveChunker(chunk_size=10, chunk_overlap=2).chunk(pages)

    assert len(chunks) == 2
    assert chunks[0].content.split() == paragraph_a.split() + paragraph_b.split()
    assert paragraph_c.split()[0] in chunks[1].content.split()
    assert " ".join(paragraph_b.split()[:2]) not in " ".join(paragraph_c.split())
    assert _covers_all_words(pages, chunks)


def test_recursive_splits_oversized_paragraph_on_sentences():
    sentences = [f"Sentence number {i} is here." for i in range(6)]
    pages = [PageText(page_number=1, text=" ".join(sentences))]
    chunks = RecursiveChunker(chunk_size=12, chunk_overlap=2).chunk(pages)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert not chunk.content.startswith("number")
        assert "Sentence" in chunk.content
    assert _covers_all_words(pages, chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_recursive_oversized_sentence_uses_word_window_fallback():
    words = [f"word{i}" for i in range(12)]
    pages = [PageText(page_number=3, text=" ".join(words))]
    chunks = RecursiveChunker(chunk_size=5, chunk_overlap=2).chunk(pages)
    expected = Chunker(chunk_size=5, chunk_overlap=2).chunk(pages)

    assert [chunk.content for chunk in chunks] == [chunk.content for chunk in expected]
    assert _covers_all_words(pages, chunks)
    assert all(" " not in token for chunk in chunks for token in chunk.content.split())


def test_recursive_exact_target_size_is_one_chunk():
    words = [f"w{i}" for i in range(5)]
    pages = [PageText(page_number=1, text=" ".join(words))]
    chunks = RecursiveChunker(chunk_size=5, chunk_overlap=1).chunk(pages)

    assert len(chunks) == 1
    assert chunks[0].content.split() == words


def test_recursive_large_page_covers_every_word():
    words = [f"w{i}." if i % 8 == 7 else f"w{i}" for i in range(1500)]
    pages = [PageText(page_number=1, text=" ".join(words))]
    chunks = RecursiveChunker(chunk_size=700, chunk_overlap=100).chunk(pages)

    assert len(chunks) >= 2
    assert _covers_all_words(pages, chunks)
    assert all(chunk.content for chunk in chunks)
    contents = [chunk.content for chunk in chunks]
    assert contents[0] != contents[1]


def test_recursive_overlap_introduces_new_content_without_duplicates():
    sentences = [f"Token{i} continues here." for i in range(20)]
    pages = [PageText(page_number=1, text=" ".join(sentences))]
    chunks = RecursiveChunker(chunk_size=12, chunk_overlap=3).chunk(pages)

    assert len(chunks) >= 2
    for previous, current in zip(chunks, chunks[1:]):
        assert previous.content != current.content
        previous_words = previous.content.split()
        current_words = current.content.split()
        assert current_words != previous_words
        new_words = [word for word in current_words if word not in previous_words[-3:]]
        assert new_words
    assert _covers_all_words(pages, chunks)


def test_recursive_is_deterministic():
    pages = [
        PageText(
            page_number=1,
            text="First paragraph stays together.\n\nSecond paragraph follows after a blank line.",
        )
    ]
    chunker = RecursiveChunker(chunk_size=8, chunk_overlap=2)
    first = chunker.chunk(pages)
    second = chunker.chunk(pages)
    assert [(c.chunk_index, c.page_number, c.content) for c in first] == [
        (c.chunk_index, c.page_number, c.content) for c in second
    ]


def test_recursive_multiple_pages_preserve_indexes_and_page_numbers():
    chunks = RecursiveChunker(chunk_size=2, chunk_overlap=0).chunk(
        [
            PageText(page_number=1, text="alpha beta gamma"),
            PageText(page_number=2, text=""),
            PageText(page_number=3, text="delta"),
        ]
    )

    assert [(c.chunk_index, c.page_number, c.content) for c in chunks] == [
        (0, 1, "alpha beta"),
        (1, 1, "gamma"),
        (2, 3, "delta"),
    ]
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_recursive_rejects_invalid_window():
    with pytest.raises(ValueError, match="smaller than chunk_size"):
        RecursiveChunker(chunk_size=700, chunk_overlap=700)
