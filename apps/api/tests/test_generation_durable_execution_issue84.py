from tevion_api import services


def test_durable_execution_boundary_is_exposed() -> None:
    assert callable(services.submit_or_resume_generation)


def test_recovery_sweep_is_exposed() -> None:
    assert callable(services.recovery_sweep)


def test_disconnect_handler_is_exposed() -> None:
    assert callable(services.handle_generation_disconnect)


def test_execution_adapter_protocol_is_exposed() -> None:
    assert services.GenerationExecutionAdapter is not None


def test_generation_run_has_lease_columns() -> None:
    from tevion_api.models import GenerationRun

    assert "lease_owner" in GenerationRun.__table__.c
    assert "lease_expires_at" in GenerationRun.__table__.c
