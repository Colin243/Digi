import Foundation

/// Zoom decided by a rule from facts about the place, not written by the language model. The model kept
/// collapsing to one amount (3, 26, then 1 looks at 2x across three runs on near-identical data) and
/// writing a 2x look with the 1x distance. Splitting the job fixes both: the model describes the shot and the
/// place, and this function turns the place facts into a zoom and a distance that matches it.
public struct ZoomPlan: Equatable, Sendable {
    /// Can the photographer stand about twice as far back?
    public enum Room: String, Codable, Sendable { case yes, maybe, no, unknown }
    /// What the background offers.
    public enum Background: String, Codable, Sendable {
        /// A distant shape worth enlarging (tree line, tower, arch, peaks) or clutter worth cropping out.
        case worthEnlarging
        /// The place itself is the point, or there is nothing distinct behind the subject.
        case neutral
    }

    public var zoom: Double
    /// Where to stand: the 1x distance multiplied by the zoom, so the subject keeps the same size.
    public var distanceMeters: Double?

    public static func make(oneXDistanceMeters: Double?, room: Room, background: Background) -> ZoomPlan {
        let zoom: Double
        switch (room, background) {
        case (.yes, .worthEnlarging): zoom = 2
        case (.maybe, .worthEnlarging): zoom = 1.5
        default: zoom = 1
        }
        let rounded = oneXDistanceMeters.map { ($0 * zoom * 10).rounded() / 10 }
        return ZoomPlan(zoom: zoom, distanceMeters: rounded)
    }

    /// First distance in metres in text such as "about 2 m, half body" or "2-3 m away"; the nearer end of a range.
    public static func parseMeters(_ text: String) -> Double? {
        let s = text.lowercased()
        guard let r = s.range(of: #"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(?:\d+(?:\.\d+)?)?\s*m\b"#, options: .regularExpression) else { return nil }
        let part = String(s[r])
        guard let n = part.range(of: #"\d+(?:\.\d+)?"#, options: .regularExpression) else { return nil }
        return Double(part[n])
    }

    /// The shot's own distance text rewritten for the zoom, e.g. "about 2 m, half body" at 2x becomes "about 4 m, half body".
    /// Text that already names its zoom ("About 2.4 m at 2x", shot formats v5-v7) is first turned back into the 1x
    /// distance, then rewritten whole, so the distance and the "at <zoom>x" always match the zoom the app uses.
    public static func rewriteDistance(_ text: String, zoom: Double) -> String {
        if let (r, meters, atZoom) = distanceAtZoom(text) {
            let oneX = meters / atZoom
            return text.replacingCharacters(in: r, with: "\(number(oneX * zoom)) m at \(number(zoom))x")
        }
        guard zoom > 1.01, let r = text.range(of: #"\d+(?:\.\d+)?\s*m\b"#, options: .regularExpression),
              let n = Self.parseMeters(String(text[r])) else { return text }
        return text.replacingCharacters(in: r, with: "\(number(n * zoom)) m")
    }

    /// The distance as if shot at 1x: "About 2.4 m at 2x" is 1.2 m; text without a zoom is already a 1x distance.
    public static func oneXMeters(_ text: String) -> Double? {
        if let (_, meters, atZoom) = distanceAtZoom(text) { return meters / atZoom }
        return parseMeters(text)
    }

    /// "<N> m at <K>x" in the text: its range, N and K (K between 1 and 3, else ignored).
    static func distanceAtZoom(_ text: String) -> (Range<String.Index>, Double, Double)? {
        guard let r = text.range(of: #"\d+(?:\.\d+)?\s*m\s+at\s+\d+(?:\.\d+)?\s*[x×]"#, options: [.regularExpression, .caseInsensitive]) else { return nil }
        var nums: [Double] = [], rest = Substring(text[r])
        while let n = rest.range(of: #"\d+(?:\.\d+)?"#, options: .regularExpression) {
            if let v = Double(rest[n]) { nums.append(v) }
            rest = rest[n.upperBound...]
        }
        guard nums.count == 2, nums[1] >= 1, nums[1] <= 3 else { return nil }
        return (r, nums[0], nums[1])
    }

    static func number(_ x: Double) -> String {
        let v = (x * 10).rounded() / 10
        return v.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(v)) : String(v)
    }

    // MARK: - From the shot's own words

    /// Room to step back and what the background offers, read from the shot's text. Only clear wording counts;
    /// anything else is unknown, which means no zoom (1x is the safe answer).
    public static func infer(from shot: Shot) -> (room: Room, background: Background) {
        // The model's own answers win when it gave them (trained fields); the text rules below are the fallback.
        let askedRoom = shot.roomToStepBack.lowercased().trimmingCharacters(in: .whitespaces)
        let askedBackground = shot.backgroundWorthEnlarging.lowercased().trimmingCharacters(in: .whitespaces)
        if ["yes", "no"].contains(askedRoom), ["yes", "no"].contains(askedBackground) {
            return (askedRoom == "yes" ? .yes : .no, askedBackground == "yes" ? .worthEnlarging : .neutral)
        }
        let text = ([shot.cameraPosition, shot.distanceAndFraming, shot.sceneReading, shot.setupChoice, shot.title]
            + shot.steps + shot.needsOnSiteCheck + shot.visibleEvidence).joined(separator: " ").lowercased()
        func has(_ patterns: [String]) -> Bool { patterns.contains { text.range(of: $0, options: .regularExpression) != nil } }

        let tight = [#"\b(narrow|cramped|tight|small|limited|little) (space|room|hallway|corridor|area)"#, #"\b(hallway|corridor|elevator|doorway|stairwell)\b"#,
                     #"(wall|desk|table|counter|couch|sofa|railing) (is )?(right )?behind you"#, #"can'?t (step|move|go) back"#, #"no room to"#]
        let roomy = [#"\b(open|wide|large|big|spacious) (space|area|plaza|square|lawn|field|courtyard|street|path|terrace|room)"#,
                     #"\b(plenty of|lots of|enough|good|ample) (room|space)"#, #"\b(plaza|lawn|field|park|beach|courtyard|promenade)\b"#,
                     #"step(ping)? (well )?back"#, #"walk(ing)? back"#]
        let room: Room = has(tight) ? .no : (has(roomy) ? .yes : .unknown)

        let distinct = [#"\b(tree ?line|tower|spire|arch|archway|mountains?|peaks?|skyline|monument|bridge|cathedral|temple|pagoda|lighthouse|clock tower|steeple|hills?|cliff|skyscrapers?)\b"#,
                        #"(clutter|crowd|cars?|signs?|power lines?|scaffolding) (behind|in the background)"#, #"\bdistant\b"#]
        return (room, has(distinct) ? .worthEnlarging : .neutral)
    }

    /// The shot with the rule's zoom written into its lens line and its distance rewritten to match. The model's own
    /// zoom is replaced, so a 2x look cannot arrive with the 1x distance. Distance text without a zoom is treated as
    /// the 1x distance; "About 2.4 m at 2x" (shot formats v5-v7) is converted back to its 1x distance first.
    public static func resolved(_ shot: Shot) -> Shot {
        let facts = infer(from: shot)
        let plan = make(oneXDistanceMeters: oneXMeters(shot.distanceAndFraming), room: facts.room, background: facts.background)
        var out = shot
        if plan.zoom > 1.01 {
            out.zoomOrLens = "\(number(plan.zoom))x, stand further back and zoom in"
        } else {
            out.zoomOrLens = "1x main lens"
        }
        out.distanceAndFraming = rewriteDistance(shot.distanceAndFraming, zoom: plan.zoom)
        return out
    }
}
