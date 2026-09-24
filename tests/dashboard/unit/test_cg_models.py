def test_module_imports():
    from dashboard.models import cg_models
    assert callable(cg_models.list_models)
