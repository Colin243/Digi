import AppKit
import WebKit

struct Configuration: Decodable {
    let sourceRoot: String
    let pythonExecutable: String
    let dataRoots: [String]
    let port: Int
}

final class Observatory: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var config: Configuration!
    var configURL: URL!
    var server: Process?
    var logHandle: FileHandle?
    var logURL: URL?
    var attempt = UUID()
    var quitting = false
    var displayMode = true
    var restoringFrame = true
    var inFullScreen = false
    let savedFrameKey = "DigiObservatoryWindowPlacement"
    var monitorLoaded = false
    var hasLoadedLocalPage = false
    var crashRecoveryAttempted = false
    let session: URLSession = {
        let options = URLSessionConfiguration.ephemeral
        options.timeoutIntervalForRequest = 1
        options.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: options)
    }()
    var baseURL: URL { URL(string: "http://127.0.0.1:\(config.port)/")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
        NSApp.applicationIconImage = NSImage(systemSymbolName: "network", accessibilityDescription: "Digi Observatory")
        let settings = WKWebViewConfiguration()
        settings.userContentController.add(self, name: "digi")
        web = WKWebView(frame: .zero, configuration: settings)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.underPageBackgroundColor = NSColor(calibratedWhite: 0.035, alpha: 1)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Digi Observatory"
        window.backgroundColor = NSColor(calibratedWhite: 0.035, alpha: 1)
        window.contentMinSize = NSSize(width: 360, height: 320)
        window.collectionBehavior.insert(.fullScreenPrimary)
        window.contentView = web
        window.delegate = self
        restoreWindowPlacement()
        makeMenu()
        window.makeKeyAndOrderFront(nil)
        restoringFrame = false
        NSApp.activate(ignoringOtherApps: true)
        connect()
    }

    func makeMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Digi Observatory", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem()
        menu.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        editItem.submenu = edit
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        let viewItem = NSMenuItem()
        menu.addItem(viewItem)
        let view = NSMenu(title: "View")
        viewItem.submenu = view
        for (title, action, key) in [("Network Display", #selector(showDisplay), "1"),
                                      ("Dashboard", #selector(showDashboard), "2"),
                                      ("Refresh Data", #selector(refreshData), "r"),
                                      ("Retry Connection", #selector(retry), "")] {
            let item = view.addItem(withTitle: title, action: action, keyEquivalent: key)
            item.target = self
        }
        view.addItem(.separator())
        let full = view.addItem(withTitle: "Toggle Full Screen", action: #selector(fullscreen), keyEquivalent: "f")
        full.keyEquivalentModifierMask = [.command, .control]
        full.target = self
        NSApp.mainMenu = menu
    }

    @objc func showDisplay() { setDisplay(true) }
    @objc func showDashboard() { setDisplay(false) }
    func setDisplay(_ enabled: Bool) {
        displayMode = enabled
        guard let url = web.url, isLocal(url) else { return }
        web.evaluateJavaScript("window.DigiDisplay?.set(\(enabled ? "true" : "false"))")
    }
    @objc func fullscreen() { window.toggleFullScreen(nil) }
    @objc func refreshData() {
        if hasLoadedLocalPage, let url = web.url, isLocal(url) {
            web.evaluateJavaScript("window.DigiMonitor?.refresh?.()")
        } else {
            connect()
        }
    }
    @objc func retry() { crashRecoveryAttempted = false; connect() }

    func connect() {
        monitorLoaded = false
        attempt = UUID()
        let token = attempt
        do {
            guard let url = Bundle.main.url(forResource: "config", withExtension: "json") else {
                throw NSError(domain: "Digi", code: 1, userInfo: [NSLocalizedDescriptionKey: "config.json is missing. Rebuild this app with macos/build.py."])
            }
            configURL = url
            config = try JSONDecoder().decode(Configuration.self, from: Data(contentsOf: url))
            guard (1024...65535).contains(config.port) else {
                throw NSError(domain: "Digi", code: 2, userInfo: [NSLocalizedDescriptionKey: "Set a port between 1024 and 65535 in \(url.path)."])
            }
        } catch { showError(error.localizedDescription); return }
        probe { healthy, occupied in
            guard token == self.attempt, !self.quitting else { return }
            if healthy { self.loadMonitor(); return }
            if occupied { self.showError("Port \(self.config.port) is responding, but it is not a healthy Digi monitor. Quit that service or change the port in \(self.configURL.path)."); return }
            do {
                if self.server?.isRunning != true { try self.startServer() }
                self.waitForServer(token: token, deadline: Date().addingTimeInterval(15))
            } catch { self.showError(error.localizedDescription) }
        }
    }

    func probe(_ completion: @escaping (Bool, Bool) -> Void) {
        let url = baseURL.appendingPathComponent("api/runs")
        session.dataTask(with: url) { data, response, error in
            let http = response as? HTTPURLResponse
            let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            let healthy = http?.statusCode == 200 && json?["runs"] is [Any]
            DispatchQueue.main.async { completion(healthy, http != nil) }
        }.resume()
    }

    func startServer() throws {
        guard FileManager.default.isExecutableFile(atPath: config.pythonExecutable) else {
            throw NSError(domain: "Digi", code: 3, userInfo: [NSLocalizedDescriptionKey: "Configured Python is missing or not executable:\n\(config.pythonExecutable)\n\nRebuild with --python pointing to your existing photography-ai environment, or edit \(configURL.path)."])
        }
        guard FileManager.default.fileExists(atPath: config.sourceRoot + "/src/photo_ai/training/monitor/server.py") else {
            throw NSError(domain: "Digi", code: 4, userInfo: [NSLocalizedDescriptionKey: "The photography-ai checkout is missing at \(config.sourceRoot). Rebuild with --source-root or update config.json."])
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: config.pythonExecutable)
        process.arguments = [Bundle.main.url(forResource: "MonitorServer", withExtension: "py")!.path, configURL.path]
        process.currentDirectoryURL = URL(fileURLWithPath: config.sourceRoot)
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        logURL = FileManager.default.temporaryDirectory.appendingPathComponent("digi-observatory-\(UUID().uuidString).log")
        FileManager.default.createFile(atPath: logURL!.path, contents: nil, attributes: [.posixPermissions: 0o600])
        logHandle = try FileHandle(forWritingTo: logURL!)
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting, self.server === process else { return }
                self.server = nil
                try? self.logHandle?.close()
                self.logHandle = nil
                // Startup failures are handled by the existing bounded startup poll.
                guard self.monitorLoaded else { return }
                self.monitorLoaded = false
                if !self.crashRecoveryAttempted {
                    self.crashRecoveryAttempted = true
                    self.connect()
                } else {
                    self.showError("The local monitor stopped again after an automatic restart. Check its Python environment and log, then choose Retry.\n\nServer log: \(self.logURL?.path ?? "unavailable")")
                }
            }
        }
        try process.run()
        server = process
    }

    func waitForServer(token: UUID, deadline: Date) {
        probe { healthy, _ in
            guard token == self.attempt, !self.quitting else { return }
            if healthy { self.loadMonitor(); return }
            if Date() >= deadline || self.server?.isRunning != true {
                self.stopOwnedServer()
                self.showError("The local monitor could not start within 15 seconds. Check the Python environment, checkout and port \(self.config.port).\n\nServer log: \(self.logURL?.path ?? "unavailable")")
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.waitForServer(token: token, deadline: deadline) }
        }
    }

    func loadMonitor() {
        monitorLoaded = true
        if hasLoadedLocalPage, let current = web.url, isLocal(current) {
            // Recovery refreshes data in place; retain camera, mode and selected run.
            // Older monitor pages without this API resume their regular polling.
            web.evaluateJavaScript("window.DigiMonitor?.refresh?.()")
            updateVisibility()
            return
        }
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        if let current = web.url, isLocal(current) {
            // The page owns run selection and display state through history.replaceState.
            // Reconnect to that state, including an intentionally absent display query.
            components.queryItems = URLComponents(url: current, resolvingAgainstBaseURL: false)?.queryItems
        } else if displayMode {
            components.queryItems = [URLQueryItem(name: "display", value: "network")]
        }
        web.load(URLRequest(url: components.url!))
    }

    func showError(_ detail: String) {
        // A loaded monitor already presents its inline offline state. Runtime
        // failures must not interrupt other work with sheets or focus changes.
        if hasLoadedLocalPage {
            NSLog("Digi Observatory connection: %@", detail)
            return
        }
        let alert = NSAlert()
        alert.messageText = "Digi Observatory could not connect"
        alert.informativeText = detail
        alert.addButton(withTitle: "Retry")
        alert.addButton(withTitle: "Quit")
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn { self.retry() } else { NSApp.terminate(nil) }
        }
    }

    func isLocal(_ url: URL) -> Bool {
        config != nil && url.scheme == "http" && url.host == "127.0.0.1" && url.port == config.port && url.user == nil && url.password == nil
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if isLocal(url), navigationAction.targetFrame?.isMainFrame == true { decisionHandler(.allow); return }
        if navigationAction.navigationType == .linkActivated,
           navigationAction.sourceFrame.isMainFrame,
           let source = navigationAction.sourceFrame.request.url, isLocal(source),
           ["https", "http"].contains(url.scheme ?? ""), !isLocal(url) {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              let url = message.frameInfo.request.url, isLocal(url),
              let body = message.body as? [String: Any], body["action"] as? String == "toggleFullscreen" else { return }
        fullscreen()
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, isLocal(url) { hasLoadedLocalPage = true }
        updateVisibility()
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showError("\(error.localizedDescription)\nUse Retry to reconnect to the local monitor.") }
    }
    func updateVisibility() {
        let visible = !window.isMiniaturized && window.occlusionState.contains(.visible)
        web.evaluateJavaScript("window.DigiDisplay?.setVisible(\(visible ? "true" : "false"))")
    }
    func screenNumber(_ screen: NSScreen) -> Double? {
        (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.doubleValue
    }
    func restoreWindowPlacement() {
        guard let saved = UserDefaults.standard.dictionary(forKey: savedFrameKey) as? [String: Double],
              let x = saved["x"], let y = saved["y"], let width = saved["width"], let height = saved["height"],
              [x, y, width, height].allSatisfy({ $0.isFinite }), width > 0, height > 0 else {
            window.center()
            return
        }
        let matchingScreen = NSScreen.screens.first { screenNumber($0) == saved["screenID"] }
        guard let screen = matchingScreen ?? NSScreen.main ?? NSScreen.screens.first else {
            window.center()
            return
        }
        let visible = screen.visibleFrame
        var frame = NSRect(x: x, y: y, width: width, height: height)
        // Keep the same relative placement if the monitor arrangement has changed.
        if matchingScreen != nil {
            frame.origin.x += screen.frame.minX - (saved["screenX"] ?? screen.frame.minX)
            frame.origin.y += screen.frame.minY - (saved["screenY"] ?? screen.frame.minY)
        }
        frame.size.width = min(frame.width, visible.width)
        frame.size.height = min(frame.height, visible.height)
        frame.origin.x = max(visible.minX, min(frame.minX, visible.maxX - frame.width))
        frame.origin.y = max(visible.minY, min(frame.minY, visible.maxY - frame.height))
        // Explicit setFrame preserves valid negative coordinates on external displays;
        // AppKit's setFrameUsingName can instead transfer them to the main display.
        window.setFrame(frame, display: false)
    }
    func saveWindowPlacement() {
        guard !restoringFrame, !inFullScreen, !window.isMiniaturized,
              let screen = window.screen, let number = screenNumber(screen) else { return }
        let frame = window.frame
        UserDefaults.standard.set([
            "x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height,
            "screenID": number, "screenX": screen.frame.minX, "screenY": screen.frame.minY
        ], forKey: savedFrameKey)
    }
    func windowDidMove(_ notification: Notification) { saveWindowPlacement() }
    func windowDidResize(_ notification: Notification) { saveWindowPlacement() }
    func windowDidChangeScreen(_ notification: Notification) { saveWindowPlacement() }
    func windowWillEnterFullScreen(_ notification: Notification) {
        saveWindowPlacement()
        inFullScreen = true
    }
    func windowDidExitFullScreen(_ notification: Notification) {
        inFullScreen = false
        saveWindowPlacement()
    }
    func windowDidChangeOcclusionState(_ notification: Notification) { updateVisibility() }
    func windowDidMiniaturize(_ notification: Notification) { updateVisibility() }
    func windowDidDeminiaturize(_ notification: Notification) { updateVisibility() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func stopOwnedServer() {
        if let process = server, process.isRunning { process.terminate() }
        server = nil
        try? logHandle?.close()
        logHandle = nil
    }
    func applicationWillTerminate(_ notification: Notification) {
        saveWindowPlacement()
        quitting = true
        attempt = UUID()
        session.invalidateAndCancel()
        stopOwnedServer()
    }
}

let application = NSApplication.shared
let delegate = Observatory()
application.setActivationPolicy(.regular)
application.delegate = delegate
application.run()
