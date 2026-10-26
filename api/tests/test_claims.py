"""Claims checked in code (plan 2b.10; TRD §7.4, PRD STORY-8; BACKLOG D6 F8): a ranking word names the group
or factor the facts rank there, and a trend word goes with a trend, change or correlation that does."""

import pytest

from sherlock.eval.grounding import card_claims
from sherlock.llm.schemas import ChipRun, LabelRun, TextRun
from sherlock.stories import narrate as nr

COLUMNS = ["pclass", "sex", "fare", "ticket", "age", "survived"]


def fact(value, fmt="text", label=""):
    return {"value": value, "formatted": str(value), "format": fmt, "label": label}


GROUPS = {"top_group": fact("female", label="sex with the highest survived"), "top_value": fact(0.727, "pct"),
          "bottom_group": fact("male", label="sex with the lowest survived"), "bottom_value": fact(0.191, "pct")}
DRIVERS = {"driver_1": fact("sex"), "driver_1_importance": fact(1.0, "num", "relative importance of sex (1 is the strongest)"),
           "driver_2": fact("pclass"), "driver_3": fact("fare")}


def runs(*parts):
    """Story runs from strings (text), ("label", ref) and ("chip", key)."""
    out = []
    for p in parts:
        if isinstance(p, str):
            out.append(TextRun(text=p))
        elif p[0] == "label":
            out.append(LabelRun(label=p[1]))
        else:
            out.append(ChipRun(chip=p[1]))
    return out


def problems(facts, *parts):
    """The claims check's findings for a story sentence, through the narrator's own rendering."""
    out, chip_facts = [], {}
    for i, run in enumerate(runs(*parts)):
        if isinstance(run, ChipRun):
            item = {"type": "chip", "id": f"c{i}", "key": run.chip, "value": facts[run.chip]["formatted"]}
            chip_facts[item["id"]] = (run.chip, facts[run.chip])
        elif isinstance(run, LabelRun):
            item = {"type": "label", "ref": run.label, "text": nr.label_text(run.label, COLUMNS)}
        else:
            item = {"type": "text", "text": run.text}
        out.append(item)
    return nr.claims(out, chip_facts, facts)


def test_a_ranking_names_the_group_the_facts_rank_there():
    assert problems(GROUPS, ("label", "value:sex:female"), " had the highest survival rate, at ", ("chip", "top_value"), ".") == (1, [])
    n, wrong = problems(GROUPS, ("label", "value:sex:male"), " had the highest survival rate.")
    assert n == 1 and "said of male" in wrong[0]
    # Two clauses, two claims, each checked against its own name.
    assert problems(GROUPS, "Survival was highest for ", ("label", "value:sex:female"), " and lowest for ",
                    ("label", "value:sex:male"), ".") == (2, [])
    assert problems(GROUPS, "Survival was highest for ", ("label", "value:sex:male"), " and lowest for ",
                    ("label", "value:sex:female"), ".")[0] == 2
    assert len(problems(GROUPS, "Survival was highest for ", ("label", "value:sex:male"), " and lowest for ",
                        ("label", "value:sex:female"), ".")[1]) == 2
    # A name chip counts as the name; a clause with no name claims nothing about a group.
    assert problems(GROUPS, ("chip", "top_group"), " had the highest rate.") == (1, [])
    assert problems(GROUPS, "The highest rate is ", ("chip", "top_value"), ".") == (0, [])


def test_a_rank_names_the_factor_of_that_rank():
    # D6 F8: "Ticket comes third" when the third factor is fare.
    n, wrong = problems(DRIVERS, ("label", "column:ticket"), " comes third.")
    assert n == 1 and "factor number 3 is fare" in wrong[0]
    assert problems(DRIVERS, ("label", "column:fare"), " comes third.") == (1, [])
    assert problems(DRIVERS, ("chip", "driver_1"), " comes first, at ", ("chip", "driver_1_importance"), ".") == (1, [])
    assert problems(DRIVERS, ("chip", "driver_1"), " matters most.") == (1, [])  # driver_1 is the top
    # Where nothing is ranked, "first" next to a value is a name ("first class"), not a rank.
    assert problems(GROUPS, "In first class, ", ("label", "value:sex:female"), " had the highest rate.") == (1, [])


def test_a_trend_word_needs_a_trend_that_goes_that_way():
    rising = {"trend": fact("rising"), "change": fact(0.2, "pct"), "peak_period": fact("2024-03")}
    flat_up = {"trend": fact("flat"), "change": fact(0.05, "pct")}
    falling = {"trend": fact("falling"), "change": fact(0.05, "pct")}
    assert problems(rising, "Revenue is rising over the months.") == (1, [])
    assert problems(flat_up, "Revenue increased from the first month to the last.") == (1, [])
    assert problems(falling, "Revenue increased over the months.")[1]  # the trend says otherwise
    assert problems({"correlation": fact(0.4, "num")}, "Fare rises with age.") == (1, [])
    # D6 F8: a bar chart of classes has no trend, so "decreases for lower classes" is a claim no fact makes.
    n, wrong = problems(GROUPS, "Survival decreases for lower classes.")
    assert n == 1 and "no trend, change or correlation" in wrong[0]


def test_the_narrator_refuses_a_claim_the_facts_dont_make():
    with pytest.raises(ValueError, match="said of male"):
        nr.to_runs(runs(("label", "value:sex:male"), " had the highest survival rate, at ", ("chip", "top_value"), "."),
                   GROUPS, COLUMNS)
    good = nr.to_runs(runs(("label", "value:sex:female"), " had the highest survival rate, at ", ("chip", "top_value"), "."),
                      GROUPS, COLUMNS)
    assert good[0]["text"] == "female"
    # The overview's merged sheet: keys carry their widget's prefix.
    merged = {f"w2.{k}": f for k, f in GROUPS.items()}
    with pytest.raises(ValueError, match="said of male"):
        nr.to_runs(runs(("label", "value:sex:male"), " had the highest survival rate."), merged, COLUMNS)


def test_the_grounding_eval_counts_claims():
    card = {"facts": GROUPS, "headline": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "label", "ref": "value:sex:female", "text": "female"}, {"type": "text", "text": " survived most often."}]}]},
        "body": {"blocks": [{"type": "paragraph", "runs": [
            {"type": "label", "ref": "value:sex:female", "text": "female"}, {"type": "text", "text": " had the lowest rate, at "},
            {"type": "chip", "id": "c2", "key": "top_value", "value": "72.7%"}, {"type": "text", "text": "."}]}]}}
    checked, wrong = card_claims(card)
    assert checked == 2 and len(wrong) == 1 and "the bottom" in wrong[0]
