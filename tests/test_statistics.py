from confido_eval.compare import weighted_kappa, wilson_interval


def test_wilson_interval_bounds() -> None:
    interval = wilson_interval(9, 10)
    assert interval is not None
    assert 0 <= interval[0] < interval[1] <= 1


def test_weighted_kappa_perfect_agreement() -> None:
    assert weighted_kappa([(0, 0), (1, 1), (2, 2), (3, 3)]) == 1.0
