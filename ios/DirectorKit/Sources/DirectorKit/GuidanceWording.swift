import Foundation

// The words on the camera screen, per style and language. The engine keeps producing the same cues;
// this maps a cue's meaning (`CueVariant`) to text. Full info is today's terse text, Soft is warm and
// plain (no degrees, no axis names), Minimal is the fewest words that still work.

public enum GuidanceLanguage: Sendable {
    case en, zh

    /// Chinese when the user's first preferred language is Chinese, otherwise English.
    public static var current: GuidanceLanguage {
        Locale.preferredLanguages.first?.hasPrefix("zh") == true ? .zh : .en
    }
}

/// Fixed messages that are not engine cues.
public enum GuidanceMessage: Sendable, CaseIterable {
    case satisfied, headRight, watchingHead, noChecks, noHeadChecks
}

public enum GuidanceWording {
    /// Text for one cue. Cues without a variant keep the engine's own text.
    public static func text(for cue: GuidanceCue, style: GuidanceStyle, language: GuidanceLanguage = .current) -> String {
        guard let v = cue.variant else { return cue.text }
        switch (language, style) {
        case (.en, .full): return cue.text
        case (.en, .soft): return enSoft(v)
        case (.en, .minimal): return enMinimal(v)
        case (.zh, .full): return zhFull(v)
        case (.zh, .soft): return zhSoft(v)
        case (.zh, .minimal): return zhMinimal(v)
        }
    }

    /// Empty string means "show no words" (Minimal's quiet confirmations). Show an icon instead.
    public static func text(_ m: GuidanceMessage, style: GuidanceStyle, language: GuidanceLanguage = .current) -> String {
        switch (language, style, m) {
        case (.en, .full, .satisfied): return "In position. Take the shot"
        case (.en, .full, .headRight): return "Head looks right"
        case (.en, .full, .watchingHead): return "Watching their head…"
        case (.en, .full, .noChecks): return "No live checks for this shot"
        case (.en, .full, .noHeadChecks): return "Nothing in this direction the camera can check."
        case (.en, .soft, .satisfied): return "Nice, hold it there"
        case (.en, .soft, .headRight): return "Their pose looks great"
        case (.en, .soft, .watchingHead): return "Checking their pose…"
        case (.en, .soft, .noChecks): return "Nothing to check for this shot"
        case (.en, .soft, .noHeadChecks): return "Nothing here the camera can check"
        case (.zh, .full, .satisfied): return "位置正确，拍吧"
        case (.zh, .full, .headRight): return "头部位置正确"
        case (.zh, .full, .watchingHead): return "正在观察对方的头部…"
        case (.zh, .full, .noChecks): return "这个镜头没有可实时检查的项目"
        case (.zh, .full, .noHeadChecks): return "这个方向没有相机可检查的内容"
        case (.zh, .soft, .satisfied): return "很棒，保持住"
        case (.zh, .soft, .headRight): return "对方的姿势很好"
        case (.zh, .soft, .watchingHead): return "正在看对方的姿势…"
        case (.zh, .soft, .noChecks): return "这个机位没有需要检查的"
        case (.zh, .soft, .noHeadChecks): return "这里没有相机能检查的内容"
        case (_, .minimal, _): return ""
        }
    }

    // MARK: English

    private static func enSoft(_ v: CueVariant) -> String {
        switch v {
        case .holdUpright: return "Hold the phone upright"
        case .turnSideways: return "Turn the phone sideways"
        case .straighten(let left): return "Level it out: turn the phone a little \(left ? "left" : "right")"
        case .tilt(let up, _): return "Tilt the phone \(up ? "up" : "down") a little"
        case .findSubject(let chosen): return chosen ? "Find the person you picked" : "Point the camera at your subject"
        case .closer(let z): return z ? "Step a little closer, or zoom in" : "Step a little closer"
        case .back(let z): return z ? "Step back a little, or zoom out" : "Step back a little"
        case .pan(let right, _): return "Pan a little \(right ? "right" : "left")"
        case .findFace: return "Get their face in view"
        case .headTurn(let t):
            switch t {
            case .subjectLeft: return "Ask them to turn a little to their left"
            case .subjectRight: return "Ask them to turn a little to their right"
            case .awayFromCamera: return "Ask them to turn a little away from you"
            case .towardCamera: return "Ask them to turn back toward you"
            }
        case .chin(let up): return "Ask them to \(up ? "lift" : "lower") their chin a little"
        }
    }

