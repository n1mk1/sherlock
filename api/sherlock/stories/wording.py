"""The wording rules for model text shown to the user (TRD §7.4, §8.1; PRD STORY-3, STORY-8): no number
in words, no causal wording, no chip or label markup. The narrator checks its stories with these, and
`wording_problem` is the one check for chat text (plan 2.9). Kept apart from `narrate.py` so the chat
agent can import it without the narrator's imports."""

import re

from sherlock.llm.text import has_digits

# D9: "how class influences ticket price" got past the first list in the cached sample's stories.
CAUSAL = re.compile(r"\b(cause[sd]?|causing|because|leads? to|led to|results? in|resulted in|drives?|driven by|due to"
                    r"|influenc(?:e[sd]?|ing)|affect(?:s|ed|ing)?|impact(?:s|ed|ing)?)\b", re.I)
# An HTML entity ("&frac34;") is markup too: the notebook's Markdown renders it as a number.
MARKUP = re.compile(r"[{}\[\]]|\bchip\b|\b(column|value):|&#?\w+;", re.I)
# Numbers spelled out are still numbers the model wrote ("six", "twice"): they must be chips too.
NUMBER_WORDS = re.compile(r"\b(zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
                          r"|(?:thir|four|fif|six|seven|eigh|nine)teen|(?:twen|thir|for|fif|six|seven|eigh|nine)ty"
                          r"|hundreds?|thousands?|millions?|billions?|trillions?|dozens?|twice|thrice|tripled?|doubled?"
                          r"|quadrupled?|quintupled?|halved|half|halves|(?:two|three|four|five|ten|hundred|thousand)fold"
                          r"|one (?:in|out of)|an? (?:third|quarter|fifth|tenth) of)\b", re.I)
# So are Roman numerals ("XLV passengers"): upper case, two letters or more.
ROMAN = re.compile(r"\b(?=[MDCLXVI]{2,}\b)M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\b")
TITLE_CHARS = 80  # the builder's limit for a widget title (TRD §7.3)


def number_in_words(text: str) -> str | None:
    """The first number the text spells out, if any."""
    m = NUMBER_WORDS.search(text) or ROMAN.search(text)
    return m.group(0) if m else None


def wording_problem(text: str) -> str | None:
    """Why model text shown to the user breaks the wording rules, or None: a number in words, causal
    wording, or chip or label markup. Chat applies it to compose prose, `closest`, the router's
    clarification options, `reading` and widget titles (plan 2.9)."""
    if number_in_words(text):
        return f"a number in words ({number_in_words(text)!r}); use a chip for a number"
    if CAUSAL.search(text):
        return f"causal wording ({CAUSAL.search(text).group(0)!r}); describe an association instead"
    if MARKUP.search(text):
        return f"chip or label markup ({MARKUP.search(text).group(0)!r}) in the text"
    return None


def title_problem(title: str) -> str | None:
    """The builder's title check (TRD §7.3) plus the wording check: a widget title the model wrote is
    kept only when it has words, no digits, at most 80 characters and no wording problem."""
    if not title.strip():
        return "the title is empty"
    if has_digits(title):
        return "the title has digits"
    if len(title) > TITLE_CHARS:
        return f"the title is longer than {TITLE_CHARS} characters"
    return wording_problem(title)
