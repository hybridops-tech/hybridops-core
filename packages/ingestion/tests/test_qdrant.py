from unittest.mock import MagicMock, patch

from ingestion.vector_store.qdrant import QdrantStore


def test_qdrant_store_creates_collection_if_not_exists():
    mock_client = MagicMock()
    mock_client.get_collections.return_value = MagicMock(collections=[])

    with patch("ingestion.vector_store.qdrant.QdrantClient", return_value=mock_client):
        store = QdrantStore(
            url="http://localhost:6333", collection_name="test_col", vector_size=768
        )

    assert store.collection_name == "test_col"
    mock_client.create_collection.assert_called_once()
    _, kwargs = mock_client.create_collection.call_args
    assert kwargs["collection_name"] == "test_col"
    assert kwargs["vectors_config"].size == 768


def test_qdrant_store_skips_creation_if_collection_exists():
    mock_client = MagicMock()
    existing_col = MagicMock()
    existing_col.name = "test_col"
    mock_client.get_collections.return_value = MagicMock(collections=[existing_col])

    with patch("ingestion.vector_store.qdrant.QdrantClient", return_value=mock_client):
        QdrantStore(url="http://localhost:6333", collection_name="test_col")

    mock_client.create_collection.assert_not_called()


def test_delete_university_data():
    mock_client = MagicMock()
    mock_client.get_collections.return_value = MagicMock(collections=[])

    with patch("ingestion.vector_store.qdrant.QdrantClient", return_value=mock_client):
        store = QdrantStore(collection_name="test_col")
        store.delete_university_data("demo")

    mock_client.delete.assert_called_once()
    _, kwargs = mock_client.delete.call_args
    assert kwargs["collection_name"] == "test_col"


def test_upsert_points_valid():
    mock_client = MagicMock()
    mock_client.get_collections.return_value = MagicMock(collections=[])

    vectors = [[0.1, 0.2], [0.3, 0.4]]
    payloads = [{"text": "a"}, {"text": "b"}]

    with patch("ingestion.vector_store.qdrant.QdrantClient", return_value=mock_client):
        store = QdrantStore(collection_name="test_col")
        store.upsert_points(vectors, payloads)

    mock_client.upsert.assert_called_once()
    _, kwargs = mock_client.upsert.call_args
    assert kwargs["collection_name"] == "test_col"
    assert len(kwargs["points"]) == 2


def test_upsert_points_guards_against_empty_or_mismatched():
    mock_client = MagicMock()
    mock_client.get_collections.return_value = MagicMock(collections=[])

    with patch("ingestion.vector_store.qdrant.QdrantClient", return_value=mock_client):
        store = QdrantStore(collection_name="test_col")
        store.upsert_points([], [])
        store.upsert_points([[0.1]], [{"text": "a"}, {"text": "b"}])

    mock_client.upsert.assert_not_called()