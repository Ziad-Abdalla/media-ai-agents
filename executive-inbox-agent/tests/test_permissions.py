import pytest

from inbox_agent import config
from inbox_agent.actions import ForbiddenAction
from inbox_agent.dlp import check_outbound
from inbox_agent.permissions import (ALLOWED_ACTIONS, ApprovalRequired, DLPBlocked, NotAuthorized,
                                     WritesDisabled, execute)


@pytest.fixture(autouse=True)
def triaged_email(ctx):
    ctx.store.add_email(id="E0", message_id="<e0@x>", status="triaged", from_addr="tariq@mbc-group.example")


def reply_plan(**over):
    plan = {"email_id": "E0", "to": ["tariq@mbc-group.example"], "subject": "Re: promo",
            "body": "شكرًا، سيتواصل معكم الفريق المختص.", "conversation": ["tariq@mbc-group.example"]}
    plan.update(over)
    return plan


@pytest.mark.parametrize("action", ["send_external", "attach_files", "bulk_export", "delete_email",
                                    "something_new"])
def test_forbidden_and_unknown_actions_are_refused_even_with_the_ceos_approval(ctx, action):
    with pytest.raises(ForbiddenAction):
        execute(action, {"to": ["x@evil.example"]}, ctx=ctx, approved_by="khalid")
    assert ctx.store.audit_rows()[0]["action"] == f"blocked:{action}"
    assert ctx.mailer.sent == []


def test_sending_needs_a_named_approver_with_that_right(ctx):
    with pytest.raises(ApprovalRequired):
        execute("send_reply", reply_plan(), ctx=ctx)
    with pytest.raises(NotAuthorized):
        execute("send_reply", reply_plan(), ctx=ctx, approved_by="noura")  # no approval rights
    execute("send_reply", reply_plan(), ctx=ctx, approved_by="sara")
    assert len(ctx.mailer.sent) == 1


def test_kill_switch_stops_everything(ctx, tmp_path, monkeypatch):
    (tmp_path / "agent.kill").write_text("stop")
    with pytest.raises(WritesDisabled):
        execute("send_reply", reply_plan(), ctx=ctx, approved_by="sara")
    assert ctx.mailer.sent == []


@pytest.mark.parametrize("over,reason", [
    ({"to": ["archive@proton-mail.example"], "conversation": ["archive@proton-mail.example"]}, "outside allowed"),
    ({"attachments": ["contracts.zip"]}, "attachments"),
    ({"to": ["tariq@mbc-group.example", "omar.haddad@sadaf.example"]}, "not in the conversation"),
    ({"body": "IBAN: SA03 8000 0000 6080 1016 7519"}, "IBAN"),
    ({"body": "مرفق ملخص سري للغاية للميزانية"}, "confidential"),
    ({"body": "رقم الهوية 1087654321"}, "national ID"),
    ({"body": "a@sadaf.example b@sadaf.example c@sadaf.example"}, "staff email"),
])
def test_dlp_blocks_leaks_even_after_approval(ctx, over, reason):
    with pytest.raises(DLPBlocked, match=reason):
        execute("send_reply", reply_plan(**over), ctx=ctx, approved_by="khalid")
    assert ctx.mailer.sent == []


def test_internal_forward_can_carry_confidential_text_but_only_inside(directory):
    ok = check_outbound("forward_internal", to=["hind.subaie@sadaf.example"], body="سري: بنود العقد",
                        directory=directory)
    assert not ok.blocked
    bad = check_outbound("forward_internal", to=["tariq@mbc-group.example"], body="hello", directory=directory)
    assert bad.blocked


def test_briefing_only_goes_to_the_executive_address(ctx):
    plan = {"to": ["exec-office@sadaf.example"], "subject": "موجز", "text": "x", "html": "<p>x</p>"}
    execute("send_briefing", plan, ctx=ctx)
    with pytest.raises(DLPBlocked):
        execute("send_briefing", {**plan, "to": ["majed.shehri@sadaf.example"]}, ctx=ctx)
    assert len(ctx.mailer.sent) == 1


def test_quarantined_email_blocks_every_action_on_it(ctx):
    ctx.store.add_email(id="E1", message_id="<q@x>", status="quarantined", from_addr="a@mbc-group.example")
    with pytest.raises(ForbiddenAction, match="quarantined"):
        execute("send_reply", reply_plan(email_id="E1"), ctx=ctx, approved_by="khalid")


def test_the_table_says_what_the_job_post_asks_for():
    assert ALLOWED_ACTIONS["draft_reply"] == "auto" and ALLOWED_ACTIONS["apply_label"] == "auto"
    assert {ALLOWED_ACTIONS[a] for a in ("send_reply", "forward_internal", "create_task")} == {"approval"}
    assert {ALLOWED_ACTIONS[a] for a in ("send_external", "attach_files", "bulk_export", "delete_email")} \
        == {"forbidden"}
    assert config.writes_enabled()
