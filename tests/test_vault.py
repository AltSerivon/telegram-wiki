from telegram_wiki.vault import is_wiki_write_allowed, slugify


def test_is_wiki_write_allowed():
    assert is_wiki_write_allowed("index.md")
    assert is_wiki_write_allowed("log.md")
    assert is_wiki_write_allowed("wiki/Foo.md")
    assert not is_wiki_write_allowed("raw/x.md")
    assert not is_wiki_write_allowed("wiki/../secrets.md")


def test_slugify():
    assert slugify("Acme Corp!") == "acme-corp"
