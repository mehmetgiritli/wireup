from __future__ import annotations

import asyncio
import functools
from contextlib import AsyncExitStack, ExitStack
from typing import TYPE_CHECKING, Any

from wireup.errors import WireupError
from wireup.ioc.container.async_container import AsyncContainer, async_container_force_sync_scope
from wireup.ioc.container.sync_container import SyncContainer
from wireup.ioc.types import ParameterWrapper
from wireup.ioc.validation import get_valid_injection_annotated_parameters

if TYPE_CHECKING:
    from collections.abc import Callable

    from wireup.ioc.container.async_container import ScopedAsyncContainer
    from wireup.ioc.container.sync_container import ScopedSyncContainer


def inject_from_container(
    container: SyncContainer | AsyncContainer,
    scoped_container_supplier: Callable[[], ScopedSyncContainer | ScopedAsyncContainer] | None = None,
) -> Callable[..., Any]:
    """Inject dependencies into the decorated function based on annotations.

    :param container: The main container instance created via `wireup.create_sync_container` or
    `wireup.create_async_container`.
    :param scoped_container_supplier: An optional callable that returns the current scoped container instance.
    If provided, it will be used to create scoped dependencies. If not provided, the container will automatically
    enter a scope. Provide a scoped_container_supplier if you need to manage the container's scope manually. For
    example, in web frameworks, you might enter the scope at the start of a request in middleware so that other
    middlewares can access the scoped container if needed.
    """

    def _decorator(target: Callable[..., Any]) -> Callable[..., Any]:
        names_to_inject = get_valid_injection_annotated_parameters(container, target)

        if asyncio.iscoroutinefunction(target):
            if isinstance(container, SyncContainer):
                msg = (
                    "Sync container cannot perform injection on async targets. "
                    "Create an async container via wireup.create_async_container."
                )
                raise WireupError(msg)

            @functools.wraps(target)
            async def _inject_async_target(*args: Any, **kwargs: Any) -> Any:
                async with AsyncExitStack() as cm:
                    scoped_container = (
                        scoped_container_supplier()
                        if scoped_container_supplier
                        else await cm.enter_async_context(container.enter_scope())  # type:ignore[reportArgumentType, unused-ignore]
                    )

                    injected_names = {
                        name: container.params.get(param.annotation.param)
                        if isinstance(param.annotation, ParameterWrapper)
                        else await scoped_container.get(param.klass, qualifier=param.qualifier_value)
                        for name, param in names_to_inject.items()
                        if param.annotation
                    }

                    return await target(*args, **{**kwargs, **injected_names})

            return _inject_async_target

        @functools.wraps(target)
        def _inject_target(*args: Any, **kwargs: Any) -> Any:
            with ExitStack() as cm:
                scoped_container = (
                    scoped_container_supplier()
                    if scoped_container_supplier
                    else cm.enter_context(
                        container.enter_scope()
                        if isinstance(container, SyncContainer)
                        else async_container_force_sync_scope(container)
                    )
                )
                get = scoped_container._synchronous_get

                injected_names = {
                    name: container.params.get(param.annotation.param)
                    if isinstance(param.annotation, ParameterWrapper)
                    else get(param.klass, qualifier=param.qualifier_value)
                    for name, param in names_to_inject.items()
                    if param.annotation
                }
                return target(*args, **{**kwargs, **injected_names})

        return _inject_target

    return _decorator
