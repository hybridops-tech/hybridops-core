from unittest.mock import MagicMock, patch

import pytest

from ingestion.loaders.local import load_document, load_pdf, load_txt


def test_load_txt(tmp_path):
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("Hello OpenUni", encoding="utf-8")

    content = load_txt(str(txt_file))
    assert content == "Hello OpenUni"


def test_load_document_txt_and_md(tmp_path):
    txt_file = tmp_path / "doc.txt"
    txt_file.write_text("Text content", encoding="utf-8")
    assert load_document(str(txt_file)) == "Text content"

    md_file = tmp_path / "guide.md"
    md_file.write_text("Markdown content", encoding="utf-8")
    assert load_document(str(md_file)) == "Markdown content"


def test_load_pdf(tmp_path):
    pdf_file = tmp_path / "document.pdf"
    pdf_file.touch()

    mock_page1 = MagicMock()
    mock_page1.get_text.return_value = "Page 1 text"
    mock_page2 = MagicMock()
    mock_page2.get_text.return_value = "Page 2 text"

    mock_doc = [mock_page1, mock_page2]

    with patch("ingestion.loaders.local.fitz.open", return_value=mock_doc):
        text = load_pdf(str(pdf_file))
        assert "Page 1 text" in text
        assert "Page 2 text" in text

    with patch("ingestion.loaders.local.fitz.open", return_value=mock_doc):
        text_from_doc = load_document(str(pdf_file))
        assert "Page 1 text" in text_from_doc


def test_load_document_unsupported_format(tmp_path):
    unsupported_file = tmp_path / "file.docx"
    unsupported_file.touch()

    with pytest.raises(ValueError, match="Unsupported file format: .docx"):
        load_document(str(unsupported_file))