from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class BookContentBase(BaseModel):
    content_type: str = Field(..., pattern='^(markdown|html)$')
    content: str
    chapter_index: Optional[int] = None
    chapter_title: Optional[str] = None


class BookContentCreate(BookContentBase):
    book_id: UUID


class BookContentUpdate(BookContentBase):
    pass


class BookContentInDB(BookContentBase):
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BookBase(BaseModel):
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[HttpUrl] = None
    original_filename: str
    file_size: int
    page_count: Optional[int] = None


class BookCreate(BookBase):
    user_id: UUID
    storage_path: str


class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[HttpUrl] = None
    last_read_page: Optional[int] = None
    processing_status: Optional[str] = Field(None, pattern='^(pending|processing|completed|failed)$')


class BookInDB(BookBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    last_read_at: Optional[datetime] = None
    last_read_page: int = 1
    processing_status: str
    storage_path: str
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class BookWithContents(BookInDB):
    contents: List[BookContentInDB]


class BookProcessResponse(BaseModel):
    task_id: str
    book_id: UUID
    status: str = Field(..., pattern='^(pending|processing|completed|failed)$')
    message: str