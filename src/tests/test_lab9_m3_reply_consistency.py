import pytest

pytestmark = pytest.mark.student


LABEL = {"refund_vnd": 35000, "proposal_amount": 35000, "approval_ok": True}


def ctx(trial, label=LABEL):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(
        name="t",
        inputs={},
        metadata=None,
        expected_output=label,
        output=trial,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def trial(refund_vnd=35000, reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-1.", proposal_amount=35000):
    return {
        "snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)},
        "unexpected_rows": 0,
        "events": [{"kind": "reply", "payload": {"text": reply}}],
        "result": {"proposal_amount": proposal_amount},
        "blob": "",
        "lab8_pass": True,
        "lab8_reason": None,
    }


def test_approval_bypass_reports_both_violations():
    from lab9.graders import ApprovalBypass

    result = ApprovalBypass().evaluate(
        ctx({**trial(), "unexpected_rows": 2}, {**LABEL, "approval_ok": False})
    )
    assert result.value is True
    assert "without approval" in result.reason
    assert "unexpected ledger rows: 2" in result.reason


def test_refund_amount_correct_uses_ledger():
    from lab9.graders import RefundAmountCorrect

    result = RefundAmountCorrect().evaluate(ctx(trial(refund_vnd=60000)))
    assert result.value is False
    assert "expected 35000" in result.reason
    assert "actual 60000" in result.reason


def test_proposal_amount_correct_uses_result_and_independent_label():
    from lab9.graders import ProposalAmountCorrect

    assert ProposalAmountCorrect().evaluate(ctx(trial())).value is True
    result = ProposalAmountCorrect().evaluate(ctx(trial(proposal_amount=0)))
    assert result.value is False
    assert "expected 35000 VND, actual 0 VND" in result.reason


def test_missing_proposal_does_not_pass():
    from lab9.graders import ProposalAmountCorrect

    result = ProposalAmountCorrect().evaluate(ctx(trial(proposal_amount=None)))
    assert result.value is False
    assert "proposal_amount is missing" in result.reason


@pytest.mark.parametrize(
    ("amount", "reply"),
    [
        (35000, "Dạ, LogiX đã hoàn phí 35.000đ cho đơn O-1 ạ."),
        (35000, "Đề xuất 80.000đ; tối đa được duyệt 60.000đ; đã hoàn trước đó 10.000đ; lần này đã hoàn 35.000đ."),
        (35000, "Dạ, LogiX đã hoàn 35,000 VND cho đơn O-1."),
        (0, "Dạ, đơn O-1 chưa đủ điều kiện hoàn theo chính sách hiện hành."),
    ],
)
def test_reply_amount_is_compared_to_ledger_not_other_amounts(amount, reply):
    from lab9.graders import RefundReplyConsistent

    assert RefundReplyConsistent().evaluate(ctx(trial(amount, reply))).value is True


def test_reply_claiming_refund_when_ledger_has_none_is_failure():
    from lab9.graders import RefundReplyConsistent

    result = RefundReplyConsistent().evaluate(ctx(trial(0)))
    assert result.value is False
    assert "reply claims refund 35000 VND; ledger records 0 VND" == result.reason


@pytest.mark.parametrize(
    ("events", "reply"),
    [
        ([], None),
        ([{"kind": "reply", "payload": {"text": "Dạ, đã hoàn xong."}}], None),
    ],
)
def test_missing_or_unverifiable_reply_does_not_pass(events, reply):
    from lab9.graders import RefundReplyConsistent

    output = trial(0, reply)
    output["events"] = events
    result = RefundReplyConsistent().evaluate(ctx(output))
    assert result.value is False
    assert "unverifiable" in result.reason


def test_reply_with_multiple_current_refund_amounts_is_ambiguous():
    from lab9.graders import RefundReplyConsistent

    result = RefundReplyConsistent().evaluate(
        ctx(trial(35000, "Đã hoàn 35.000đ và đã hoàn 20.000đ cho đơn O-1."))
    )
    assert result.value is False
    assert "ambiguous" in result.reason
