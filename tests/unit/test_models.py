from datetime import datetime

import pytest
from pydantic import ValidationError

from mirofish_forecast.models import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
    VIXRegime,
)


class TestMacroIndicators:
    def test_valid_creation(self):
        m = MacroIndicators(fed_funds_rate=5.25, as_of=datetime.utcnow())
        assert m.fed_funds_rate == 5.25

    def test_optional_fields_default_none(self):
        m = MacroIndicators()
        assert m.fed_funds_rate is None
        assert m.ten_year_yield is None

    def test_frozen_rejects_mutation(self):
        m = MacroIndicators(fed_funds_rate=5.25)
        with pytest.raises(ValidationError):
            m.fed_funds_rate = 5.50

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            MacroIndicators(fed_funds_rate=5.25, bogus_field=99)


class TestVIXData:
    def test_regime_classification(self):
        v = VIXData(spot=25.0, regime=VIXRegime.ELEVATED)
        assert v.regime == VIXRegime.ELEVATED

    def test_empty_creation(self):
        v = VIXData()
        assert v.spot is None


class TestMarketContext:
    def test_full_assembly(self):
        ctx = MarketContext(
            macro=MacroIndicators(),
            vix=VIXData(),
            cross_asset=CrossAssetSnapshot(),
            fear_greed=FearGreedData(),
            internals=MarketInternals(),
            assembled_at=datetime.utcnow(),
        )
        assert ctx.macro.fed_funds_rate is None
        assert ctx.assembled_at is not None

    def test_serialization_roundtrip(self):
        ctx = MarketContext(
            macro=MacroIndicators(fed_funds_rate=5.25),
            vix=VIXData(spot=22.3, regime=VIXRegime.ELEVATED),
            cross_asset=CrossAssetSnapshot(es_price=5420.0),
            fear_greed=FearGreedData(value=38.0, description="Fear"),
            internals=MarketInternals(nyse_tick=-200.0),
            assembled_at=datetime.utcnow(),
        )
        json_str = ctx.model_dump_json()
        restored = MarketContext.model_validate_json(json_str)
        assert restored.macro.fed_funds_rate == 5.25
        assert restored.vix.regime == VIXRegime.ELEVATED
