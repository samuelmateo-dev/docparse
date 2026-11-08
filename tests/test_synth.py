from docparse.synth import generate


def test_same_seed_same_documents_different_seed_different():
    a, b, c = generate(20, seed=1), generate(20, seed=1), generate(20, seed=2)
    assert [d.text for d in a] == [d.text for d in b]
    assert [d.text for d in a] != [d.text for d in c]


def test_truth_is_arithmetically_consistent():
    for d in generate(60, seed=5):
        t = d.truth
        assert round(sum(t["lines"]), 2) == t["subtotal"]
        assert round(t["subtotal"] + t["vat_amount"], 2) == t["total"]
        assert round(t["subtotal"] * t["vat_rate"] / 100, 2) == t["vat_amount"]


def test_noise_rate_extremes():
    clean = generate(30, seed=5, noise_rate=0.0)
    assert not any(d.truth["corrupted"] for d in clean)
    noisy = generate(30, seed=5, noise_rate=1.0)
    assert all(d.truth["corrupted"] for d in noisy)
    assert [d.text for d in clean] != [d.text for d in noisy]


def test_corruption_changes_exactly_one_character():
    for c, n in zip(generate(30, seed=5, noise_rate=0.0), generate(30, seed=5, noise_rate=1.0)):
        assert len(c.text) == len(n.text)
        assert sum(x != y for x, y in zip(c.text, n.text)) == 1
