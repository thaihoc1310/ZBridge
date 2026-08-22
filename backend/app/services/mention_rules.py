import re
import unicodedata
from collections.abc import Iterable, Sequence

from app.schemas.api import IncomingGroupMessage

DEFAULT_MENTION_SKIP_PHRASES = [
    "ok",
    "oke",
    "okay",
    "cảm ơn",
    "cảm ơn nhé",
    "thanks",
    "thank you",
    "rõ rồi",
    "đã rõ",
    "nhận được",
    "nhận được rồi",
]


def normalize_phrase(value: str) -> str:
    """Normalize exact-match rules without discarding Vietnamese accents."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(
        character if unicodedata.category(character)[0] in {"L", "N"} else " "
        for character in value
    )
    return re.sub(r"\s+", " ", value).strip()


def normalize_skip_phrases(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        phrase = normalize_phrase(value)
        if not phrase or phrase in seen:
            continue
        normalized.append(value.strip())
        seen.add(phrase)
    return normalized


def content_without_mentions(
    event: IncomingGroupMessage,
    *,
    target_display_names: Sequence[str] = (),
) -> str:
    """Remove mention labels while remaining compatible with older gateways."""
    content = event.content
    mention_texts = [mention.text for mention in event.mentions if mention.text]
    if mention_texts:
        for mention_text in sorted(mention_texts, key=len, reverse=True):
            content = content.replace(mention_text, "", 1)
    else:
        # During rolling deploys the old gateway does not yet send mention text.
        for display_name in sorted(target_display_names, key=len, reverse=True):
            content = re.sub(
                rf"@{re.escape(display_name)}",
                "",
                content,
                count=1,
                flags=re.IGNORECASE,
            )
    return content


#: A bare "giá" is deliberately loose — it also catches "đánh giá", "giá trị",
#: "giá đỗ" — because the classifier is what separates a real quote request from
#: an incidental word. Tone marks survive normalisation, so "già" and "giả" do
#: not match.
PRICE_KEYWORD_TOKENS = ("giá",)
PRICE_KEYWORD_PHRASES = ("bao nhiêu tiền", "bnh tiền")


def text_mentions_price(content: str, mention_texts: Iterable[str] = ()) -> bool:
    """Cheap gate in front of the classifier, not a decision on its own.

    Reads what the sender typed, with the mention labels taken out: a member
    whose display name happens to contain "giá" should not send every message
    that tags them to the model. Takes raw text so it also works on the stored
    context rows, not just a live event.
    """
    for mention_text in sorted((t for t in mention_texts if t), key=len, reverse=True):
        content = content.replace(mention_text, "", 1)
    normalized = normalize_phrase(content)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in PRICE_KEYWORD_PHRASES):
        return True
    return bool(set(normalized.split()) & set(PRICE_KEYWORD_TOKENS))


def mentions_price(event: IncomingGroupMessage) -> bool:
    return text_mentions_price(
        event.content, [mention.text for mention in event.mentions]
    )


def is_bare_mention(
    event: IncomingGroupMessage,
    *,
    target_display_names: Sequence[str] = (),
) -> bool:
    return not normalize_phrase(
        content_without_mentions(event, target_display_names=target_display_names)
    )


def matches_skip_phrase(
    event: IncomingGroupMessage,
    skip_phrases: Iterable[str],
    *,
    target_display_names: Sequence[str] = (),
) -> bool:
    residual = normalize_phrase(
        content_without_mentions(event, target_display_names=target_display_names)
    )
    return bool(residual) and residual in {
        normalize_phrase(phrase) for phrase in skip_phrases if normalize_phrase(phrase)
    }
