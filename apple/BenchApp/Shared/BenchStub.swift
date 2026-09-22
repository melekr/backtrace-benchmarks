import Foundation
import Network

/// Minimal HTTP/1.1 stub bound to 127.0.0.1 on an ephemeral port.
///
/// Every request whose headers and complete body arrive (`Content-Length` or `Transfer-Encoding: chunked`) is
/// answered with `200 {"response":"ok","_rxid":"bench"}` and counted. `Expect: 100-continue` gets its interim
/// reply. A connection that stays silent for `idleTimeout` before its request is complete is dropped and counted
/// as incomplete, so a stalled client cannot hang a lane. Responses end with a graceful close (FIN after the data,
/// cancel once the peer closes), never an abortive reset. Nothing here ever reaches the network: the listener is
/// restricted to the IPv4 loopback address.
final class BenchStub {
    static let shared = BenchStub()
    /// Silence on a connection for this long before its request is complete counts as an incomplete request.
    static let idleTimeout: TimeInterval = 30

    private let queue = DispatchQueue(label: "io.backtrace.bench.stub")
    private let lock = NSLock()
    private var listener: NWListener?
    private var connections: [ObjectIdentifier: NWConnection] = [:]
    private var completedRequests = 0
    private var incompleteRequests = 0
    private var idleTimeouts = 0
    private var chunkedRequests = 0
    private var continueReplies = 0
    private(set) var port: UInt16 = 0
    private(set) var startError: String?

    /// Number of requests whose headers and full body were received and answered with 200.
    var requestCount: Int {
        lock.lock(); defer { lock.unlock() }
        return completedRequests
    }

    /// Connections that closed, errored or went idle before a full request arrived (should stay 0).
    var incompleteCount: Int {
        lock.lock(); defer { lock.unlock() }
        return incompleteRequests
    }

    /// Subset of `incompleteCount` dropped by the idle timeout.
    var idleTimeoutCount: Int {
        lock.lock(); defer { lock.unlock() }
        return idleTimeouts
    }

    /// Completed requests that used chunked transfer encoding.
    var chunkedCount: Int {
        lock.lock(); defer { lock.unlock() }
        return chunkedRequests
    }

