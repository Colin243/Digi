import Foundation

func check(_ value: @autoclosure () -> Bool, _ message: String) {
    if !value() { fatalError(message) }
}
var timer = ShutterCountdown()
check(timer.begin(seconds: 3), "Countdown should start")
check(!timer.begin(seconds: 10), "Repeated shutter press must not restart an active countdown")
check(timer.remaining == 3, "Initial countdown must be visible")
check(!timer.advance(), "Must not capture at two seconds")
check(!timer.advance(), "Must not capture at one second")
check(timer.advance(), "Must capture when countdown completes")
check(!timer.advance(), "Must capture only once")
check(timer.remaining == nil, "Completed timer should clear")
check(timer.begin(seconds: 10), "Should start another countdown")
timer.cancel()
check(!timer.advance(), "Cancellation must prevent capture")
check(timer.begin(seconds: 3), "Should restart after cancellation")
timer.cancel()
check(!timer.begin(seconds: -1), "Invalid delays must be rejected")
print("Countdown completion, duplicate presses, cancellation, and restart passed")
