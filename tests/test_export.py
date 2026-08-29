from ytnb.export import render_day
from ytnb.models import Comment


def _c(cid, text, parent="", video="v1", title="動画A", t="10:00"):
    return Comment(cid, video, title, f"2026-06-06T{t}:00+09:00", "2026-06-06", "太郎", text, parent_id=parent)


def test_render_day_layout():
    text = render_day(
        "2026-06-06",
        [
            _c("c2", "2 番目", t="11:00"),
            _c("c1", "最初\n改行あり", t="09:00"),
            _c("r1", "返信です", parent="c1", t="09:30"),
            _c("orphan", "前日の親への返信", parent="c0", t="12:00"),
            _c("c3", "別動画", video="v2", title="動画B"),
        ],
    )
    lines = text.splitlines()
    assert lines[0] == "# 2026-06-06 のコメント"
    assert "## 動画A" in lines and "https://www.youtube.com/watch?v=v1" in lines
    assert "## 動画B" in lines
    i1 = lines.index("- (太郎, 09:00) 最初 改行あり")
    assert lines[i1 + 1] == "  - ↳ 返信 (太郎, 09:30) 返信です"
    assert lines[i1 + 2] == "- (太郎, 11:00) 2 番目"
    assert "- ↳ 返信 (親: 前日以前のコメント) (太郎, 12:00) 前日の親への返信" in lines
    assert lines[-1] == "合計 3 件のコメント、2 件の返信"


def test_render_day_excludes_reply_draft():
    c = _c("c1", "本文")
    c.reply_draft = "SECRET_DRAFT"
    assert "SECRET_DRAFT" not in render_day("2026-06-06", [c])
