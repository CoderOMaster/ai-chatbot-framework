import types
import builtins
import app.bot.nlu.nlu_service.trainer as trainer


class Args(types.SimpleNamespace):
    pass


def test_parse_args_defaults(monkeypatch):
    # Simulate no CLI args
    monkeypatch.setattr("sys.argv", ["trainer"])
    args = trainer.parse_args()
    assert args.train is False
    assert args.dry_run is False
    assert isinstance(args.models_dir, str)


def test_main_async_dry_run(monkeypatch, caplog):
    args = Args(dry_run=True)
    # ensure no training called
    called = {"train": False}

    async def fake_train_pipeline():
        called["train"] = True

    monkeypatch.setattr(trainer, "train_pipeline", fake_train_pipeline)

    # run
    code = trainer.asyncio.run(trainer.main_async(args))
    assert code == 0
    assert called["train"] is False


def test_main_async_trains_when_flag_set(monkeypatch):
    args = Args(dry_run=False)
    called = {"train": False}

    async def fake_train_pipeline():
        called["train"] = True

    monkeypatch.setattr(trainer, "train_pipeline", fake_train_pipeline)

    code = trainer.asyncio.run(trainer.main_async(args))
    assert code == 0
    assert called["train"] is True


def test_main_entrypoint_runs(monkeypatch):
    # Simulate CLI with --train
    monkeypatch.setattr("sys.argv", ["trainer", "--train"]) 

    # Prevent actually running asyncio loop; intercept main_async
    ran = {"called": False}

    def fake_run(coro):
        ran["called"] = True
        class Dummy:
            def __await__(self):
                if False:
                    yield None
                return 0
        return 0

    monkeypatch.setattr(trainer.asyncio, "run", lambda c: 0)

    rc = trainer.main()
    assert rc == 0