from supadiag.network_quality import DEFAULT_THRESHOLDS, NetworkQualityAnalyzer, learn_quality_thresholds


def test_learn_quality_thresholds_defaults_when_empty():
    learned = learn_quality_thresholds([])
    assert learned["has_learned"] is False
    assert learned["total_feedbacks"] == 0
    assert learned["thresholds"] == DEFAULT_THRESHOLDS


def test_learn_quality_thresholds_from_operator_feedback():
    feedbacks = [
        {"label": "bom", "latency_ms": 20.0, "jitter_ms": 2.0, "packet_loss_percent": 0.0},
        {"label": "bom", "latency_ms": 40.0, "jitter_ms": 4.0, "packet_loss_percent": 0.0},
        {"label": "medio", "latency_ms": 80.0, "jitter_ms": 12.0, "packet_loss_percent": 0.6},
        {"label": "medio", "latency_ms": 100.0, "jitter_ms": 16.0, "packet_loss_percent": 1.0},
        {"label": "ruim", "latency_ms": 180.0, "jitter_ms": 35.0, "packet_loss_percent": 3.0},
        {"label": "ruim", "latency_ms": 220.0, "jitter_ms": 45.0, "packet_loss_percent": 5.0},
    ]

    learned = learn_quality_thresholds(feedbacks)
    assert learned["has_learned"] is True
    assert learned["counts"] == {"bom": 2, "medio": 2, "ruim": 2}

    lat_th = learned["thresholds"]["latency_ms"]
    assert lat_th["warn"] == 60.0   # ponto médio entre median(bom=30) e median(medio=90)
    assert lat_th["crit"] == 145.0  # ponto médio entre median(medio=90) e median(ruim=200)
    assert learned["ranges"]["latency_ms"]["bom"] == (0.0, 60.0)
    assert learned["ranges"]["latency_ms"]["medio"] == (60.0, 145.0)
    assert learned["ranges"]["latency_ms"]["ruim"] == (145.0, None)

    analyzer = NetworkQualityAnalyzer(settings=None, repository=None)
    assert analyzer.classify_quality(3.0, 45.0, 0.0, learned_thresholds=learned) == "BOM"
    assert analyzer.classify_quality(14.0, 95.0, 0.8, learned_thresholds=learned) == "MEDIO"
    assert analyzer.classify_quality(40.0, 190.0, 4.0, learned_thresholds=learned) == "RUIM"
