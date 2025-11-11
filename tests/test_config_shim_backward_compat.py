def test_config_shim_exposes_app_config_settings():
    # Backward compatibility: importing app.config provides Settings instance as app_config
    from app.config import app_config
    from app.common.config import Settings

    assert isinstance(app_config, Settings)
    # should have default fields available
    assert hasattr(app_config, "MONGODB_HOST")