"""Comment worker registration and retry contracts."""

from pathlib import Path


def test_worker_wires_revalidating_comment_publisher() -> None:
    worker = Path("apps/worker/worker.py").read_text()

    assert "CommentCreatedPublisher(" in worker
    assert "comments=CommentRepository()" in worker
    assert "products=product_service" in worker
    assert "comment_handler=comment_handler" in worker
