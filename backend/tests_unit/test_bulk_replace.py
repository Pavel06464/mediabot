"""Юнит-тесты массовой замены в описаниях. Telegram и Mongo не нужны."""
import bulk_replace as br

FIND_TYPO = "https://t.me/t.me/PoDomam18_bot?start=channel_3b69266a"
FIND_OK = "https://t.me/PoDomam18_bot?start=channel_3b69266a"
TEXT = "Больше с ней в 👉 [Сливы приваток](https://t.me/PoDomam18_bot?start=channel_3b69266a)\n[По домам 18+](https://t.me/PoDomam18tg)"
OTHER = "Больше с ней в 👉 [Частные сливы](https://t.me/PoDomam18_bot?start=channel_666de39e)\n[По домам 18+](https://t.me/PoDomam18tg)"


def test_normalize_double_tme():
    assert br.normalize_tme_url(FIND_TYPO) == FIND_OK
    assert br.normalize_tme_url(FIND_OK) == FIND_OK
    assert br.normalize_tme_url("t.me/t.me/PoDomam18_bot?start=channel_3b69266a") == FIND_OK
    assert br.normalize_tme_url("  " + FIND_TYPO + "  ") == FIND_OK


def test_typo_finds_hidden_markdown_url():
    assert br.contains_find(TEXT, FIND_TYPO)
    assert br.contains_find(TEXT, FIND_OK)
    assert br.contains_find(TEXT, "t.me/PoDomam18_bot?start=channel_3b69266a")
    assert not br.contains_find(OTHER, FIND_TYPO)  # другой start=


def test_whitespace_stripped_on_find():
    assert br.contains_find(TEXT, FIND_TYPO + "  ")
    assert br.contains_find(TEXT, "  " + FIND_OK)


def test_replace_typo_is_noop_when_already_correct():
    assert br.apply_replace(TEXT, FIND_TYPO, FIND_OK) == TEXT
    assert not br.would_change(TEXT, FIND_TYPO, FIND_OK)


def test_replace_changes_start_param():
    new = "https://t.me/PoDomam18_bot?start=channel_NEW"
    out = br.apply_replace(TEXT, FIND_TYPO, new)
    assert new in out and FIND_OK not in out
    assert "[Сливы приваток]" in out


def test_plain_text_still_exact():
    t = "hello world hello"
    assert br.contains_find(t, "hello")
    assert br.apply_replace(t, "hello", "hi") == "hi world hi"
    assert not br.contains_find(t, "https://t.me/nope")


def test_caption_and_text_fields():
    post = {
        "id": "1",
        "title": "Mollyella",
        "blocks": [
            {"type": "text", "value": TEXT},
            {"type": "video", "caption": "см. " + FIND_OK, "is_cover": False},
        ],
    }
    assert br.post_matches(post, FIND_TYPO)
    assert not br.post_would_change(post, FIND_TYPO, FIND_OK)
    changed = br.apply_to_post_blocks(post["blocks"], FIND_OK, "https://t.me/x")
    assert "https://t.me/x" in changed[0]["value"]
    assert FIND_OK not in changed[0]["value"]
    assert changed[1]["caption"] == "см. https://t.me/x"


def test_summarize_explains_noop_and_labels():
    posts = [
        {"id": "a", "title": "Mollyella", "blocks": [{"type": "text", "value": TEXT}]},
        {"id": "b", "title": "Anya", "blocks": [{"type": "text", "value": OTHER}]},
    ]
    sigs = [{"id": "s1", "name": "Сливы приваток", "content": TEXT}]
    s = br.summarize_scan(posts, FIND_TYPO, FIND_OK, sigs)
    assert s["matched"] == 1 and s["matched_exact"] == 0
    assert s["would_change"] == 0 and s["noop"] == 1
    assert s["signatures_matched"] == 1 and s["signatures_would_change"] == 0
    assert "Сливы приваток" in s["markdown_labels"]
    assert "Точного текста нет" in s["message"]
    assert "ничего не изменит" in s["message"]
    assert s["find_normalized"] == FIND_OK


def test_html_href_also_matches():
    html = 'Смотрите <a href="https://t.me/PoDomam18_bot?start=channel_3b69266a">тут</a>'
    assert br.contains_find(html, FIND_TYPO)
    assert br.apply_replace(html, FIND_TYPO, FIND_OK) == html
