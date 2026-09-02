import SwiftUI

/// Thin rounded linear progress bar (`height:4-10px;border-radius:99px`), used for
/// challenge progress, XP, and the battle "vs" split throughout the design.
struct FWProgressBar: View {
    /// 0...1
    let progress: Double
    var height: CGFloat = 6
    var trackColor: Color = FWColor.surface2
    var fillColor: Color = FWColor.accent

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(trackColor)
                Capsule()
                    .fill(fillColor)
                    .frame(width: geo.size.width * max(0, min(1, progress)))
                    .animation(FWAnimation.progressFill, value: progress)
            }
        }
        .frame(height: height)
        .accessibilityElement(children: .ignore)
        .accessibilityValue("\(Int(progress * 100)) percent")
    }
}

/// Circular ring progress (the Challenge Detail hero metric — SVG
/// `stroke-dasharray`/`stroke-dashoffset` ring in the prototype).
struct FWProgressRing: View {
    /// 0...1
    let progress: Double
    var lineWidth: CGFloat = 14
    var size: CGFloat = 206
    var trackColor: Color = FWColor.surface2
    var fillColor: Color = FWColor.accent

    /// The prototype draws r=85 inside a 206px box, so the stroke sits inset from the
    /// edge rather than hugging it. A bare `Circle()` inscribes its whole frame, which
    /// renders noticeably larger — this reproduces the source ratio instead.
    private var ringDiameter: CGFloat { size * (85.0 / 103.0) }

    var body: some View {
        ZStack {
            Circle().stroke(trackColor, lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: max(0, min(1, progress)))
                .stroke(fillColor, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(FWAnimation.progressFill, value: progress)
        }
        .frame(width: ringDiameter, height: ringDiameter)
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityValue("\(Int(progress * 100)) percent")
    }
}

/// Level/XP bar (Home header, XP screen): thin bar + "620 / 1000 XP" meta label.
struct XPBar: View {
    let currentXP: Int
    let xpToNextLevel: Int
    var width: CGFloat? = 190

    private var progress: Double {
        xpToNextLevel > 0 ? Double(currentXP) / Double(xpToNextLevel) : 0
    }

    var body: some View {
        FWProgressBar(progress: progress, height: 4)
            .frame(width: width)
            .accessibilityLabel("Experience progress")
            .accessibilityValue("\(currentXP) of \(xpToNextLevel) XP")
    }
}
