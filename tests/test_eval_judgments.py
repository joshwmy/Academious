"""The judgment file: round-tripping, and never losing a human label."""

from __future__ import annotations

import uuid

import pytest

from academious.eval import judgments as judgments_module
from academious.eval.judgments import Judgment

PAPER_A = str(uuid.UUID(int=1))
PAPER_B = str(uuid.UUID(int=2))

NEWLINE = chr(10)


def test_reading_a_missing_file_returns_nothing_rather_than_failing(tmp_path):
    assert judgments_module.read(tmp_path / "absent.jsonl") == []


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / "judgments.jsonl"
    original = [
        Judgment("bio-01", PAPER_A, grade=3, title="Zebra", retrieved_by=["lexical"]),
        Judgment("bio-01", PAPER_B, grade=None, title="Apple"),
    ]
    assert judgments_module.write(path, original) == 2
    restored = judgments_module.read(path)
    assert {j.paper_id: j.grade for j in restored} == {PAPER_A: 3, PAPER_B: None}


def test_rows_are_written_in_a_stable_order(tmp_path):
    """A regenerated pool must produce a reviewable diff, not a reshuffle."""
    path = tmp_path / "judgments.jsonl"
    judgments_module.write(
        path,
        [Judgment("q", PAPER_A, title="Zebra"), Judgment("q", PAPER_B, title="Apple")],
    )
    titles = [j.title for j in judgments_module.read(path)]
    assert titles == ["Apple", "Zebra"]


def test_merge_preserves_an_existing_grade():
    existing = [Judgment("q", PAPER_A, grade=2, judge="joshua", retrieved_by=["lexical"])]
    incoming = [Judgment("q", PAPER_A, grade=None, retrieved_by=["semantic"])]
    merged = judgments_module.merge(existing, incoming)
    assert len(merged) == 1
    assert merged[0].grade == 2
    assert merged[0].judge == "joshua"
    assert merged[0].retrieved_by == ["lexical", "semantic"]


def test_merge_keeps_a_judgment_whose_paper_left_the_pool():
    existing = [Judgment("q", PAPER_A, grade=1)]
    merged = judgments_module.merge(existing, [Judgment("q", PAPER_B, grade=None)])
    assert {j.paper_id for j in merged} == {PAPER_A, PAPER_B}


def test_merge_adds_newly_pooled_papers():
    merged = judgments_module.merge([], [Judgment("q", PAPER_A), Judgment("q", PAPER_B)])
    assert len(merged) == 2


def test_grade_map_excludes_unjudged_rows():
    grades = judgments_module.grade_map(
        [Judgment("q", PAPER_A, grade=0), Judgment("q", PAPER_B, grade=None)]
    )
    assert grades == {"q": {uuid.UUID(PAPER_A): 0}}


def test_grade_zero_is_a_judgment_and_none_is_not():
    judged, total = judgments_module.coverage(
        [Judgment("q", PAPER_A, grade=0), Judgment("q", PAPER_B, grade=None)]
    )
    assert (judged, total) == (1, 2)


def test_stamp_rejects_a_grade_outside_the_scale():
    with pytest.raises(ValueError, match="grade must be one of"):
        judgments_module.stamp(Judgment("q", PAPER_A), 7, "joshua")


def test_a_malformed_line_names_the_file_and_line_number(tmp_path):
    path = tmp_path / "broken.jsonl"
    good = Judgment("q", PAPER_A).to_json()
    path.write_text(good + NEWLINE + "not json at all" + NEWLINE, encoding="utf-8")
    with pytest.raises(ValueError, match="broken.jsonl:2"):
        judgments_module.read(path)


def test_a_line_missing_a_required_field_names_the_line_too(tmp_path):
    path = tmp_path / "wrong-shape.jsonl"
    path.write_text('{"query_id": "q"}' + NEWLINE, encoding="utf-8")
    with pytest.raises(ValueError, match="wrong-shape.jsonl:1: not a judgment"):
        judgments_module.read(path)


# ------------------------------------------------- the interactive labeller


def _pool(tmp_path):
    from academious.eval.judgments import Judgment

    path = tmp_path / "judgments.jsonl"
    judgments_module.write(
        path,
        [
            Judgment("bio-01", PAPER_A, title="Apple", retrieved_by=["lexical"]),
            Judgment("bio-01", PAPER_B, title="Zebra", retrieved_by=["semantic"]),
        ],
    )
    return path


def test_labelling_writes_after_every_answer(tmp_path, monkeypatch):
    """A closed terminal must not cost an hour of judging."""
    from academious.workers import label

    path = _pool(tmp_path)
    seen = []

    def fake_input(prompt):
        # Read the file back mid-session: the first grade must already be there.
        seen.append([j.grade for j in judgments_module.read(path)])
        return "3"

    monkeypatch.setattr("builtins.input", fake_input)
    graded = label.run(path, judge="tester")

    assert graded == 2
    assert seen[1] == [3, None]
    assert [j.grade for j in judgments_module.read(path)] == [3, 3]


def test_quitting_keeps_what_was_already_graded(tmp_path, monkeypatch):
    from academious.workers import label

    path = _pool(tmp_path)
    answers = iter(["2", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    graded = label.run(path, judge="tester")

    assert graded == 1
    assert [j.grade for j in judgments_module.read(path)] == [2, None]


def test_ctrl_c_is_treated_as_quit_not_as_a_crash(tmp_path, monkeypatch):
    from academious.workers import label

    path = _pool(tmp_path)

    def interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert label.run(path, judge="tester") == 0
    assert [j.grade for j in judgments_module.read(path)] == [None, None]


def test_an_invalid_answer_re_prompts_rather_than_recording_anything(tmp_path, monkeypatch):
    from academious.workers import label

    path = _pool(tmp_path)
    answers = iter(["7", "banana", "1", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert label.run(path, judge="tester") == 1
    assert [j.grade for j in judgments_module.read(path)] == [1, None]


def test_skip_leaves_a_paper_unjudged(tmp_path, monkeypatch):
    from academious.workers import label

    path = _pool(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "s")

    assert label.run(path, judge="tester") == 0
    assert all(j.grade is None for j in judgments_module.read(path))


def test_labelling_can_be_restricted_to_one_query(tmp_path, monkeypatch):
    from academious.eval.judgments import Judgment
    from academious.workers import label

    path = tmp_path / "judgments.jsonl"
    judgments_module.write(
        path,
        [
            Judgment("bio-01", PAPER_A, title="Apple"),
            Judgment("cs-01", PAPER_B, title="Zebra"),
        ],
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "2")

    assert label.run(path, judge="tester", query_id="cs-01") == 1
    grades = {j.query_id: j.grade for j in judgments_module.read(path)}
    assert grades == {"bio-01": None, "cs-01": 2}


def test_labelling_a_missing_pool_says_so_rather_than_failing(tmp_path):
    from academious.workers import label

    assert label.run(tmp_path / "nothing.jsonl", judge="tester") == 0
