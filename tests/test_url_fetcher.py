from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx
from pydantic import HttpUrl

from parser_serve.backends import BackendExecutionError
from parser_serve.worker.url_fetcher import fetch_url_source, validate_source_url


async def public_resolver(_: str, __: int) -> set[str]:
    return {"93.184.216.34"}


class UrlSourceFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_private_and_mixed_dns_results(self) -> None:
        with self.assertRaisesRegex(BackendExecutionError, "non-public"):
            await validate_source_url(HttpUrl("http://127.0.0.1/page"))

        async def mixed(_: str, __: int) -> set[str]:
            return {"93.184.216.34", "10.0.0.8"}

        with self.assertRaisesRegex(BackendExecutionError, "non-public"):
            await validate_source_url(
                HttpUrl("https://example.com/page"),
                resolver=mixed,
            )

    async def test_fetches_bounded_html_without_following_client_redirects(
        self,
    ) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(
                    302,
                    headers={"Location": "/final"},
                )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                content=b"<html><body>safe</body></html>",
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
        try:
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "page.html"
                result = await fetch_url_source(
                    HttpUrl("https://example.com/start"),
                    destination,
                    maximum_bytes=1024,
                    timeout_seconds=5,
                    maximum_redirects=2,
                    resolver=public_resolver,
                    client=client,
                )
                self.assertEqual(result.read_text(), "<html><body>safe</body></html>")
        finally:
            await client.aclose()
        self.assertEqual(
            requests,
            [
                "https://example.com/start",
                "https://example.com/final",
            ],
        )

    async def test_revalidates_redirect_target_and_rejects_downgrade(self) -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    302,
                    headers={"Location": "http://127.0.0.1/internal"},
                )
            ),
            follow_redirects=False,
        )
        try:
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(
                    BackendExecutionError,
                    "HTTPS to HTTP",
                ):
                    await fetch_url_source(
                        HttpUrl("https://example.com/start"),
                        Path(temporary) / "page.html",
                        maximum_bytes=1024,
                        timeout_seconds=5,
                        maximum_redirects=2,
                        resolver=public_resolver,
                        client=client,
                    )
        finally:
            await client.aclose()

    async def test_rejects_unsupported_or_oversized_responses(self) -> None:
        for response, message in [
            (
                httpx.Response(
                    200,
                    headers={"Content-Type": "application/octet-stream"},
                    content=b"data",
                ),
                "content type",
            ),
            (
                httpx.Response(
                    200,
                    headers={"Content-Type": "text/html"},
                    content=b"x" * 20,
                ),
                "size limit",
            ),
        ]:
            client = httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: response),
            )
            try:
                with tempfile.TemporaryDirectory() as temporary:
                    destination = Path(temporary) / "page.html"
                    with self.assertRaisesRegex(BackendExecutionError, message):
                        await fetch_url_source(
                            HttpUrl("https://example.com/page"),
                            destination,
                            maximum_bytes=10,
                            timeout_seconds=5,
                            maximum_redirects=0,
                            resolver=public_resolver,
                            client=client,
                        )
                    self.assertFalse(destination.exists())
            finally:
                await client.aclose()

    async def test_rejects_html_header_with_binary_content_and_removes_file(
        self,
    ) -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"Content-Type": "text/html"},
                    content=b"%PDF-1.7\n",
                )
            )
        )
        try:
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "page.html"
                with self.assertRaisesRegex(BackendExecutionError, "signature"):
                    await fetch_url_source(
                        HttpUrl("https://example.com/page"),
                        destination,
                        maximum_bytes=1024,
                        timeout_seconds=5,
                        maximum_redirects=0,
                        resolver=public_resolver,
                        client=client,
                    )
                self.assertFalse(destination.exists())
        finally:
            await client.aclose()


if __name__ == "__main__":
    unittest.main()
