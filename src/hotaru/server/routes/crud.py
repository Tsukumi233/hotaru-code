"""Generic CRUD-style route factory."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar, cast

from fastapi import APIRouter
from pydantic import BaseModel

Model = TypeVar("Model", bound=BaseModel)
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
Kind = Literal["raw", "one", "many"]
Fn = Callable[..., object]


@dataclass(frozen=True)
class Route:
    method: Method
    path: str
    response_model: object | None
    fn: Fn
    kind: Kind = "raw"
    schema: type[BaseModel] | None = None


def raw(method: Method, path: str, response_model: object | None, fn: Fn) -> Route:
    return Route(method=method, path=path, response_model=response_model, fn=fn)


def one(method: Method, path: str, response_model: type[Model], fn: Fn) -> Route:
    return Route(
        method=method,
        path=path,
        response_model=response_model,
        fn=fn,
        kind="one",
        schema=response_model,
    )


def many(method: Method, path: str, response_model: type[Model], fn: Fn) -> Route:
    return Route(
        method=method,
        path=path,
        response_model=list[response_model],
        fn=fn,
        kind="many",
        schema=response_model,
    )


async def _call(fn: Fn, *a: object, **kw: object) -> object:
    out = fn(*a, **kw)
    if inspect.isawaitable(out):
        return await cast(Awaitable[object], out)
    return out


def _serialize(spec: Route, out: object) -> object:
    if spec.kind == "one":
        if spec.schema is None:
            raise ValueError("Route schema is required for one")
        return spec.schema.model_validate(out)
    if spec.kind == "many":
        if spec.schema is None:
            raise ValueError("Route schema is required for many")
        return [spec.schema.model_validate(item) for item in cast(Iterable[object], out)]
    return out


def _endpoint(spec: Route) -> Callable[..., Awaitable[object]]:
    async def endpoint(*a: object, **kw: object) -> object:
        return _serialize(spec, await _call(spec.fn, *a, **kw))

    endpoint.__name__ = spec.fn.__name__
    endpoint.__doc__ = spec.fn.__doc__
    endpoint.__module__ = spec.fn.__module__
    ctx = vars(sys.modules[spec.fn.__module__])
    endpoint.__signature__ = inspect.signature(spec.fn, eval_str=True, globals=ctx, locals=ctx)
    return endpoint


def crud_router(*, prefix: str, tags: list[str], routes: Sequence[Route]) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags)
    for item in routes:
        router.add_api_route(
            item.path,
            _endpoint(item),
            methods=[item.method],
            response_model=item.response_model,
        )
    return router
