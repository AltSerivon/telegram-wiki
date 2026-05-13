from telegram_wiki.db.models import Base
from telegram_wiki.db.session import get_engine


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
