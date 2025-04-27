import logging
import threading
import queue
from urllib.parse import urljoin, urlparse
import httpx
from httpx_sse import connect_sse

import mcp.types as types

logger = logging.getLogger(__name__)

def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)

class SSEClient:
    def __init__(self, url: str, headers: dict = None, timeout: float = 5, sse_read_timeout: float = 60 * 5):
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout
        self.read_queue = queue.Queue(-1)
        self.write_queue = queue.Queue(-1)
        self._client = None
        self._reader_thread = None  # to keep track of the reader thread
        self._writer_thread = None  # to keep track of the writer thread
        self._sse_connection = None

    def _sse_reader(self, event_source, task_status):
        try:
            logger.info(f'SSE reader active')
            for sse in event_source.iter_sse():
                logger.debug(f"Received SSE event: {sse.event}")
                if sse.event == "endpoint":
                    endpoint_url = urljoin(self.url, sse.data)
                    logger.info(f"Received endpoint URL: {endpoint_url}")

                    url_parsed = urlparse(self.url)
                    endpoint_parsed = urlparse(endpoint_url)
                    if (
                        url_parsed.netloc != endpoint_parsed.netloc
                        or url_parsed.scheme != endpoint_parsed.scheme
                    ):
                        error_msg = (
                            f"Endpoint origin does not match connection origin: {endpoint_url}"
                        )
                        logger.error(error_msg)
                        raise ValueError(error_msg)

                    task_status.put(endpoint_url)

                elif sse.event == "message":
                    try:
                        message = types.JSONRPCMessage.model_validate_json(sse.data)
                        logger.debug(f"Received server message: {message}")
                    except Exception as exc:
                        logger.error(f"Error parsing server message: {exc}")
                        self.read_queue.put(exc)
                        continue

                    self.read_queue.put(message)
                else:
                    logger.warning(f"Unknown SSE event: {sse.event}")
        except Exception as exc:
            logger.error(f"Error in sse_reader: {exc}")
            self.read_queue.put(exc)
        finally:
            logger.debug('Read queue is closed')
            self.read_queue.put(None)  # to signal completion

    def _post_writer(self, endpoint_url: str, ready_event=None):
        try:
            if ready_event:
                ready_event.set()  # Signal that the writer is ready
            while (message := self.write_queue.get()):
                logger.debug(f"Sending client message: {message}")
                response = self._client.post(
                    endpoint_url,
                    json=message.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
                response.raise_for_status()
                logger.debug(f"Client message sent successfully: {response.status_code}")
        except Exception as exc:
            logger.error(f"Error in post_writer: {exc}")
        finally:
            logger.warning("Writer thread is exiting.")
            self.write_queue.put(None)  # to signal completion

    def connect(self):
        self._client = httpx.Client(headers=self.headers)
        try:
            logger.info(f"Connecting to SSE endpoint: {remove_request_params(self.url)}")
            self._sse_connection = connect_sse(self._client, "GET", self.url, timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout))
            event_source = self._sse_connection.__enter__()
            event_source.response.raise_for_status()
            logger.debug("SSE connection established")

            task_status = queue.Queue()
            self._reader_thread = threading.Thread(target=self._sse_reader, args=(event_source, task_status), daemon=True)
            self._reader_thread.start()

            endpoint_url = task_status.get()  # Block until the endpoint URL is received
            logger.info(f"Starting post writer with endpoint URL: {endpoint_url}")
            
            writer_ready = threading.Event()
            self._writer_thread = threading.Thread(target=self._post_writer, args=(endpoint_url, writer_ready), daemon=True)
            self._writer_thread.start()
                # Wait for writer to be ready
            writer_ready.wait()
            logger.info(f"Post writer ready")

            return self.read_queue, self.write_queue
        except Exception as exc:
            logger.error(f"Error connecting to SSE: {exc}")
            raise
            
    def disconnect(self):
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.info("HTTP client closed.")
        # Ensure both threads are joined before closing
        if self._reader_thread:
            self._reader_thread.join()
            logger.info("Reader thread has completed.")
        
        if self._writer_thread:
            self._writer_thread.join()
            logger.info("Writer thread has completed.")
        
        if self._sse_connection:
            self._sse_connection.__exit__()
            self._sse_connection = None


if __name__ == "__main__":
    sse_client = SSEClient(url="http://0.0.0.0:8000/sse")
    read_stream, write_stream = sse_client.connect()

    try:
        while True:
            msg = read_stream.get()
            if msg is None:
                break
            logger.info(f"Received message: {msg}")
    except KeyboardInterrupt:
        logger.info("Shutting down client.")
