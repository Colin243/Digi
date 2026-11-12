import Foundation
import MLX

// One decomposed analysis with the same prompts, images and code path as the phone app.
//   MacSmoke <ios-bench/Resources> [size=1024] [repeats=1]

func now() -> Double { CFAbsoluteTimeGetCurrent() }

let args = CommandLine.arguments
guard args.count >= 2 else {
    print("usage: MacSmoke <path to ios-bench/Resources> [size] [repeats]")
    exit(2)
}
let res = URL(fileURLWithPath: args[1])
let size = args.count > 2 ? Int(args[2]) ?? 1024 : 1024
let repeats = args.count > 3 ? Int(args[3]) ?? 1 : 1

let pack = try PromptPack.load(url: res.appendingPathComponent("prompts.json"))
let (manifest, imgDir) = try ImageManifest.load(dir: res.appendingPathComponent("BenchImages"))
let host = ModelHost()
print("prompt v\(pack.promptVersion) (\(pack.jsonFormat)), case \(manifest.case), \(size) px")

var t0 = now()
try await host.load(from: res.appendingPathComponent("Model"))
print(String(format: "load %.2f s, MLX active %.2f GB", now() - t0, Double(Memory.activeMemory) / 1e9))

func img(_ role: String, _ i: Int) -> URL {
    imgDir.appendingPathComponent(manifest.variant(role: role, index: i, size: size)!.file)
}

func call(_ stage: String, _ prompt: String, _ image: URL?, _ maxTokens: Int) async throws -> String {
    Memory.peakMemory = 0
    let r = try await host.run(template: prompt, marker: pack.imageMarker, image: image, maxTokens: maxTokens)
    print(String(format: "  %-22@ prompt %5d tok  gen %4d tok (%@)  prep %.2f  prefill %.2f  ttft %.2f  e2e %6.2f s  %5.1f tok/s  peak %.2f GB",
                 stage, r.promptTokens, r.generatedTokens, r.stopReason, r.prepare, r.prefill, r.ttft, r.e2e, r.genTPS,
                 Double(Memory.peakMemory) / 1e9))
    return r.text
}

for rep in 1...repeats {
    print("analysis \(rep):")
    t0 = now()
    var notes: [String] = []
    let notesStage = try pack.stage("image_notes")
    for i in 1...manifest.inspirationCount {
        notes.append(try await call("notes_inspiration\(i)", notesStage.prompt, img("inspiration", i), notesStage.maxTokens))
    }
    let ts = try pack.stage("target_scene")
    let target = try await call("target_scene", ts.prompt, img("target", 1), ts.maxTokens)
    let aesthetic = try await call("aesthetic_from_notes", try pack.aestheticPrompt(notes: notes), nil,
                                   try pack.stage("aesthetic_from_notes").maxTokens)
    let comps = try await call("compositions", try pack.compositionsPrompt(aestheticRaw: aesthetic, targetRaw: target),
                               img("target", 1), try pack.stage("compositions").maxTokens)
    print(String(format: "  total %.1f s; JSON valid: target %@, aesthetic %@, compositions %@", now() - t0,
                 "\(JSONText.isValid(target))", "\(JSONText.isValid(aesthetic))", "\(JSONText.isValid(comps))"))
    if rep == repeats {
        print("--- note 1 ---\n\(notes[0])\n--- target ---\n\(target)\n--- compositions (first 1200 chars) ---\n\(comps.prefix(1200))")
    }
}
