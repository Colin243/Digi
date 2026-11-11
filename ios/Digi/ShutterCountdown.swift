// Pure countdown state; the view supplies time and owns the cancellable task.
struct ShutterCountdown {
    private(set) var remaining: Int?

    mutating func begin(seconds: Int) -> Bool {
        guard remaining == nil, seconds > 0 else { return false }
        remaining = seconds
        return true
    }

    mutating func advance() -> Bool {
        guard let remaining else { return false }
        if remaining > 1 {
            self.remaining = remaining - 1
            return false
        }
        self.remaining = nil
        return true
    }

    mutating func cancel() { remaining = nil }
}
