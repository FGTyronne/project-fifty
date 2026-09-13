from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from project_fifty.domain.models import TradeAction
from tests.conftest import make_proposal


@given(
    bad=st.one_of(
        st.just(Decimal("-1")),
        st.just(Decimal("NaN")),
        st.just(Decimal("Infinity")),
        st.just(Decimal("-Infinity")),
    )
)
def test_invalid_monetary_and_quantity_cannot_validate(bad: Decimal) -> None:
    with pytest.raises(ValidationError):
        make_proposal(
            proposal_id="prop",
            key="idem",
            action=TradeAction.BUY,
            qty=bad,
            price=bad,
        )
