import asyncio
from unittest.mock import AsyncMock, patch

import pymupdf
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Room, TimetableCell, TimetableRecord, UploadedDocument
from app.processing import process_document


@pytest.fixture
def processing_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'processing-test.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.processing.SessionLocal", test_sessions)
    yield test_sessions
    engine.dispose()


def make_pdf(path):
    document = pymupdf.open()
    document.new_page(width=612, height=792)
    document.save(path)
    document.close()


def test_process_document_stores_sarvam_json_as_a_reviewable_timetable(
    processing_session, tmp_path, completed_extraction
):
    pdf_path = tmp_path / "department.pdf"
    make_pdf(pdf_path)
    with processing_session() as session:
        document = UploadedDocument(
            filename="department.pdf", content_type="application/pdf", file_path=str(pdf_path),
            size_bytes=pdf_path.stat().st_size, sha256="a" * 64, status="queued",
        )
        session.add(document)
        session.commit()
        document_id = document.id

    with patch("app.processing.extract_documents_async", new_callable=AsyncMock) as mocked_extract:
        mocked_extract.return_value = completed_extraction
        asyncio.run(process_document(document_id))

    assert mocked_extract.await_count == 1
    with processing_session() as session:
        document = session.get(UploadedDocument, document_id)
        records = session.scalars(select(TimetableRecord)).all()
        assert document.status == "review"
        assert len(records) == 1
        record = records[0]
        assert record.metadata_confidence["room"] == "sarvam"
        assert session.get(Room, record.room_id).label == "CV 301"
        assert record.row_count == 3
        assert record.column_count == 3
        cells = session.scalars(select(TimetableCell).where(
            TimetableCell.timetable_id == record.id
        ).order_by(TimetableCell.row_index, TimetableCell.column_index)).all()
        assert [cell.raw_text for cell in cells] == [
            "Day", "08:00-09:00", "09:00-10:00",
            "Monday", "DSA", "OS",
            "Tuesday", "SHORT BREAK", "",
        ]
