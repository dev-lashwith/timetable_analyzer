from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .db import Base


json_type = JSON().with_variant(JSONB, "postgresql")


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_warnings: Mapped[list] = mapped_column(json_type, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class AcademicYear(Base):
    __tablename__ = "academic_years"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class Semester(Base):
    __tablename__ = "semesters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class ClassGroup(Base):
    __tablename__ = "class_groups"
    __table_args__ = (UniqueConstraint("normalized_name", "normalized_section", "normalized_stream"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    section: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    stream: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    normalized_name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_section: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_stream: Mapped[str] = mapped_column(String(80), nullable=False)


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class Faculty(Base):
    __tablename__ = "faculty"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)


class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)


class SharedCellText(Base):
    __tablename__ = "shared_cell_texts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_text: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)


class TimeSlot(Base):
    __tablename__ = "time_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_label: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    day: Mapped[str | None] = mapped_column(String(20))
    start_time: Mapped[str | None] = mapped_column(String(10))
    end_time: Mapped[str | None] = mapped_column(String(10))


class TimetableRecord(Base):
    __tablename__ = "timetables"
    __table_args__ = (UniqueConstraint("document_id", "source_page", "table_index"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("uploaded_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    source_page: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    table_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    table_type: Mapped[str] = mapped_column(String(32), nullable=False, default="timetable")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="review", index=True)
    academic_year_id: Mapped[int | None] = mapped_column(ForeignKey("academic_years.id"))
    semester_id: Mapped[int | None] = mapped_column(ForeignKey("semesters.id"))
    class_group_id: Mapped[int | None] = mapped_column(ForeignKey("class_groups.id"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_widths: Mapped[list] = mapped_column(json_type, nullable=False)
    row_heights: Mapped[list] = mapped_column(json_type, nullable=False)
    source_bbox: Mapped[dict] = mapped_column(json_type, nullable=False)
    page_size: Mapped[dict] = mapped_column(json_type, nullable=False)
    raw_page_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_confidence: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(json_type, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimetableCell(Base):
    __tablename__ = "timetable_cells"
    __table_args__ = (UniqueConstraint("timetable_id", "row_index", "column_index"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timetable_id: Mapped[str] = mapped_column(ForeignKey("timetables.id", ondelete="CASCADE"), nullable=False, index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    rowspan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    colspan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    source_bbox: Mapped[dict] = mapped_column(json_type, nullable=False)
    shared_text_id: Mapped[int | None] = mapped_column(ForeignKey("shared_cell_texts.id"))
    time_slot_id: Mapped[int | None] = mapped_column(ForeignKey("time_slots.id"))


class FacultyAllocation(Base):
    __tablename__ = "faculty_allocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timetable_id: Mapped[str] = mapped_column(ForeignKey("timetables.id", ondelete="CASCADE"), nullable=False, index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    raw_row: Mapped[list] = mapped_column(json_type, nullable=False)
