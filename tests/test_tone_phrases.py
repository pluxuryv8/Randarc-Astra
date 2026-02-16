from __future__ import annotations

from core import assistant_phrases as phrases


def test_phrases_do_not_contain_rudeness():
    texts = [
        phrases.ASK_CLARIFY_MEMORY,
        phrases.ASK_CLARIFY_REMINDER_TIME,
        phrases.ASK_CLARIFY_WEB,
        phrases.CONFIRM_DANGER,
        phrases.DONE,
        phrases.ERROR,
    ]
    for text in texts:
        assert text
        assert not phrases.contains_rude_words(text)
