import contextlib
import functools
import inspect
from contextvars import ContextVar
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
)

from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.middleware.base import BaseHTTPMiddleware

from wireup import inject_from_container, service
from wireup.errors import WireupError
from wireup.integration.util import is_view_using_container
from wireup.ioc.container.async_container import AsyncContainer, ScopedAsyncContainer
from wireup.ioc.types import AnyCallable, ParameterWrapper
from wireup.ioc.validation import get_inject_annotated_parameters, get_valid_injection_annotated_parameters

current_request: ContextVar[Request] = ContextVar("wireup_fastapi_request")
current_ws_container: ContextVar[ScopedAsyncContainer] = ContextVar("wireup_fastapi_container")


def _hide_annotated_names(func: AnyCallable) -> AnyCallable:
    names_to_hide = get_inject_annotated_parameters(func)
    orig_sig = inspect.signature(func)
    filtered_params = {name: param for name, param in orig_sig.parameters.items() if param.name not in names_to_hide}
    new_sig = inspect.Signature(parameters=list(filtered_params.values()), return_annotation=orig_sig.return_annotation)
    new_annotations = {
        name: annotation for name, annotation in func.__annotations__.items() if name not in names_to_hide
    }

    func.__wireup_names__ = get_inject_annotated_parameters(func)  # type: ignore[attr-defined]
    func.__signature__ = new_sig  # type: ignore[attr-defined]
    func.__annotations__ = new_annotations

    return func


class WireupRoute(APIRoute):
    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        super().__init__(path=path, endpoint=_hide_annotated_names(endpoint), **kwargs)


async def _wireup_request_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    token = current_request.set(request)
    try:
        async with request.app.state.wireup_container.enter_scope() as scoped_container:
            request.state.wireup_container = scoped_container
            return await call_next(request)
    finally:
        current_request.reset(token)


@service(lifetime="scoped")
def fastapi_request_factory() -> Request:
    """Provide the current FastAPI request as a dependency.

    Note that this requires the Wireup-FastAPI integration to be set up.
    """
    try:
        return current_request.get()
    except LookupError as e:
        msg = "fastapi.Request in wireup is only available during a request."
        raise WireupError(msg) from e


# We need to inject websocket routes separately as the regular fastapi middlewares work only for http.
def _inject_websocket_route(container: AsyncContainer, target: Callable[..., Any]) -> Callable[..., Any]:
    names_to_inject = get_valid_injection_annotated_parameters(container, target)

    @functools.wraps(target)
    async def _inner(*args: Any, **kwargs: Any) -> Any:
        async with container.enter_scope() as scoped_container:
            token = current_ws_container.set(scoped_container)
            injected_names = {
                name: container.params.get(param.annotation.param)
                if isinstance(param.annotation, ParameterWrapper)
                else await scoped_container.get(param.klass, qualifier=param.qualifier_value)
                for name, param in names_to_inject.items()
                if param.annotation
            }

            try:
                return await target(*args, **{**kwargs, **injected_names})
            finally:
                current_ws_container.reset(token)

    return _inner


def _inject_routes(container: AsyncContainer, app: FastAPI) -> None:
    inject_scoped = inject_from_container(container, get_request_container)

    for route in app.routes:
        if (
            isinstance(route, (APIRoute, APIWebSocketRoute))
            and route.dependant.call
            and is_view_using_container(container, route.dependant.call)
        ):
            target = route.dependant.call
            route.dependant.call = (
                inject_scoped(target) if isinstance(route, APIRoute) else _inject_websocket_route(container, target)
            )


def _update_lifespan(container: AsyncContainer, app: FastAPI) -> None:
    old_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with old_lifespan(app) as state:
            yield state

        await container.close()

    app.router.lifespan_context = lifespan


def setup(container: AsyncContainer, app: FastAPI) -> None:
    """Integrate Wireup with FastAPI.

    This performs the following:
    * Inject dependencies in http and websocket routes.
    * Enter a new container scope per request. Scoped lifetime lasts as long as the request does.
    * Expose `fastapi.Request` as a Wireup scoped dependency.
    * Close the Wireup container on app shutdown via lifespan.

    See: https://maldoinc.github.io/wireup/latest/integrations/fastapi/

    Note that for lifespan events to trigger in the FastAPI test client you must use the client as a context manager.
    ```python
    @pytest.fixture()
    def client(app: FastAPI) -> Iterator[TestClient]:
        with TestClient(app) as client:
            yield client
    ```
    """
    _update_lifespan(container, app)

    app.add_middleware(BaseHTTPMiddleware, dispatch=_wireup_request_middleware)
    _inject_routes(container, app)
    app.state.wireup_container = container


def get_app_container(app: FastAPI) -> AsyncContainer:
    """Return the container associated with the given FastAPI application."""
    return app.state.wireup_container


def get_request_container() -> ScopedAsyncContainer:
    """When inside a request, returns the scoped container instance handling the current request."""
    try:
        return current_request.get().state.wireup_container
    except LookupError:
        return current_ws_container.get()
