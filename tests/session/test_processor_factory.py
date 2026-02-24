from hotaru.session.processor import SessionProcessor
from hotaru.session.processor_factory import SessionProcessorFactory
from tests.helpers import fake_app


def test_processor_factory_builds_processor_with_collaborators() -> None:
    app = fake_app()
    proc = SessionProcessorFactory.build(
        app=app,
        session_id="ses",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    assert isinstance(proc, SessionProcessor)
    assert proc.agentflow is not None
    assert proc.turnprep is not None
    assert proc.turnrun is not None
    assert proc.tools is not None