    /// Interim `100 Continue` replies sent.
    var continueCount: Int {
        lock.lock(); defer { lock.unlock() }
        return continueReplies
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

    // MARK: - Per-connection request parsing (everything below runs on `queue`)

    /// Parser state of one inbound connection.
    private final class Inbound {
        var buffer = Data()
        var bodyStart: Int?
        var contentLength: Int?
        var chunked = false
        var expectsContinue = false
        var continueSent = false
        var finished = false
        var idleTimer: DispatchWorkItem?
    }

    private enum Progress {
        case needMore
        case complete
        case malformed
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
        let inbound = Inbound()
        armIdleTimer(inbound, connection)
        receiveMore(inbound, connection)
    }

    /// (Re)starts the idle timer; firing drops the connection and counts an incomplete request.
    private func armIdleTimer(_ inbound: Inbound, _ connection: NWConnection) {
        inbound.idleTimer?.cancel()
        let timer = DispatchWorkItem { [weak self] in
            guard let self = self, !inbound.finished else { return }
            inbound.finished = true
            self.lock.lock()
            self.incompleteRequests += 1
            self.idleTimeouts += 1
            self.lock.unlock()
            connection.cancel()
        }
        inbound.idleTimer = timer
        queue.asyncAfter(deadline: .now() + BenchStub.idleTimeout, execute: timer)
    }

    private func receiveMore(_ inbound: Inbound, _ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] data, _, isComplete, error in
            guard let self = self, !inbound.finished else { return }
            if let data = data, !data.isEmpty {
                inbound.buffer.append(data)
                self.armIdleTimer(inbound, connection)
            }
            switch self.progress(inbound) {
            case .complete:
                self.finish(inbound, connection, complete: true)
                return
            case .malformed:
                self.finish(inbound, connection, complete: false)
                return
            case .needMore:
                break
            }
            if inbound.expectsContinue && !inbound.continueSent {
                inbound.continueSent = true
                self.lock.lock(); self.continueReplies += 1; self.lock.unlock()
                connection.send(content: Data("HTTP/1.1 100 Continue\r\n\r\n".utf8), completion: .idempotent)
            }
            if isComplete || error != nil {
                self.finish(inbound, connection, complete: false)
                return
            }
            self.receiveMore(inbound, connection)
        }
    }

    /// Parses the head once it has fully arrived, then reports whether the body is complete.
    private func progress(_ inbound: Inbound) -> Progress {
        let buffer = inbound.buffer
        if inbound.bodyStart == nil {
            guard let headerEnd = buffer.range(of: Data("\r\n\r\n".utf8)) else { return .needMore }
            let head = String(decoding: buffer[buffer.startIndex..<headerEnd.lowerBound], as: UTF8.self)
            for line in head.components(separatedBy: "\r\n").dropFirst() {   // the first line is the request line
                guard let colon = line.firstIndex(of: ":") else { continue }
                let name = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
                let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces).lowercased()
                switch name {
                case "content-length":
                    inbound.contentLength = Int(value)
                case "transfer-encoding":
                    if value.contains("chunked") { inbound.chunked = true }
                case "expect":
                    if value == "100-continue" { inbound.expectsContinue = true }
                default:
                    break
                }
            }
            inbound.bodyStart = headerEnd.upperBound
        }
        guard let bodyStart = inbound.bodyStart else { return .needMore }
        if inbound.chunked {
            return BenchStub.chunkedProgress(buffer, from: bodyStart)
        }
        return buffer.endIndex - bodyStart >= (inbound.contentLength ?? 0) ? .complete : .needMore
    }

    /// Walks chunk-size lines from `start`; complete once the zero-size chunk and its trailer CRLF have arrived.
    private static func chunkedProgress(_ buffer: Data, from start: Int) -> Progress {
        let crlf = Data("\r\n".utf8)
        var pos = start
        while true {
            guard pos <= buffer.endIndex, let lineEnd = buffer.range(of: crlf, in: pos..<buffer.endIndex) else {
                return .needMore
            }
            let sizeField = String(decoding: buffer[pos..<lineEnd.lowerBound], as: UTF8.self)
            let hex = sizeField.split(separator: ";", maxSplits: 1).first.map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
            guard let size = Int(hex, radix: 16) else { return .malformed }
            if size == 0 {
                // Optional trailer fields, then an empty line.
                let terminated = buffer.range(of: Data("\r\n\r\n".utf8), in: lineEnd.lowerBound..<buffer.endIndex) != nil
                return terminated ? .complete : .needMore
            }
            pos = lineEnd.upperBound + size + 2
        }
    }

    private func finish(_ inbound: Inbound, _ connection: NWConnection, complete: Bool) {
        inbound.finished = true
        inbound.idleTimer?.cancel()
        lock.lock()
        if complete {
            completedRequests += 1
            if inbound.chunked { chunkedRequests += 1 }
        } else {
            incompleteRequests += 1
        }
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
        // Graceful close: the response is the final message (FIN follows the data) and the socket is cancelled once
        // the peer closes, or after five seconds. Cancelling straight after `.contentProcessed` can reset the
        // connection before the client has read the response, which the SDK then treats as a transport failure.
        connection.send(content: Data(response.utf8), contentContext: .finalMessage, isComplete: true,
                        completion: .contentProcessed { [weak self] _ in
            guard let self = self else {
                connection.cancel()
                return
            }
            self.queue.asyncAfter(deadline: .now() + 5) { connection.cancel() }
            self.drainUntilPeerCloses(connection)
        })
    }

    private func drainUntilPeerCloses(_ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] _, _, isComplete, error in
            if isComplete || error != nil {
                connection.cancel()
                return
            }
            self?.drainUntilPeerCloses(connection)
        }
    }

    private func forget(_ id: ObjectIdentifier) {
        lock.lock(); connections.removeValue(forKey: id); lock.unlock()
    }
}
