import Foundation

// Everything written to the results JSON. Keys are encoded snake_case.
// Sizes are bytes, durations are seconds, unless a name says otherwise.

struct BenchReport: Codable {
    var schema = "digi-ios-bench/1"
    var id: String
    var status: String  // running | finished | aborted | failed | terminated
    var abortReason: String?
    var fallbackMessage: String?
    var startedAt: Date
    var finishedAt: Date?
    var device: DeviceInfo
    var runtime: RuntimeInfo
    var model: ModelInfo?
    var config: BenchConfig
    var load: LoadRecord?
    var reload: LoadRecord?
    var trials: [Trial] = []
    var events: [EventRecord] = []
    var summary: [SummaryRow] = []
}

struct DeviceInfo: Codable {
    var machine: String  // e.g. iPhone18,1
    var modelName: String?
    var systemName: String
    var systemVersion: String
    var osBuild: String?
    var physicalMemory: UInt64
    var processorCount: Int
    var gpuArchitecture: String?
    var gpuRecommendedWorkingSet: UInt64?
    var lowPowerMode: Bool
    var batteryLevel: Float?
    var batteryState: String
    var thermalStateAtStart: String
    var availableMemoryAtStart: Int  // os_proc_available_memory: what this process may still allocate
    var footprintAtStart: UInt64  // task_vm_info.phys_footprint
    var systemUptimeAtStart: Double  // small value = recently rebooted = truly cold file cache
    var networkAtStart: NetworkSnapshot
    var buildConfiguration: String
    var isSimulator: Bool
}

struct NetworkSnapshot: Codable {
    var status: String  // satisfied | unsatisfied | requiresConnection | unknown
    var interfaces: [String]
    var note: String
}

struct RuntimeInfo: Codable {
    var appVersion: String
    var packages: [String: String]  // from the bundled Package.resolved
    var mlxCacheLimit: Int
    var mlxMemoryLimit: Int
    var promptVersion: String
    var jsonFormat: String
}

struct ModelInfo: Codable {
    var repoId: String
    var revision: String?
    var configSha256: String?
    var weightsBytes: UInt64
    var location: String  // bundle | documents
    var path: String
}

struct BenchConfig: Codable {
    var preset: String
    var repeats: Int
    var sizes: [Int]
    var workloads: [String]
    var imageCase: String
    var cameraPauseResume: Bool
    var cameraPreset: String
    var reloadTest: Bool
    var cooldownSeconds: Double
    var maxTokens: [String: Int]
    var temperature: Double
    var memoryPrecheckBytes: Int
}

struct LoadRecord: Codable {
    var ok: Bool
    var error: String?
    var seconds: Double?
    var footprintBefore: UInt64
    var footprintAfter: UInt64
    var availableBefore: Int
    var availableAfter: Int
    var peakFootprint: UInt64
    var minAvailable: Int
    var mlxActiveAfter: Int
    var mlxPeak: Int
    var thermalState: String
    var camera: CameraCheck?
    var note: String?
}

struct Trial: Codable {
    var index: Int
    var workload: String  // decomposed | image_notes | target_scene
    var size: Int
    var firstAfterLoad: Bool
    var startedAt: Date
    var thermalStart: String
    var thermalEnd: String
    var camera: CameraCheck?
    var calls: [CallRecord] = []
    var inferenceSeconds: Double = 0  // sum of call e2e (what the user waits for)
    var wallSeconds: Double = 0  // whole trial incl. camera stop/start
    var peakFootprint: UInt64 = 0
    var minAvailable: Int = .max
    var mlxPeak: Int = 0
    var memoryWarnings: Int = 0
    var error: String?
}

struct CallRecord: Codable {
    var stage: String
    var image: String?
    var imagePixels: [Int]?
    var promptTokens: Int
    var generatedTokens: Int
    var maxTokens: Int
    var stopReason: String
    var prepareSeconds: Double  // image preprocessing + chat template + tokenize
    var prefillSeconds: Double  // GenerateCompletionInfo.promptTime
    var ttftSeconds: Double  // request start -> first generated token
    var decodeSeconds: Double  // GenerateCompletionInfo.generateTime
    var e2eSeconds: Double  // request start -> stream finished
    var promptTokensPerSecond: Double
    var generationTokensPerSecond: Double
    var peakFootprint: UInt64
    var minAvailable: Int
    var mlxPeak: Int
    var thermalStart: String
    var thermalEnd: String
    var jsonValid: Bool?
    var output: String
}

struct CameraCheck: Codable {
    var available: Bool
    var error: String?
    var availableWithCameraRunning: Int?
    var footprintWithCameraRunning: UInt64?
    var stopSeconds: Double?  // stopRunning() duration
    var startCallSeconds: Double?  // startRunning() duration
    var firstFrameSeconds: Double?  // start request -> first video frame delivered (capture recovery)
    var recovered: Bool?
}

struct EventRecord: Codable {
    var at: Date
    var secondsSinceStart: Double
    var kind: String  // thermal | memory_warning | camera_interrupted | camera_error | scene_phase | note
    var detail: String
    var footprint: UInt64
    var available: Int
}

struct SummaryRow: Codable {
    var workload: String
    var size: Int
    var n: Int
    var firstE2e: Double?
    var warmE2eMedian: Double?
    var warmE2eMax: Double?
    var ttftMedian: Double?  // over the calls of warm trials (first call of each trial for decomposed)
    var genTokPerSecMedian: Double?
    var promptTokPerSecMedian: Double?
    var peakFootprintMax: UInt64
    var minAvailableMin: Int
    var cameraRecoveryMedian: Double?
    var cameraRecoveryMax: Double?
    var jsonValid: String
}
