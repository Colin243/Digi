import Foundation

/// One recommended shot. The superset of shot-v1/v2/v3 in photography-ai/src/photo_ai/schema.py.
/// Decoding is lenient, like the Python schema: a missing text field is "", a single string where
/// a list is expected becomes a one-item list.
public struct Shot: Codable, Equatable, Sendable, Identifiable {
    public var id: String { title + "|" + cameraPosition }

    // shot-v3 reasoning (before the instructions)
    public var sceneReading: String
    public var setupChoice: String
    public var whyEachChoice: [String]
    public var fixIfWrong: [String]
    // shot-v1 core
    public var title: String
    public var usesPrinciple: String
    public var cameraPosition: String
    public var cameraHeight: String
    public var cameraAngle: String
    public var subjectPosition: String
    public var distanceAndFraming: String
    public var orientation: String
    public var zoomOrLens: String
    public var lightingTip: String
    public var visibleEvidence: [String]
    public var needsOnSiteCheck: [String]
    public var steps: [String]
    // shot-v2 subject direction
    public var bodyPose: String
    public var headDirection: String
    public var gaze: String
    public var expressionCue: String
    /// Place facts the model reports for the zoom rule: "yes", "no" or empty when the model did not say.
    public var roomToStepBack: String = ""
    public var backgroundWorthEnlarging: String = ""

    public init(
        title: String, cameraPosition: String, cameraHeight: String, cameraAngle: String,
        subjectPosition: String, sceneReading: String = "", setupChoice: String = "",
        whyEachChoice: [String] = [], fixIfWrong: [String] = [], usesPrinciple: String = "",
        distanceAndFraming: String = "", orientation: String = "", zoomOrLens: String = "",
        lightingTip: String = "", visibleEvidence: [String] = [], needsOnSiteCheck: [String] = [],
        steps: [String] = [], bodyPose: String = "", headDirection: String = "", gaze: String = "",
        expressionCue: String = ""
    ) {
        self.title = title; self.cameraPosition = cameraPosition; self.cameraHeight = cameraHeight
        self.cameraAngle = cameraAngle; self.subjectPosition = subjectPosition
        self.sceneReading = sceneReading; self.setupChoice = setupChoice
        self.whyEachChoice = whyEachChoice; self.fixIfWrong = fixIfWrong
        self.usesPrinciple = usesPrinciple; self.distanceAndFraming = distanceAndFraming
        self.orientation = orientation; self.zoomOrLens = zoomOrLens; self.lightingTip = lightingTip
        self.visibleEvidence = visibleEvidence; self.needsOnSiteCheck = needsOnSiteCheck
        self.steps = steps; self.bodyPose = bodyPose; self.headDirection = headDirection
        self.gaze = gaze; self.expressionCue = expressionCue
    }

    enum CodingKeys: String, CodingKey {
        case sceneReading = "scene_reading", setupChoice = "setup_choice"
        case whyEachChoice = "why_each_choice", fixIfWrong = "fix_if_wrong"
        case title, usesPrinciple = "uses_principle", cameraPosition = "camera_position"
        case cameraHeight = "camera_height", cameraAngle = "camera_angle"
        case subjectPosition = "subject_position", distanceAndFraming = "distance_and_framing"
        case orientation, zoomOrLens = "zoom_or_lens", lightingTip = "lighting_tip"
        case visibleEvidence = "visible_evidence", needsOnSiteCheck = "needs_on_site_check", steps
        case bodyPose = "body_pose", headDirection = "head_direction", gaze
        case expressionCue = "expression_cue"
        case roomToStepBack = "room_to_step_back", backgroundWorthEnlarging = "background_worth_enlarging"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func text(_ k: CodingKeys) -> String { (try? c.decodeIfPresent(String.self, forKey: k)) ?? "" }
        func list(_ k: CodingKeys) -> [String] {
            if let l = try? c.decodeIfPresent([String].self, forKey: k) { return l }
            if let s = try? c.decodeIfPresent(String.self, forKey: k), !s.isEmpty { return [s] }
            return []
        }
        sceneReading = text(.sceneReading); setupChoice = text(.setupChoice)
        whyEachChoice = list(.whyEachChoice); fixIfWrong = list(.fixIfWrong)
        title = text(.title); usesPrinciple = text(.usesPrinciple)
        cameraPosition = text(.cameraPosition); cameraHeight = text(.cameraHeight)
        cameraAngle = text(.cameraAngle); subjectPosition = text(.subjectPosition)
        distanceAndFraming = text(.distanceAndFraming); orientation = text(.orientation)
        zoomOrLens = text(.zoomOrLens); lightingTip = text(.lightingTip)
        visibleEvidence = list(.visibleEvidence); needsOnSiteCheck = list(.needsOnSiteCheck)
        steps = list(.steps); bodyPose = text(.bodyPose); headDirection = text(.headDirection)
        gaze = text(.gaze); expressionCue = text(.expressionCue)
        roomToStepBack = text(.roomToStepBack); backgroundWorthEnlarging = text(.backgroundWorthEnlarging)
    }

    /// The fields every shot must carry to be actionable (schema.py: Composition minimums).
    public var isActionable: Bool {
        ![title, cameraPosition, cameraHeight, cameraAngle, subjectPosition].contains { $0.isEmpty }
    }
}

public enum ShotFormat: String, Codable, Sendable { case v1, v2, v3 }
