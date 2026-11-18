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
    public static func rewriteDistance(_ text: String, zoom: Double) -> String {
        guard zoom > 1.01, let r = text.range(of: #"\d+(?:\.\d+)?\s*m\b"#, options: .regularExpression),
              let n = Self.parseMeters(String(text[r])) else { return text }
        let scaled = (n * zoom * 10).rounded() / 10
        let shown = scaled.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(scaled)) : String(scaled)
        return text.replacingCharacters(in: r, with: "\(shown) m")
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
    /// zoom is replaced, so a 2x look cannot arrive with the 1x distance. The distance text is treated as the 1x distance.
    public static func resolved(_ shot: Shot) -> Shot {
        let facts = infer(from: shot)
        let plan = make(oneXDistanceMeters: parseMeters(shot.distanceAndFraming), room: facts.room, background: facts.background)
        var out = shot
        if plan.zoom > 1.01 {
            let z = plan.zoom.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(plan.zoom)) : String(plan.zoom)
            out.zoomOrLens = "\(z)x, stand further back and zoom in"
            out.distanceAndFraming = rewriteDistance(shot.distanceAndFraming, zoom: plan.zoom)
        } else {
            out.zoomOrLens = "1x main lens"
        }
        return out
    }
}
