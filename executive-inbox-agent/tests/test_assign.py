from inbox_agent.assign import decide, evidence_in_email, rule_owner
from inbox_agent.models import ExtractedTask

from .conftest import task


def T(**over):
    return ExtractedTask(**task(**over))


def run(directory, t, category="urgent_action", priority="high", subject="تصريح التصوير",
        text="نرجو متابعة تصريح التصوير في حي الطريف.", received="2026-10-08T10:00:00+03:00"):
    return decide(directory, task=t, category=category, priority=priority, subject=subject,
                  email_text=text, received=received)


def test_agreement_with_evidence_is_proposed_without_confirmation(directory):
    d = run(directory, T(evidence_quote="متابعة تصريح التصوير"))
    assert d.proposed_owner == "abdulrahman" and d.rule_owner == "abdulrahman"
    assert not d.needs_confirmation


def test_urgent_tasks_always_need_a_person(directory):
    d = run(directory, T(urgent=True, evidence_quote="متابعة تصريح التصوير"))
    assert d.needs_confirmation and any("urgent" in r for r in d.reasons)


def test_a_name_that_is_not_the_owner_does_not_win(directory):
    text = "الأستاذ ماجد قال لي أتواصل معكم بخصوص تصريح التصوير في البلدية"
    owner, why = rule_owner(directory, category="urgent_action", task_text="متابعة تصريح البلدية",
                            evidence=text, subject="تصريح", email_text=text)
    assert owner == "abdulrahman", why


def test_an_explicit_request_for_a_person_wins_over_the_department_head(directory):
    text = "اطلبوا من نورة تأمّن مولد كهرباء للتصوير يوم الخميس"
    owner, why = rule_owner(directory, category="urgent_action", task_text="تأمين مولد للتصوير",
                            evidence=text, subject="مولد", email_text=text)
    assert owner == "noura" and "by name" in why


def test_disagreement_is_flagged_and_both_opinions_are_kept(directory):
    d = run(directory, T(suggested_owner_id="majed", evidence_quote="متابعة تصريح التصوير"))
    assert d.needs_confirmation and "model says majed, rules say abdulrahman" in d.reasons


def test_contract_questions_go_to_legal_even_when_payment_is_mentioned(directory):
    d = run(directory, T(suggested_owner_id="yousef", what_ar="الرد على سؤال جدول الدفعات في البند 6 من العقد",
                         evidence_quote="جدول الدفعات في البند 6"),
            category="legal_contract", text="عندي سؤال عن جدول الدفعات في البند 6 من العقد",
            received="2026-10-08T10:00:00+03:00")
    assert d.proposed_owner == "hind" and d.needs_confirmation


def test_out_of_office_owner_goes_to_the_delegate_and_is_flagged(directory):
    d = run(directory, T(suggested_owner_id="hind", what_ar="مراجعة بند الحصرية في العقد",
                         evidence_quote="بند الحصرية"),
            category="legal_contract", text="نرجو مراجعة بند الحصرية في العقد", received="2026-10-12T09:00:00+03:00")
    assert d.proposed_owner == "waleed" and "out of office" in d.owner_note
    assert d.needs_confirmation


def test_unknown_person_from_the_model_is_never_proposed(directory):
    d = run(directory, T(suggested_owner_id="mohammed", evidence_quote="متابعة تصريح التصوير"))
    assert d.proposed_owner == "abdulrahman" and d.needs_confirmation


def test_invented_evidence_is_caught():
    email = "نرجو متابعة تصريح التصوير في حي الطريف."
    assert evidence_in_email("متابعة تصريح التصوير", email)
    assert evidence_in_email("متابعه تصريح التصوير في حي الطريف", email)   # spelling variants are fine
    assert not evidence_in_email("الموافقة على ميزانية إضافية 50 ألف", email)
    assert not evidence_in_email("", email)


def test_approval_requests_go_to_the_general_manager(directory):
    d = run(directory, T(suggested_owner_id="reem", what_ar="اعتماد يوم تصوير إضافي",
                         evidence_quote="نرجو اعتماد يوم تصوير إضافي"),
            category="approval_needed", text="نرجو اعتماد يوم تصوير إضافي للحلقة 9")
    assert d.proposed_owner == "reem" and not d.needs_confirmation
