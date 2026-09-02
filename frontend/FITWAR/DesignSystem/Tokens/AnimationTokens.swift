import SwiftUI

/// Animation timing, matching the prototype's `@keyframes` durations/easings
/// (`fwUp .3-.4s ease`, progress-bar transitions `.6-1.1s cubic-bezier(.2,.8,.2,1)`,
/// `fwPop .5s cubic-bezier(.2,.9,.2,1)`, `fwPulse 1.1-1.6s infinite`).
enum FWAnimation {
    /// Screen-entrance fade/slide-up (`fwUp`).
    static let entrance = Animation.easeOut(duration: 0.32)

    /// Progress bar / ring fills (`transition:width .6-1s cubic-bezier(.2,.8,.2,1)`).
    static let progressFill = Animation.timingCurve(0.2, 0.8, 0.2, 1, duration: 0.8)

    /// Success/checkmark pop-in (`fwPop`).
    static let pop = Animation.timingCurve(0.2, 0.9, 0.2, 1, duration: 0.5)

    /// Live/streaming pulse dot (`fwPulse`).
    static let pulse = Animation.easeInOut(duration: 1.4).repeatForever(autoreverses: true)

    /// Pressed-state feedback on buttons (`style-active{transform:scale(.985)}`).
    static let press = Animation.easeOut(duration: 0.12)
}
