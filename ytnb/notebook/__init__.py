from ytnb.notebook.base import NotebookSink, NullSink
from ytnb.notebook.local import LocalSink


def make_sink(cfg) -> NotebookSink:
    """config.notebook.sink に応じて Sink を返す。"""
    n = cfg.notebook
    if n.sink == "none":
        return NullSink()
    if n.sink == "local":
        return LocalSink(n.local_out_dir, n.drive_title_format)
    if n.sink == "drive":
        from ytnb.auth import drive_credentials
        from ytnb.notebook.drive import DriveSink

        return DriveSink(drive_credentials(cfg), n.drive_folder_id, n.drive_title_format)
    raise ValueError(f"unknown sink: {n.sink}")
