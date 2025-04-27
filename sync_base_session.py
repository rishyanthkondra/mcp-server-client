import logging
import threading
import queue
from datetime import timedelta
from typing import Any, Callable, Generic, TypeVar, Union

from pydantic import BaseModel

from mcp.shared.exceptions import McpError
from mcp.types import (
    CancelledNotification,
    ClientNotification,
    ClientRequest,
    ClientResult,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestParams,
    ServerNotification,
    ServerRequest,
    ServerResult,
)

SendRequestT = TypeVar("SendRequestT", ClientRequest, ServerRequest)
SendResultT = TypeVar("SendResultT", ClientResult, ServerResult)
SendNotificationT = TypeVar("SendNotificationT", ClientNotification, ServerNotification)
ReceiveRequestT = TypeVar("ReceiveRequestT", ClientRequest, ServerRequest)
ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)
ReceiveNotificationT = TypeVar("ReceiveNotificationT", ClientNotification, ServerNotification)

RequestId = Union[str, int]


class RequestResponder(Generic[ReceiveRequestT, SendResultT]):
    """Handles responding to MCP requests and manages request lifecycle."""

    def __init__(
        self,
        request_id: RequestId,
        request_meta: RequestParams.Meta | None,
        request: ReceiveRequestT,
        session: """BaseSession[
            SendRequestT,
            SendNotificationT,
            SendResultT,
            ReceiveRequestT,
            ReceiveNotificationT
        ]""",
        on_complete: Callable[["RequestResponder[ReceiveRequestT, SendResultT]"], Any],
    ) -> None:
        self.request_id = request_id
        self.request_meta = request_meta
        self.request = request
        self._session = session
        self._completed = False
        self._cancelled = False
        self._on_complete = on_complete
        self._lock = threading.Lock()
        self._entered = False

    def __enter__(self) -> "RequestResponder[ReceiveRequestT, SendResultT]":
        self._entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        with self._lock:
            if self._completed:
                self._on_complete(self)
            self._entered = False

    def respond(self, response: SendResultT | ErrorData) -> None:
        with self._lock:
            if not self._entered:
                raise RuntimeError("RequestResponder must be used as a context manager")
            if self._completed:
                raise AssertionError("Request already responded to")

            if not self.cancelled:
                self._completed = True
                self._session._send_response(
                    request_id=self.request_id, response=response
                )

    def cancel(self) -> None:
        with self._lock:
            if not self._entered:
                raise RuntimeError("RequestResponder must be used as a context manager")
            self._cancelled = True
            self._completed = True
            self._session._send_response(
                request_id=self.request_id,
                response=ErrorData(code=0, message="Request cancelled", data=None),
            )

    @property
    def in_flight(self) -> bool:
        return not self._completed and not self.cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class BaseSession(Generic[SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveNotificationT]):
    """Implements an MCP "session" synchronously using threads."""

    def __init__(
        self,
        read_queue: "queue.Queue[JSONRPCMessage | Exception]",
        write_queue: "queue.Queue[JSONRPCMessage]",
        receive_request_type: type[ReceiveRequestT],
        receive_notification_type: type[ReceiveNotificationT],
        read_timeout_seconds: timedelta | None = None,
    ) -> None:
        self._read_queue = read_queue
        self._write_queue = write_queue
        self._receive_request_type = receive_request_type
        self._receive_notification_type = receive_notification_type
        self._read_timeout_seconds = read_timeout_seconds

        self._response_streams: dict[RequestId, "queue.Queue[JSONRPCResponse | JSONRPCError]"] = {}
        self._in_flight: dict[RequestId, RequestResponder[ReceiveRequestT, SendResultT]] = {}
        self._request_id = 0

        self._lock = threading.Lock()
        self._running = False
        self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)

    def start(self) -> None:
        self._running = True
        self._receive_thread.start()

    def close(self) -> None:
        self._running = False
        if self._receive_thread.is_alive():
            self._receive_thread.join()

    def send_request(
        self,
        request: SendRequestT,
        result_type: type[ReceiveResultT],
    ) -> ReceiveResultT:
        with self._lock:
            request_id = self._request_id
            self._request_id += 1

        response_queue: "queue.Queue[JSONRPCResponse | JSONRPCError]" = queue.Queue(maxsize=-1)
        self._response_streams[request_id] = response_queue

        jsonrpc_request = JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            **request.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        self._write_queue.put(JSONRPCMessage(jsonrpc_request))

        try:
            response_or_error = response_queue.get(
                timeout=None if self._read_timeout_seconds is None else self._read_timeout_seconds.total_seconds()
            )
        except queue.Empty:
            raise McpError(
                ErrorData(
                    code=408,
                    message=f"Timed out while waiting for response to {request.__class__.__name__}.",
                )
            )
        finally:
            del self._response_streams[request_id]

        if isinstance(response_or_error, JSONRPCError):
            raise McpError(response_or_error.error)
        else:
            return result_type.model_validate(response_or_error.result)

    def send_notification(self, notification: SendNotificationT) -> None:
        jsonrpc_notification = JSONRPCNotification(
            jsonrpc="2.0",
            **notification.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        self._write_queue.put(JSONRPCMessage(jsonrpc_notification))

    def _send_response(self, request_id: RequestId, response: SendResultT | ErrorData) -> None:
        if isinstance(response, ErrorData):
            jsonrpc_error = JSONRPCError(jsonrpc="2.0", id=request_id, error=response)
            self._write_queue.put(JSONRPCMessage(jsonrpc_error))
        else:
            jsonrpc_response = JSONRPCResponse(
                jsonrpc="2.0",
                id=request_id,
                result=response.model_dump(by_alias=True, mode="json", exclude_none=True),
            )
            self._write_queue.put(JSONRPCMessage(jsonrpc_response))

    def _receive_loop(self) -> None:
        while self._running:
            try:
                message = self._read_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if isinstance(message, Exception):
                self._handle_incoming(message)
            elif isinstance(message.root, JSONRPCRequest):
                validated_request = self._receive_request_type.model_validate(
                    message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                )
                responder = RequestResponder(
                    request_id=message.root.id,
                    request_meta=validated_request.root.params.meta if validated_request.root.params else None,
                    request=validated_request,
                    session=self,
                    on_complete=lambda r: self._in_flight.pop(r.request_id, None),
                )

                self._in_flight[responder.request_id] = responder
                self._received_request(responder)

                if not responder._completed:
                    self._handle_incoming(responder)

            elif isinstance(message.root, JSONRPCNotification):
                try:
                    notification = self._receive_notification_type.model_validate(
                        message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                    )
                    if isinstance(notification.root, CancelledNotification):
                        cancelled_id = notification.root.params.requestId
                        if cancelled_id in self._in_flight:
                            self._in_flight[cancelled_id].cancel()
                    else:
                        self._received_notification(notification)
                        self._handle_incoming(notification)
                except Exception as e:
                    logging.warning(
                        f"Failed to validate notification: {e}. "
                        f"Message was: {message.root}"
                    )
            else:  # Response or error
                stream = self._response_streams.get(message.root.id)
                if stream:
                    stream.put(message.root)
                else:
                    self._handle_incoming(
                        RuntimeError(
                            f"Received response with unknown request ID: {message}"
                        )
                    )
        print('Exiting loop')

    def _received_request(self, responder: RequestResponder[ReceiveRequestT, SendResultT]) -> None:
        """Override to handle incoming requests."""
        pass

    def _received_notification(self, notification: ReceiveNotificationT) -> None:
        """Override to handle incoming notifications."""
        pass

    def send_progress_notification(
        self, progress_token: Union[str, int], progress: float, total: float | None = None
    ) -> None:
        """Implement progress notification sending if needed."""
        pass

    def _handle_incoming(self, obj: Any) -> None:
        """Override to handle any incoming message."""
        pass
