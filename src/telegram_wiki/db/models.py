from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from telegram_wiki.utc import utc_now


class Base(DeclarativeBase):
    pass


class TelegramPeer(Base):
    __tablename__ = "telegram_peers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    peer_type: Mapped[str] = mapped_column(String(16), nullable=False)  # channel, chat, user
    peer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_hash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_junk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (UniqueConstraint("peer_type", "peer_id", name="uq_peer_type_id"),)

    membership: Mapped["Membership | None"] = relationship(back_populates="peer", uselist=False)


class CompanyGroup(Base):
    __tablename__ = "company_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    vault_rel_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_peer_id: Mapped[int] = mapped_column(ForeignKey("telegram_peers.id"), unique=True, nullable=False)
    company_group_id: Mapped[int] = mapped_column(ForeignKey("company_groups.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    peer: Mapped["TelegramPeer"] = relationship(back_populates="membership")
    company: Mapped["CompanyGroup"] = relationship(back_populates="memberships")


class IngestCursor(Base):
    __tablename__ = "ingest_cursors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_peer_id: Mapped[int] = mapped_column(ForeignKey("telegram_peers.id"), unique=True, nullable=False)
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    peer: Mapped["TelegramPeer"] = relationship()


class WikiProcessedFile(Base):
    __tablename__ = "wiki_processed_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_group_id: Mapped[int] = mapped_column(ForeignKey("company_groups.id"), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (UniqueConstraint("company_group_id", "rel_path", name="uq_company_rel_path"),)


class WikiRun(Base):
    __tablename__ = "wiki_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_group_id: Mapped[int] = mapped_column(ForeignKey("company_groups.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
