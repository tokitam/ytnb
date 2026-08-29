from datetime import date, datetime, timedelta, timezone

from tests.fakes import FakeSpreadsheet, MemorySink
from ytnb import pipeline
from ytnb.config import Config, NotebookConfig, SheetConfig, YouTubeConfig
from ytnb.models import COLUMNS, Comment
from ytnb.sheet import SheetStore


def _cfg(**nb):
    return Config(
        youtube=YouTubeConfig(channel_id="UCx", overlap_days=2),
        sheet=SheetConfig(spreadsheet_id="sid"),
        notebook=NotebookConfig(sink="local", retention_days=nb.get("retention_days", 30), channel_name="テストch"),
    )


def _c(cid, d, text="t", parent="", video="v1", title="動画"):
    return Comment(
        comment_id=cid,
        video_id=video,
        video_title=title,
        published_at=f"{d}T10:00:00+09:00",
        date=d,
        author="a",
        text=text,
        parent_id=parent,
    )


def test_store_creates_sheets_with_headers():
    ss = FakeSpreadsheet()
    SheetStore(ss)
    assert ss.sheets["comments"].rows[0] == COLUMNS
    assert ss.sheets["state"].rows[0] == ["key", "value"]


def test_append_dedupes_across_runs():
    store = SheetStore(FakeSpreadsheet())
    new1 = store.append_comments([_c("a", "2026-06-06"), _c("b", "2026-06-06"), _c("a", "2026-06-06")])
    assert [c.comment_id for c in new1] == ["a", "b"]
    new2 = store.append_comments([_c("a", "2026-06-06"), _c("c", "2026-06-07")])
    assert [c.comment_id for c in new2] == ["c"]
    assert len(store.all_comments()) == 3


def test_state_roundtrip_and_since_resolution():
    cfg = _cfg()
    store = SheetStore(FakeSpreadsheet())
    assert pipeline.resolve_since(store, cfg, None) is None

    pipeline.store(store, [_c("a", "2026-06-06"), _c("b", "2026-06-08")])
    assert store.get_state(pipeline.KEY_LAST_PUBLISHED) == "2026-06-08T10:00:00+09:00"
    assert store.get_state(pipeline.KEY_LAST_RUN)

    since = pipeline.resolve_since(store, cfg, None)
    assert since == datetime.fromisoformat("2026-06-08T10:00:00+09:00") - timedelta(days=2)

    # --since は state より優先
    assert pipeline.resolve_since(store, cfg, "2026-01-01") == datetime(2026, 1, 1, tzinfo=timezone.utc)

    # 古いコメントしか来なかった場合は last_published を戻さない
    pipeline.store(store, [_c("z", "2026-06-01")])
    assert store.get_state(pipeline.KEY_LAST_PUBLISHED) == "2026-06-08T10:00:00+09:00"


def test_export_groups_by_date_and_prunes():
    cfg = _cfg(retention_days=10)
    store = SheetStore(FakeSpreadsheet())
    store.append_comments(
        [
            _c("a", "2026-06-06", "こんにちは"),
            _c("a-r", "2026-06-06", "ありがとう", parent="a"),
            _c("b", "2026-06-05", "別の日"),
            _c("old", "2026-01-01", "古い"),
        ]
    )
    sink = MemorySink()
    sink.docs["2026-01-01"] = "stale"
    exported = pipeline.export(cfg, store, None, sink=sink, today=date(2026, 6, 10))
    assert exported == ["2026-06-05", "2026-06-06"]
    assert "2026-01-01" not in sink.docs and sink.deleted == ["id-2026-01-01"]
    doc = sink.docs["2026-06-06"]
    assert doc.startswith("# 2026-06-06 のコメント (テストch)")
    assert "こんにちは" in doc and "↳ 返信 (a, 10:00) ありがとう" in doc
    assert store.get_state(pipeline.KEY_LAST_EXPORT) == "2026-06-06"

    # 日付指定
    sink2 = MemorySink()
    assert pipeline.export(cfg, store, {"2026-06-05"}, sink=sink2, today=date(2026, 6, 10)) == ["2026-06-05"]
    assert list(sink2.docs) == ["2026-06-05"]


def test_export_explicit_date_ignores_retention():
    cfg = _cfg(retention_days=10)
    store = SheetStore(FakeSpreadsheet())
    store.append_comments([_c("old", "2026-01-01", "古い")])
    sink = MemorySink()
    assert pipeline.export(cfg, store, None, sink=sink, today=date(2026, 6, 10)) == []
    assert pipeline.export(cfg, store, {"2026-01-01"}, sink=sink, today=date(2026, 6, 10)) == ["2026-01-01"]
    assert "古い" in sink.docs["2026-01-01"]
