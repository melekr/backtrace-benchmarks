package io.backtrace.bench.app;

import java.io.IOException;
import java.net.InetAddress;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

/**
 * In-process HTTP mock bound to 127.0.0.1 (CONVENTIONS section 11). Answers every request under
 * /post and /api/* with a 200 JSON body and counts them. Started on a worker thread so the main
 * thread never touches a socket; the caller blocks only until the listening port is known.
 */
public final class MockServer {
    /** Fixed 64-hex token that satisfies the SDK's URL parsing; it is not a secret. */
    public static final String TOKEN = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private static final String OK_BODY = "{\"response\":\"ok\",\"_rxid\":\"bench\"}";

    private final MockWebServer server = new MockWebServer();
    private final AtomicInteger requests = new AtomicInteger();
    private final AtomicInteger unexpected = new AtomicInteger();
    private volatile int port = -1;

    public int start() throws IOException {
        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                requests.incrementAndGet();
                String path = request.getPath() == null ? "" : request.getPath();
                if (!(path.startsWith("/post") || path.startsWith("/api/"))) {
                    unexpected.incrementAndGet();
                }
                return new MockResponse()
                        .setResponseCode(200)
                        .setHeader("Content-Type", "application/json")
                        .setBody(OK_BODY);
            }
        });
        final CountDownLatch started = new CountDownLatch(1);
        final AtomicReference<IOException> failure = new AtomicReference<>();
        Thread t = new Thread(() -> {
            try {
                server.start(InetAddress.getByName("127.0.0.1"), 0);
                port = server.getPort();
            } catch (IOException e) {
                failure.set(e);
            } finally {
                started.countDown();
            }
        }, "bench-mock-start");
        t.start();
        try {
            started.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("interrupted while starting mock server", e);
        }
        if (failure.get() != null) {
            throw failure.get();
        }
        return port;
    }

    public int port() {
        return port;
    }

    public String baseUrl() {
        return "http://127.0.0.1:" + port;
    }

    /** Submission URL in the exact shape required by CONVENTIONS section 11. */
    public String submissionUrl() {
        return baseUrl() + "/post?format=json&token=" + TOKEN;
    }

    public String metricsBaseUrl() {
        return baseUrl() + "/api";
    }

    public int requestCount() {
        return requests.get();
    }

    public int unexpectedCount() {
        return unexpected.get();
    }
}
