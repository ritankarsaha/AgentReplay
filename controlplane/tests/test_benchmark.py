from __future__ import annotations

from types import SimpleNamespace

from controlplane.learn import benchmark as bm


def summarize(run, spans):
    return run.id


def label_of(summary):
    return next(c.label for c in bm.classifier_cases() if f"bench-{c.id}" == summary)


def perfect_classifier(summary):
    return SimpleNamespace(failure_class=label_of(summary), usage={"cost_usd": 0.01})


def wrong_classifier(summary):
    return SimpleNamespace(failure_class="other", usage=None)


def test_cases_cover_distinct_labels_and_are_well_formed():
    cases = bm.classifier_cases()
    assert len(cases) == 8 and len({c.label for c in cases}) == 8
    assert all(c.spans and all(s.id and s.type for s in c.spans) for c in cases)
    judges = bm.judge_cases()
    assert {j.passes for j in judges} == {True, False}


def test_perfect_backend_scores_100_and_is_consistent():
    judge = lambda out, rubric: SimpleNamespace(passes=next(j.passes for j in bm.judge_cases() if j.output == out))
    result = bm.run_benchmark(["meta"], trials=3, classifier_fns={"meta": perfect_classifier}, judge_fns={"meta": judge}, summarize=summarize)[0]
    assert (result.classifier_accuracy, result.classifier_consistency) == (1.0, 1.0)
    assert (result.judge_accuracy, result.judge_consistency) == (1.0, 1.0)
    assert result.calls == 3 * (8 + 6) and result.classifier_confusions == []
    assert abs(result.classifier_cost_usd - 0.24) < 1e-9


def test_wrong_and_flaky_backends_are_measured_not_hidden():
    flip = {"n": 0}

    def flaky_judge(out, rubric):
        flip["n"] += 1
        if flip["n"] % 5 == 0:
            raise RuntimeError("rate limited")
        return SimpleNamespace(passes=flip["n"] % 2 == 0)

    result = bm.run_benchmark(["meta"], trials=2, classifier_fns={"meta": wrong_classifier}, judge_fns={"meta": flaky_judge}, summarize=summarize)[0]
    assert result.classifier_accuracy == 0.0 and len(result.classifier_confusions) == 16
    assert result.judge_errors > 0 and 0.0 < result.judge_accuracy < 1.0
    assert result.judge_consistency < 1.0


def test_classifier_exceptions_count_as_errors():
    def boom(summary):
        raise RuntimeError("down")

    result = bm.run_benchmark(["meta"], trials=2, classifier_fns={"meta": boom}, judge_fns={}, summarize=summarize)[0]
    assert result.classifier_errors == 16 and result.classifier_accuracy is None and result.judge_accuracy is None


def test_unconfigured_backend_is_skipped_and_rendered_as_such():
    results = bm.run_benchmark(["anthropic"], trials=1, classifier_fns={}, judge_fns={}, summarize=summarize)
    assert results[0].skipped == "no API key configured"
    assert "skipped" in bm.render(results, 1)


def test_consistency_is_the_mean_modal_share():
    assert bm._consistency([["a", "a", "a"], ["a", "b", "b"]]) == round((1 + 2 / 3) / 2, 4)
    assert bm._consistency([]) is None
