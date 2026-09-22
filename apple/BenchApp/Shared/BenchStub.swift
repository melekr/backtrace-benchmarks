import Foundation
import Network

/// Minimal HTTP/1.1 stub bound to 127.0.0.1 on an ephemeral port.
///
/// Every request that arrives with a complete body is answered with
/// `200 {"response":"ok","_rxid":"bench"}` and counted. Nothing here ever
/// reaches the network: the listener is restricted to the IPv4 loopback address.
final class BenchStub {
    static let shared = BenchStub()

    private let queue = DispatchQueue(label: "io.backtrace.bench.stub")
    private let lock = NSLock()
    private var listener: NWListener?
    private var connections: [ObjectIdentifier: NWConnection] = [:]
    private var completedRequests = 0
    private var incompleteRequests = 0
    private(set) var port: UInt16 = 0
    private(set) var startError: String?

    /// Number of requests whose headers and full body were received and answered with 200.
    var requestCount: Int {
        lock.lock(); defer { lock.unlock() }
        return completedRequests
    }

    /// Connections that closed before a full request arrived (should stay 0).
    var incompleteCount: Int {
        lock.lock(); defer { lock.unlock() }
        return incompleteRequests
    }

    var isRunning: Bool { return port != 0 }

    /// Base URL to hand to the SDK as `endpoint`; the SDK appends `/post?format=plcrash&token=...`.
    var baseURL: URL {
        return URL(string: "http://127.0.0.1:\(port)")!
    }

    /// Starts the listener and blocks the caller until it is ready (or `timeout` elapses).
    @discardableResult
    func start(timeout: TimeInterval = 5) -> Bool {
        if listener != nil { return isRunning }
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true
        parameters.requiredLocalEndpoint = NWEndpoint.hostPort(host: .ipv4(.loopback), port: .any)
        let newListener: NWListener
        do {
            newListener = try NWListener(using: parameters)
        } catch {
            startError = "NWListener init failed: \(error)"
            return false
        }
        let ready = DispatchSemaphore(value: 0)
        var signalled = false
        newListener.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                self?.port = newListener.port?.rawValue ?? 0
                if !signalled { signalled = true; ready.signal() }
            case .failed(let error):
                self?.startError = "NWListener failed: \(error)"
                if !signalled { signalled = true; ready.signal() }
            case .cancelled:
                if !signalled { signalled = true; ready.signal() }
            default:
                break
            }
        }
        newListener.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
        listener = newListener
        newListener.start(queue: queue)
        if ready.wait(timeout: .now() + timeout) == .timedOut {
            startError = "NWListener did not become ready within \(timeout)s"
        }
        return isRunning
    }

    private func accept(_ connection: NWConnection) {
        let id = ObjectIdentifier(connection)
        lock.lock(); connections[id] = connection; lock.unlock()
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed, .cancelled:
                self?.forget(id)
            default:
                break
            }
        }
        connection.start(queue: queue)

        var buffer = Data()
        var expectedTotal: Int?

        func receiveMore() {
            connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] data, _, isComplete, error in
                guard let self = self else { return }
                if let data = data { buffer.append(data) }
                if expectedTotal == nil, let headerEnd = buffer.range(of: Data("\r\n\r\n".utf8)) {
                    let head = String(decoding: buffer[buffer.startIndex..<headerEnd.lowerBound], as: UTF8.self)
                    var contentLength = 0
                    for line in head.components(separatedBy: "\r\n") {
                        let parts = line.split(separator: ":", maxSplits: 1)
                        if parts.count == 2,
                           parts[0].trimmingCharacters(in: .whitespaces).lowercased() == "content-length" {
                            contentLength = Int(parts[1].trimmingCharacters(in: .whitespaces)) ?? 0
                        }
                    }
                    expectedTotal = (headerEnd.upperBound - buffer.startIndex) + contentLength
                }
                if let expected = expectedTotal, buffer.count >= expected {
                    self.respond(on: connection, id: id, complete: true)
                    return
                }
                if isComplete || error != nil {
                    self.respond(on: connection, id: id, complete: false)
                    return
                }
                receiveMore()
            }
        }
        receiveMore()
    }

    private func respond(on connection: NWConnection, id: ObjectIdentifier, complete: Bool) {
        lock.lock()
        if complete { completedRequests += 1 } else { incompleteRequests += 1 }
        lock.unlock()
        guard complete else {
            connection.cancel()
            return
        }
        let body = "{\"response\":\"ok\",\"_rxid\":\"bench\"}"
        let response = "HTTP/1.1 200 OK\r\n"
            + "Content-Type: application/json\r\n"
            + "Content-Length: \(body.utf8.count)\r\n"
            + "Connection: close\r\n\r\n"
            + body
        connection.send(content: Data(response.utf8), completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private func forget(_ id: ObjectIdentifier) {
        lock.lock(); connections.removeValue(forKey: id); lock.unlock()
    }
}