    private static func enMinimal(_ v: CueVariant) -> String {
        switch v {
        case .holdUpright: return "upright"
        case .turnSideways: return "sideways"
        case .straighten: return "level"
        case .tilt(let up, _): return "tilt \(up ? "up" : "down")"
        case .findSubject: return "find subject"
        case .closer: return "closer"
        case .back: return "back"
        case .pan(let right, _): return "pan \(right ? "right" : "left")"
        case .findFace: return "find face"
        case .headTurn(let t):
            switch t {
            case .subjectLeft: return "they turn left"
            case .subjectRight: return "they turn right"
            case .awayFromCamera: return "they turn away"
            case .towardCamera: return "they turn back"
            }
        case .chin(let up): return "chin \(up ? "up" : "down")"
        }
    }

    // MARK: Chinese

    private static func zhFull(_ v: CueVariant) -> String {
        switch v {
        case .holdUpright: return "请竖着拿手机"
        case .turnSideways: return "请横着拿手机"
        case .straighten(let left): return "摆正：手机向\(left ? "左" : "右")旋转"
        case .tilt(let up, let n): return "向\(up ? "上" : "下")倾斜 \(n)°"
        case .findSubject(let chosen): return chosen ? "找到你选的人" : "把镜头对准主体"
        case .closer(let z): return z ? "靠近或放大" : "靠近一点"
        case .back(let z): return z ? "后退或缩小" : "后退一点"
        case .pan(let right, let goal):
            let target = goal == "center" ? "让主体居中" : "让主体落在\(goal == "left" ? "左" : "右")三分线"
            return "向\(right ? "右" : "左")平移，\(target)"
        case .findFace: return "还看不到对方的脸"
        case .headTurn(let t):
            switch t {
            case .subjectLeft: return "对他说：“头稍微向你的左边转”"
            case .subjectRight: return "对他说：“头稍微向你的右边转”"
            case .awayFromCamera: return "对他说：“头稍微转开，不要朝向我”"
            case .towardCamera: return "对他说：“稍微转回来朝向我”"
            }
        case .chin(let up): return "对他说：“下巴稍微\(up ? "抬高" : "收一点")”"
        }
    }

    private static func zhSoft(_ v: CueVariant) -> String {
        switch v {
        case .holdUpright: return "请竖着拿手机"
        case .turnSideways: return "请横过来拿手机"
        case .straighten(let left): return "手机往\(left ? "左" : "右")转一点点，把画面摆正"
        case .tilt(let up, _): return "手机稍微往\(up ? "上抬" : "下压")一点"
        case .findSubject(let chosen): return chosen ? "找一下你选的那位" : "把镜头对准你要拍的人"
        case .closer(let z): return z ? "再靠近一点，或者放大一点" : "再靠近一点"
        case .back(let z): return z ? "往后退一点，或者缩小一点" : "往后退一点"
        case .pan(let right, _): return "镜头往\(right ? "右" : "左")移一点"
        case .findFace: return "让对方的脸入镜"
        case .headTurn(let t):
            switch t {
            case .subjectLeft: return "请对方稍微往自己的左边转头"
            case .subjectRight: return "请对方稍微往自己的右边转头"
            case .awayFromCamera: return "请对方稍微转头避开镜头"
            case .towardCamera: return "请对方稍微转回来看向镜头"
            }
        case .chin(let up): return "请对方稍微\(up ? "抬一点" : "收一点")下巴"
        }
    }

    private static func zhMinimal(_ v: CueVariant) -> String {
        switch v {
        case .holdUpright: return "竖拿"
        case .turnSideways: return "横拿"
        case .straighten: return "摆正"
        case .tilt(let up, _): return up ? "上仰" : "下压"
        case .findSubject: return "找主体"
        case .closer: return "靠近"
        case .back: return "后退"
        case .pan(let right, _): return right ? "右移" : "左移"
        case .findFace: return "找脸"
        case .headTurn(let t):
            switch t {
            case .subjectLeft: return "对方左转"
            case .subjectRight: return "对方右转"
            case .awayFromCamera: return "对方转开"
            case .towardCamera: return "对方转回"
            }
        case .chin(let up): return up ? "抬下巴" : "收下巴"
        }
    }
}
