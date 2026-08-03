from ingestion.chunking.text_splitter import chunk_text


def test_chunk_text_normal_case():
    text = "one two three four five six seven eight nine ten"
    chunks = chunk_text(text, chunk_size=4, overlap=2)
    assert len(chunks) == 4
    assert chunks[0] == "one two three four"
    assert chunks[1] == "three four five six"
    assert chunks[2] == "five six seven eight"
    assert chunks[3] == "seven eight nine ten"


def test_chunk_text_empty_string():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_chunk_text_overlap_greater_than_or_equal_to_chunk_size():
    text = "word1 word2 word3 word4 word5"
    chunks_equal = chunk_text(text, chunk_size=3, overlap=3)
    assert chunks_equal == ["word1 word2 word3"]

    chunks_greater = chunk_text(text, chunk_size=3, overlap=5)
    assert chunks_greater == ["word1 word2 word3"]