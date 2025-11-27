from typing import Any, Callable, Optional, TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    # Only for type-checkers to avoid importing heavy runtime modules at import time
    from config import BaseConfig  # noqa: F401


class _AppRequiredKeys(BaseModel):
    """Minimal required configuration keys validated via pydantic."""

    MONGODB_HOST: str
    MONGODB_DATABASE: str


def get_app_config(
    overrides: Optional[dict] = None,
    loader: Optional[Callable[[], Any]] = None,
    raise_on_error: bool = True,
) -> Any:
    """Lazily load and validate the application configuration.

    Parameters
    - overrides: optional dictionary of values to override on the loaded config
    - loader: optional callable that returns a config instance. If not provided,
      the function will import and call config.from_envvar() lazily which
      avoids heavy or circular imports at module import time.
    - raise_on_error: if True, validation errors are raised; otherwise the
      (possibly invalid) loaded config is returned.

    Returns
    - An instance of the project's config model (typically a pydantic BaseModel).

    This function supports dependency injection by accepting a custom loader
    or overrides which makes unit testing predictable and avoids relying on
    global state.
    """
    # Import the default loader lazily to guard against circular/heavy imports
    if loader is None:
        from config import from_envvar as loader  # local import to avoid circular import

    loaded = loader()

    # Attempt to convert the loaded config to a dict. Most project configs use
    # pydantic BaseModel, which exposes .dict(); if not available, fall back to
    # collecting UPPERCASE attributes.
    try:
        data = loaded.dict()
    except Exception:
        data = {k: getattr(loaded, k) for k in dir(loaded) if k.isupper()}

    # Apply overrides (dependency injection) by creating a fresh instance of
    # the loaded config class with merged values when overrides are provided.
    if overrides:
        merged = {**data, **overrides}
        try:
            loaded = loaded.__class__(**merged)
            data = merged
        except Exception:
            # If instantiation fails, keep the original loaded and update data
            data.update(overrides)

    # Validate required keys using a lightweight pydantic model
    try:
        _AppRequiredKeys(**data)
    except ValidationError:
        if raise_on_error:
            raise

    return loaded