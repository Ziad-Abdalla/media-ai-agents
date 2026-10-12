from inbox_agent.normalize import split_body

from .conftest import make_email

MBC = ("Tariq", "tariq@mbc-group.example")


def add(ctx, email):
    split_body(email)
    vec = ctx.linker.embed(email)
    link = ctx.linker.link(email, vec)
    ctx.linker.record(email, link)
    ctx.store.add_email(id=email.source_id, message_id=email.message_id, source_id=email.source_id,
                        thread_id=link.thread_id, from_addr=email.from_addr, subject=email.subject,
                        date=email.date, status="triaged",
                        embedding=vec.tobytes() if vec is not None else None)
    return link


def test_reply_headers_link_with_full_confidence(ctx):
    first = add(ctx, make_email("a", subject="Promo materials", sender=MBC, message_id="<a@m>"))
    reply = add(ctx, make_email("b", subject="Re: Promo materials", sender=("Omar", "omar.haddad@sadaf.example"),
                                message_id="<b@s>", in_reply_to="<a@m>", references=["<a@m>"],
                                date="2026-10-12T10:00:00+03:00"))
    assert reply.thread_id == first.thread_id and reply.method == "headers" and reply.confidence == 1.0


def test_forward_without_headers_links_by_original_subject_and_sender(ctx):
    first = add(ctx, make_email("a", subject="Delivery specs Ramadan 2027", sender=MBC, message_id="<a@m>"))
    body = ("FYI\n\n---------- Forwarded message ---------\nFrom: Tariq <tariq@mbc-group.example>\n"
            "Subject: Delivery specs Ramadan 2027\n\nProRes masters by 15 Dec")
    fwd = add(ctx, make_email("b", subject="Fwd: Delivery specs Ramadan 2027", body=body,
                              sender=("Omar", "omar.haddad@sadaf.example"), message_id="<b@s>"))
    assert fwd.thread_id == first.thread_id and fwd.method == "subject"


def test_same_generic_subject_from_two_vendors_is_not_linked(ctx):
    a = add(ctx, make_email("a", subject="فاتورة", body="فاتورة تأجير الإضاءة",
                            sender=("A", "accounts@desertlights-rental.example"), message_id="<a@d>"))
    b = add(ctx, make_email("b", subject="فاتورة", body="فاتورة خدمات الإعاشة",
                            sender=("B", "billing@catering.example"), message_id="<b@c>"))
    assert a.thread_id != b.thread_id


def test_phone_reply_with_new_subject_links_by_meaning(ctx):
    director = ("Director", "director@studio.example")
    first = add(ctx, make_email("a", subject="تغيير موعد تصوير الحلقة السابعة",
                                body="نحتاج نقل تصوير الحلقة السابعة من الخميس الى السبت في موقع الدرعية",
                                sender=director, message_id="<a@x>"))
    later = add(ctx, make_email("b", subject="تحديث", body="بخصوص نقل تصوير الحلقة السابعة الى السبت في الدرعية تم التأكيد",
                                sender=director, message_id="<b@x>"))
    assert later.thread_id == first.thread_id and later.method == "embedding"
    assert "similar meaning" in later.reason


def test_similar_text_from_a_stranger_is_not_linked(ctx):
    add(ctx, make_email("a", subject="تغيير موعد التصوير", body="نقل تصوير الحلقة السابعة الى السبت",
                        sender=("D", "director@studio.example"), message_id="<a@x>"))
    other = add(ctx, make_email("b", subject="سؤال", body="نقل تصوير الحلقة السابعة الى السبت",
                                sender=("S", "someone@else.example"), message_id="<b@y>"))
    assert other.method == "new"
