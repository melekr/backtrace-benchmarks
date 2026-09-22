import Foundation
import Darwin

/// Monotonic clock helpers based on mach_absolute_time (the same clock XCTClockMetric uses).
enum BenchClock {
    private static let timebase: mach_timebase_info_data_t = {
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        return info
    }()

    static func now() -> UInt64 {
        return mach_absolute_time()
    }

    static func nanoseconds(from start: UInt64, to end: UInt64) -> Double {
        let elapsed = end >= start ? end - start : 0
        return Double(elapsed) * Double(timebase.numer) / Double(timebase.denom)
    }

    static func milliseconds(from start: UInt64, to end: UInt64) -> Double {
        return nanoseconds(from: start, to: end) / 1_000_000.0
    }

    static func microseconds(from start: UInt64, to end: UInt64) -> Double {
        return nanoseconds(from: start, to: end) / 1_000.0
    }
}

/// Process and device counters sampled by the benchmark apps.
enum BenchProcess {
    /// Number of threads in this task, via task_threads. Returns -1 when the Mach call fails.
    static func threadCount() -> Int {
        var list: thread_act_array_t?
        var count: mach_msg_type_number_t = 0
        guard task_threads(mach_task_self_, &list, &count) == KERN_SUCCESS else { return -1 }
        if let list = list {
            for index in 0..<Int(count) {
                mach_port_deallocate(mach_task_self_, list[index])
            }
            let size = vm_size_t(Int(count) * MemoryLayout<thread_t>.stride)
            vm_deallocate(mach_task_self_, vm_address_t(bitPattern: list), size)
        }
        return Int(count)
    }

    static func sysctlString(_ name: String) -> String {
        var size = 0
        sysctlbyname(name, nil, &size, nil, 0)
        guard size > 0 else { return "" }
        var buffer = [CChar](repeating: 0, count: size)
        sysctlbyname(name, &buffer, &size, nil, 0)
        return String(cString: buffer)
    }

    static func fileSize(at url: URL) -> Int? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attrs[.size] as? NSNumber else { return nil }
        return size.intValue
    }
}
