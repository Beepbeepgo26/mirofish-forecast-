"""Test FeatureExtractor."""

import numpy as np

from mirofish_forecast.ml.feature_extractor import (
    FEATURE_NAMES,
    FeatureExtractor,
)


class TestFeatureExtractor:
    def test_feature_count(self) -> None:
        """Should have correct number of features."""
        extractor = FeatureExtractor()
        assert extractor.feature_count == 25
        assert len(extractor.feature_names) == 25

    def test_feature_names_unique(self) -> None:
        """All feature names must be unique."""
        assert len(set(FEATURE_NAMES)) == len(FEATURE_NAMES)

    def test_extract_from_historical_shape(self) -> None:
        """extract_from_historical returns correct shape."""
        extractor = FeatureExtractor()
        n = 200
        closes = np.linspace(5200, 5400, n)
        highs = closes + 5
        lows = closes - 5
        opens = closes - 1
        volumes = np.ones(n) * 10000

        result = extractor.extract_from_historical(
            closes,
            highs,
            lows,
            opens,
            volumes,
            idx=100,
            horizon_minutes=120,
        )
        assert result.shape == (25,)
        assert result.dtype == np.float32

    def test_extract_from_historical_no_nan(self) -> None:
        """All features should be finite (no NaN/inf)."""
        extractor = FeatureExtractor()
        n = 200
        closes = np.linspace(5200, 5400, n)
        highs = closes + 5
        lows = closes - 5
        opens = closes - 1
        volumes = np.ones(n) * 10000

        result = extractor.extract_from_historical(
            closes,
            highs,
            lows,
            opens,
            volumes,
            idx=100,
            horizon_minutes=60,
        )
        assert np.all(np.isfinite(result))

    def test_extract_from_historical_edge_idx(self) -> None:
        """Should handle early indices gracefully (no crash)."""
        extractor = FeatureExtractor()
        n = 100
        closes = np.linspace(5200, 5400, n)
        highs = closes + 5
        lows = closes - 5
        opens = closes - 1
        volumes = np.ones(n) * 10000

        # Very early index — many features will be zero
        result = extractor.extract_from_historical(
            closes,
            highs,
            lows,
            opens,
            volumes,
            idx=2,
            horizon_minutes=30,
        )
        assert result.shape == (25,)
        assert np.all(np.isfinite(result))

    def test_horizon_encoded(self) -> None:
        """Horizon minutes should be encoded as the last feature."""
        extractor = FeatureExtractor()
        n = 200
        closes = np.linspace(5200, 5400, n)
        highs = closes + 5
        lows = closes - 5
        opens = closes - 1
        volumes = np.ones(n) * 10000

        result = extractor.extract_from_historical(
            closes,
            highs,
            lows,
            opens,
            volumes,
            idx=100,
            horizon_minutes=240,
        )
        assert result[-1] == 240.0  # Last feature = horizon_minutes

    def test_momentum_varies(self) -> None:
        """Momentum features should differ for trending vs flat data."""
        extractor = FeatureExtractor()
        n = 200

        # Trending up
        closes_up = np.linspace(5200, 5400, n)
        highs = closes_up + 5
        lows = closes_up - 5
        opens = closes_up - 1
        volumes = np.ones(n) * 10000

        result_up = extractor.extract_from_historical(
            closes_up,
            highs,
            lows,
            opens,
            volumes,
            idx=100,
            horizon_minutes=120,
        )

        # Flat
        closes_flat = np.ones(n) * 5300
        highs_f = closes_flat + 5
        lows_f = closes_flat - 5
        opens_f = closes_flat - 1

        result_flat = extractor.extract_from_historical(
            closes_flat,
            highs_f,
            lows_f,
            opens_f,
            volumes,
            idx=100,
            horizon_minutes=120,
        )

        # return_1bar (index 0) should differ
        assert result_up[0] != result_flat[0]

    def test_cross_asset_features_populated(self) -> None:
        """Cross-asset returns should be non-zero when arrays are provided."""
        extractor = FeatureExtractor()
        n = 200
        closes = np.linspace(5200, 5400, n)
        highs = closes + 5
        lows = closes - 5
        opens = closes - 1
        volumes = np.ones(n) * 10000

        # DXY trending up
        dxy = np.linspace(104.0, 105.0, n)
        # TLT trending down
        tlt = np.linspace(92.0, 90.0, n)
        # Crude flat
        crude = np.ones(n) * 78.0

        result = extractor.extract_from_historical(
            closes,
            highs,
            lows,
            opens,
            volumes,
            idx=100,
            horizon_minutes=120,
            dxy_closes=dxy,
            tlt_closes=tlt,
            crude_closes=crude,
        )

        # Indices 21, 22, 23 should be non-zero
        assert result[21] != 0.0  # dxy_return_1d
        assert result[22] != 0.0  # tlt_return_1d
        # crude is flat, so return should be ~0
        assert abs(result[23]) < 0.001

    def test_cross_asset_features_zero_when_missing(self) -> None:
        """Cross-asset returns should be zero when arrays are None."""
        extractor = FeatureExtractor()
        n = 200
        closes = np.linspace(5200, 5400, n)
        highs = closes + 5
        lows = closes - 5
        opens = closes - 1
        volumes = np.ones(n) * 10000

        result = extractor.extract_from_historical(
            closes,
            highs,
            lows,
            opens,
            volumes,
            idx=100,
            horizon_minutes=120,
        )

        assert result[21] == 0.0
        assert result[22] == 0.0
        assert result[23] == 0.0
