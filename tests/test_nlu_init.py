def test_package_exports():
    from nlu_service import __all__

    assert "api" in __all__
    assert "pipeline" in __all__
    assert "trainer" in __all__