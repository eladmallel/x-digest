"""Test module imports and basic scaffolding."""

def test_imports():
    """All modules import without error."""
    from x_digest import config, fetch, classify, models, presummary, images, digest, status, errors
    from x_digest.llm import base as llm_base
    from x_digest.delivery import base as delivery_base
    assert True


def test_version_import():
    """Package version is accessible."""
    import x_digest
    assert hasattr(x_digest, '__version__')
    assert x_digest.__version__ == "0.1.0"


def test_error_code_enum():
    """ErrorCode enum is properly defined."""
    from x_digest.errors import ErrorCode
    
    # Test a few key error codes exist
    assert hasattr(ErrorCode, 'BIRD_AUTH_FAILED')
    assert hasattr(ErrorCode, 'LLM_TIMEOUT')
    assert hasattr(ErrorCode, 'DELIVERY_SEND_FAILED')
    
    # Test they have string values
    assert ErrorCode.BIRD_AUTH_FAILED.value == "BIRD_AUTH_FAILED"