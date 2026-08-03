from unittest.mock import MagicMock, patch

import httpx
import pytest

from ingestion.embeddings.ollama import OllamaEmbedder


def test_ensure_model_pulled_model_already_available():
    mock_get_resp = MagicMock()
    mock_get_resp.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}

    with (
        patch("httpx.get", return_value=mock_get_resp) as mock_get,
        patch("httpx.post") as mock_post,
    ):
        embedder = OllamaEmbedder(base_url="http://localhost:11434", model="nomic-embed-text")
        embedder.ensure_model_pulled()

    mock_get.assert_called_once_with("http://localhost:11434/api/tags")
    mock_post.assert_not_called()


def test_ensure_model_pulled_pulls_missing_model():
    mock_get_resp = MagicMock()
    mock_get_resp.json.return_value = {"models": []}

    mock_post_resp = MagicMock()

    with (
        patch("httpx.get", return_value=mock_get_resp),
        patch("httpx.post", return_value=mock_post_resp) as mock_post,
    ):
        embedder = OllamaEmbedder(base_url="http://localhost:11434", model="nomic-embed-text")
        embedder.ensure_model_pulled()

    mock_post.assert_called_once_with(
        "http://localhost:11434/api/pull",
        json={"name": "nomic-embed-text", "stream": False},
        timeout=300.0,
    )


def test_ensure_model_pulled_connection_error_raises():
    with patch("httpx.get", side_effect=httpx.RequestError("Connection refused")):
        embedder = OllamaEmbedder()
        with pytest.raises(httpx.RequestError):
            embedder.ensure_model_pulled()


def test_embed_documents():
    mock_post_resp = MagicMock()
    mock_post_resp.json.side_effect = [
        {"embedding": [0.1, 0.2]},
        {"embedding": [0.3, 0.4]},
    ]

    mock_client = MagicMock()
    mock_client.post.return_value = mock_post_resp
    mock_client_context = MagicMock()
    mock_client_context.__enter__.return_value = mock_client

    with patch("httpx.Client", return_value=mock_client_context):
        embedder = OllamaEmbedder(model="nomic-embed-text")
        embeddings = embedder.embed_documents(["first text", "second text"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert mock_client.post.call_count == 2