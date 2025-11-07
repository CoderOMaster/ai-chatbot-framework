def test_compat_shims_delegate(monkeypatch):
    called = {"fb": False, "rest": False}

    def fake_fb(event, ctx):
        called["fb"] = True
        return {"ok": True}

    def fake_rest(event, ctx):
        called["rest"] = True
        return {"ok": True}

    import lambda_handlers.webhooks.facebook as real_fb
    import lambda_handlers.webhooks.rest as real_rest

    monkeypatch.setattr(real_fb, "handler", fake_fb)
    monkeypatch.setattr(real_rest, "handler", fake_rest)

    from lambda.handlers.webhooks import facebook as shim_fb
    from lambda.handlers.webhooks import rest as shim_rest

    assert shim_fb.handler({}, None) == {"ok": True}
    assert shim_rest.handler({}, None) == {"ok": True}

    assert called["fb"] and called["rest"]