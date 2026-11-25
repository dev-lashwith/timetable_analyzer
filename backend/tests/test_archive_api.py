import asyncio

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import app
from app.models import AcademicYear, ClassGroup, Room, Semester, TimetableCell, TimetableRecord, UploadedDocument


@pytest.fixture
def archive_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'archive-test.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.archive_api.SessionLocal", test_sessions)
    yield test_sessions
    engine.dispose()


def seed_review_timetable(session_factory):
    with session_factory() as session:
        document = UploadedDocument(filename="department.pdf", content_type="application/pdf", file_path="/tmp/department.pdf",
                                    size_bytes=42, sha256="a" * 64, status="review", page_count=1)
        year = AcademicYear(label="2025-26", normalized_label="2025-26")
        semester = Semester(label="Semester II", normalized_label="semester ii")
        group = ClassGroup(name="II Year", section="A", stream="AIML", normalized_name="ii year",
                           normalized_section="a", normalized_stream="aiml")
        room = Room(label="Lab 2", normalized_label="lab 2")
        session.add_all([document, year, semester, group, room])
        session.flush()
        timetable = TimetableRecord(document_id=document.id, source_page=1, table_index=1, table_type="timetable",
                                    status="review", academic_year_id=year.id, semester_id=semester.id,
                                    class_group_id=group.id, room_id=room.id, row_count=1, column_count=1,
                                    column_widths=[100], row_heights=[40], source_bbox={"x": 1, "y": 2, "width": 100, "height": 40},
                                    page_size={"width": 900, "height": 700}, raw_page_text="Semester II 2025-26",
                                    metadata_confidence={}, warnings=[])
        session.add(timetable)
        session.flush()
        session.add(TimetableCell(timetable_id=timetable.id, row_index=0, column_index=0, rowspan=1, colspan=1,
                                  raw_text="Monday", normalized_text="monday", x=0, y=0, width=100, height=40,
                                  source_bbox={"x": 1, "y": 2, "width": 100, "height": 40}))
        session.commit()
        return document.id, timetable.id


def test_verified_timetable_is_published_and_appears_in_dependent_filters(archive_session):
    _, timetable_id = seed_review_timetable(archive_session)
    transport = httpx.ASGITransport(app=app)

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            verified = await client.post(f"/api/timetables/{timetable_id}/verify")
            assert verified.status_code == 200
            published = await client.post(f"/api/timetables/{timetable_id}/publish")
            assert published.status_code == 200
            options = await client.get("/api/options")
            found = await client.get("/api/timetables/search?semester_id=1&class_id=1&academic_year_id=1&room_id=1")
            exported = await client.get(f"/api/documents/{verified.json()['document_id']}/json")
            return options, found, exported

    options, found, exported = asyncio.run(run())
    assert options.status_code == 200
    assert [item["label"] for item in options.json()["semesters"]] == ["Semester II"]
    assert found.status_code == 200 and found.json()[0]["id"] == timetable_id
    exported_table = exported.json()["timetables"][0]
    assert exported_table["cells"][0]["raw_text"] == "Monday"
    assert exported_table["cells"][0]["coordinates"]["source_page_bbox"]["x"] == 1
